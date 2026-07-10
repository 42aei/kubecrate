## Why

Backlog 0016 identifies Envoy Gateway as the next platform service after Flux self-management is proven. Introducing HTTP ingress on the kind-first local path unblocks the real platform service validation contract: an application service (CrateCheck) reachable through the ingress path, with CrateCheck status checks verifying the ingress pipeline end-to-end.

This change keeps the first ingress slice minimal: prove HTTP reachability for CrateCheck before adding TLS, multi-host routing, or advanced policies.

## What Changes

- **Introduce Envoy Gateway as a platform service**: install Envoy Gateway via HelmRelease (chart `gateway-helm` v1.4.2) in namespace `core-envoy-gateway`, following the two-axis model and `core-<service-name>` namespace pattern.
- **Add EnvoyProxy configuration for kind NodePort exposure**: configure the managed Envoy proxy Service as `NodePort` via an `EnvoyProxy` resource, referenced by the smoke `GatewayClass`, so ingress traffic reaches the kind node port mapped by `kind/config.yaml` (host 10080 → container 30080).
- **Add smoke Gateway API resources**: a `GatewayClass`, `Gateway`, and `HTTPRoute` under the cluster smoke path, routing HTTP traffic to the CrateCheck Service.
- **Add CrateCheck status checks for Envoy Gateway**: four CrateCheck checks (`envoy-helmrelease-ready`, `envoy-gatewayclass-accepted`, `envoy-gateway-ready`, `envoy-httproute-ready`) that validate the Envoy Gateway installation and HTTP route readiness. The route check requires both `Accepted=True` and `ResolvedRefs=True` so the documented controlled red test (backend port change) is detectable.
- **Provide a validation runbook**: document via `docs/kind-envoy-gateway-ingress-runbook.md` how to validate ingress end-to-end: reconcile, inspect resources, reach CrateCheck /status.json through the ingress path (`127.0.0.1:10080`), and execute the controlled red test.
- **Add Envoy Gateway to the cluster entrypoint**: wire Envoy Gateway platform service Kustomization and smoke Kustomization into `clusters/kind-dev-misc-local/entrypoint/` so Flux reconciles them.
- **Add CrateCheck RBAC for Envoy Gateway resources**: the CrateCheck ClusterRole already includes read access to `helmreleases`, `gatewayclasses`, `gateways`, and `httproutes`.
- **Provide QA branch override mechanism**: document how to override the Flux sync branch for disposable QA clusters without hardcoding a PR branch in committed configuration.

## Capabilities

### New Capabilities

- `envoy-gateway-ingress`: Envoy Gateway installed as a platform service on the kind-first local path, with HTTP ingress reachability for the CrateCheck application service, CrateCheck status checks covering the ingress pipeline, and a documented validation runbook with controlled red test.

### Modified Capabilities

None.

## Impact

- Adds Envoy Gateway as the first post-Flux platform service, validating the two-axis model extension to platform services beyond Flux.
- Keeps the ingress slice minimal: HTTP only, single Gateway, single HTTPRoute to CrateCheck, no TLS, no multi-host routing.
- Preserves the kind-first local path and operator-visible outcome validation through CrateCheck status JSON.
- Does not require changes to bootstrap installation or Flux self-management.
