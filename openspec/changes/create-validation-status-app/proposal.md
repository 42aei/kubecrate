## Why

Backlog 0014 is the first concrete follow-up from the post-baseline platform services discussion. Future platform service slices need a shared, AI-runnable application service fixture that proves real consumption through status output rather than only proving that controllers installed.

This change defines that validation application service before ESO, ingress, certificate management, or policy work depends on it.

## What Changes

- Introduce a reusable application service validation status app for the kind-first local path, consuming the external CrateCheck image (`ghcr.io/42aei/cratecheck:v1`) rather than embedding application runtime code.
- Define the app as an application service fixture, not a platform service.
- Deploy CrateCheck with a plain declarative YAML check config (CEL-based checks against live Kubernetes resources) stored in a ConfigMap. No Python, JS, Go, or runtime code in ConfigMaps.
- Provide a polished human-readable status UI (`/status`) and a machine-readable status JSON endpoint (`/status.json`) served by CrateCheck.
- Define initial baseline checks (CrateCheck deployment readiness, namespace existence, ConfigMap presence) with future check categories for secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior.
- Add read-only Kubernetes RBAC (ClusterRole `cratecheck-readonly`) scoped to initial check resources plus discovery API access, documented for incremental expansion.
- Define the runtime placement: `application-services/cratecheck/base/` for reusable base, `clusters/kind-dev-misc-local/application-services/cratecheck/` for cluster binding, wired through `clusters/kind-dev-misc-local/entrypoint/` for GitOps-managed operation.
- Define AI-runnable validation commands that can fetch the status JSON and assert expected checks for the capabilities enabled by this slice.

## Capabilities

### New Capabilities

- `application-service-validation`: Defines the reusable validation application service fixture, its status UI, status JSON, check model, placement, and validation expectations.

### Modified Capabilities

- None.

## Impact

- Adds an approved application service fixture under the application service layout for the kind-first local path.
- May add minimal source code, container packaging, manifests, cluster binding, and validation/evidence commands needed for the fixture.
- Does not add ESO, ingress, cert-manager, observability, Kyverno, or other platform services.
- Does not make the validation app part of bootstrap installation; it is reconciled through GitOps-managed operation as an application service.
- Preserves the two-axis model: lifecycle phase remains separate from workload category, and the validation app remains application services scope.
