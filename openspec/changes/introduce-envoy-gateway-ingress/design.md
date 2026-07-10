## Context

Backlog 0016 identifies Envoy Gateway as the next platform service after Flux self-management is proven by the first installable slice (OpenSpec `create-first-installable-slice`). The first installable slice explicitly excludes ingress from its scope. This change introduces ingress as a focused follow-on vertical slice.

The CrateCheck application service already exists as the validation target. It serves `/status.json` and `/status` (HTML UI) from namespace `cratecheck`. Envoy Gateway routes HTTP traffic to the CrateCheck Service, and CrateCheck status checks validate the ingress pipeline end-to-end.

## Goals / Non-Goals

**Goals:**

- Install Envoy Gateway via HelmRelease on the kind-first local path as a GitOps-managed platform service.
- Configure the managed Envoy proxy Service as NodePort so ingress traffic reaches the kind node port mapped by `kind/config.yaml` (host 10080 → container 30080).
- Route HTTP traffic to the CrateCheck Service via Gateway API resources (GatewayClass, Gateway, HTTPRoute).
- Add CrateCheck status checks that validate the entire Envoy Gateway ingress pipeline: HelmRelease readiness, GatewayClass acceptance, Gateway programming, and HTTPRoute acceptance with backend reference resolution.
- Provide a documented validation runbook with host-side ingress requests to CrateCheck and a controlled red test.
- Keep the first ingress slice minimal: HTTP only, single Gateway, single HTTPRoute.

**Non-Goals:**

- TLS, certificate management, multi-host routing, or advanced Gateway API policies.
- External DNS, public exposure, or production-grade ingress.
- Ingress for services other than CrateCheck.
- Modifications to bootstrap installation or Flux self-management.

## Decisions

### Envoy Gateway as the ingress implementation

Envoy Gateway is chosen as the ingress implementation per backlog 0016 guidance. It is installed via HelmRelease under `platform-services/envoy-gateway/base/` with cluster binding at `clusters/kind-dev-misc-local/platform-services/envoy-gateway/`.

The Helm chart `gateway-helm` version `v1.4.2` is used with the Kubernetes provider. The namespace `core-envoy-gateway` follows the `core-<service-name>` pattern for platform service dedicated namespaces.

### EnvoyProxy for kind NodePort exposure

The kind `config.yaml` maps host port 10080 to container port 30080. For ingress traffic to reach the cluster through this mapping, the Envoy proxy Service must be of type `NodePort` on port 30080.

An `EnvoyProxy` resource (CRD `gateway.envoyproxy.io/v1alpha1`) configures the managed proxy infrastructure. The smoke `GatewayClass` references the `EnvoyProxy` via `parametersRef`. The `EnvoyProxy` sets `provider.kubernetes.envoyService.type: NodePort` and uses `envoyService.patch` to declaratively pin the Service `nodePort` to 30080, matching the kind config mapping.

### Smoke Gateway API resources

The smoke resources live under `clusters/kind-dev-misc-local/platform-services/envoy-gateway/smoke/` and are reconciled by a dedicated Flux `Kustomization` (`envoy-gateway-smoke`) that depends on the main `envoy-gateway` Kustomization.

- **GatewayClass** `kubecrate-envoy-gateway`: references the Envoy Gateway controller and the EnvoyProxy parameters.
- **Gateway** `kubecrate-envoy-smoke`: single HTTP listener on port 80, accepting routes from all namespaces.
- **HTTPRoute** `envoy-smoke-cratecheck`: routes path prefix `/` to the CrateCheck Service on port 8080 in namespace `cratecheck`.

### CrateCheck status checks for Envoy Gateway

Four CrateCheck checks validate the ingress pipeline:

1. `envoy-helmrelease-ready`: HelmRelease Ready condition for the Envoy Gateway chart.
2. `envoy-gatewayclass-accepted`: GatewayClass Accepted condition.
3. `envoy-gateway-ready`: Gateway Programmed condition.
4. `envoy-httproute-ready`: HTTPRoute Accepted AND ResolvedRefs conditions on the parent Gateway.

The `envoy-httproute-ready` check requires both `Accepted=True` and `ResolvedRefs=True` on the matching parent status entry. This ensures the documented controlled red test (changing the backend port to 9999, which breaks `ResolvedRefs`) is detectable by CrateCheck.

### Controlled red test

The runbook documents a green → controlled red → restore green cycle:

1. Prove all Envoy checks green with the correct backend port 8080.
2. Patch the HTTPRoute backend port to 9999 (breaks `ResolvedRefs`).
3. Verify `envoy-httproute-ready` reports non-green.
4. Restore the backend port to 8080.
5. Verify `envoy-httproute-ready` returns to green.

### CrateCheck RBAC scope

The CrateCheck ClusterRole already includes:
- `helmreleases` (group `helm.toolkit.fluxcd.io`) — get
- `gatewayclasses`, `gateways`, `httproutes` (group `gateway.networking.k8s.io`) — get

No RBAC changes are required for this slice.

### QA branch override for disposable Flux

The committed `helm-values-sync.yaml` pins the Flux sync branch to the canonical branch. For disposable QA clusters that need to reconcile a PR branch, set `FLUX_GIT_BRANCH_OVERRIDE` at bootstrap time:

```sh
make kind-dev-misc-local-bootstrap FLUX_GIT_BRANCH_OVERRIDE=kubecrate/cratecheck-restack-envoy
```

The `kind-dev-misc-local-bootstrap` target detects the override and patches the `flux-sync-values` ConfigMap after applying the entrypoint kustomization, before the `flux-system-sync` HelmRelease reconciles. This ensures the GitRepository is created with the QA branch from the start.

The `kind-dev-misc-local-await-gitops` target also honours `FLUX_GIT_BRANCH_OVERRIDE` when verifying the expected GitRepository branch, so downstream gitops readiness checks remain consistent.

## Risks / Trade-offs

- [Risk] The Envoy Gateway Helm chart v1.4.2 may have chart maintenance or community-status changes. → Mitigation: version is pinned; revisit if upstream guidance changes.
- [Risk] The EnvoyProxy parametersRef requires the EnvoyProxy CRD to be installed before the GatewayClass is reconciled. → Mitigation: the Envoy Gateway HelmRelease installs the CRDs; the smoke Kustomization depends on the main Envoy Gateway Kustomization.
