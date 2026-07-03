## Why

Backlog 0014 is the first concrete follow-up from the post-baseline platform services discussion. Future platform service slices need a shared, AI-runnable application service fixture that proves real consumption through status output rather than only proving that controllers installed.

This change defines that validation application service before ESO, ingress, certificate management, or policy work depends on it.

## What Changes

- Introduce a reusable application service validation status app for the kind-first local path.
- Define the app as an application service fixture, not a platform service.
- Define a polished human-readable status UI and a machine-readable status JSON endpoint.
- Define a status-check contract where each check reports status, the capability it validates, the platform or Kubernetes area it exercises, and troubleshooting guidance for non-green states.
- Define initial check categories that future platform service slices can enable: base app health, secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior.
- Define the minimum runtime placement for the fixture only for this approved slice, without creating unrelated application service skeletons.
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
