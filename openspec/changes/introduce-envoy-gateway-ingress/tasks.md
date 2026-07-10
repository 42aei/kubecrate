## 1. Envoy Gateway platform service manifests

- [x] 1.1 Create `platform-services/envoy-gateway/base/` with namespace, HelmRepository, and HelmRelease for chart `gateway-helm` v1.4.2 in namespace `core-envoy-gateway`.
- [x] 1.2 Create `clusters/kind-dev-misc-local/platform-services/envoy-gateway/` cluster binding with `kustomization.yaml` and `helm-values.yaml`.
- [x] 1.3 Add `envoy-gateway` Flux Kustomization to `clusters/kind-dev-misc-local/entrypoint/` so Flux reconciles the Envoy Gateway platform service.

## 2. Smoke Gateway API resources

- [x] 2.1 Create `clusters/kind-dev-misc-local/platform-services/envoy-gateway/smoke/` with GatewayClass, Gateway, and HTTPRoute resources.
- [x] 2.2 Create EnvoyProxy resource with `provider.kubernetes.envoyService.type: NodePort` for kind NodePort exposure.
- [x] 2.3 Wire GatewayClass to reference the EnvoyProxy via `parametersRef`.
- [x] 2.4 Add `envoy-gateway-smoke` Flux Kustomization (depends on `envoy-gateway`) to the cluster entrypoint.

## 3. CrateCheck status checks for Envoy Gateway

- [x] 3.1 Add CrateCheck checks for `envoy-helmrelease-ready`, `envoy-gatewayclass-accepted`, `envoy-gateway-ready`, and `envoy-httproute-ready`.
- [x] 3.2 Ensure `envoy-httproute-ready` requires both `Accepted=True` and `ResolvedRefs=True` on the parent Gateway status.
- [x] 3.3 Verify CrateCheck RBAC covers all Envoy Gateway resources (helmreleases, gatewayclasses, gateways, httproutes).

## 4. Validation and runbook

- [x] 4.1 Create `docs/kind-envoy-gateway-ingress-runbook.md` with reconcile, inspect, and validation commands.
- [x] 4.2 Document host-side ingress request through `127.0.0.1:10080` to CrateCheck `/status.json`.
- [x] 4.3 Document green → controlled red → restore green cycle for the `envoy-httproute-ready` check.
- [x] 4.4 Document QA branch override mechanism for disposable Flux clusters.

## 5. Automated validation

- [x] 5.1 CrateCheck YAML parse and field validation passes for all 7 checks.
- [x] 5.2 CEL contract validation asserts `envoy-httproute-ready` references both `Accepted` and `ResolvedRefs` with `status == 'True'`.
- [x] 5.3 Kustomize build succeeds for base, cluster binding, smoke, and entrypoint.
- [x] 5.4 Kubeconform validates rendered manifests with no invalid resources.

## 6. OpenSpec authorization

- [x] 6.1 Create `openspec/changes/introduce-envoy-gateway-ingress/` with proposal, design, tasks, and spec.
- [x] 6.2 Update backlog 0016 status from `proposed` to `started` with reference to this OpenSpec change.
- [x] 6.3 Ensure no reference to obsolete `kubecrate-status`; all references use CrateCheck.
- [ ] 6.4 Obtain explicit human approval for this OpenSpec change. AGENTS.md currently only authorizes `create-first-installable-slice` as a proposal-approved change (AGENTS.md line 93). This `introduce-envoy-gateway-ingress` change was created alongside implementation and has no separate approval evidence. The repository maintainer (Christian) must explicitly approve this proposal before the runtime implementation is authorized per AGENTS.md line 3. Until then, task 6.1-6.3 are technical preparation only.
