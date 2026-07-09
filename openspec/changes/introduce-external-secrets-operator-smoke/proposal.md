## Why

Backlog 0015 is ready for OpenSpec because it names a concrete platform service, an operator-visible end-to-end outcome, and a validation application service consumer. The first installable slice deliberately deferred External-Secrets Operator (ESO); this change brings ESO back as the next narrow platform services slice without expanding the platform catalog or making secret projection a prerequisite for bootstrap installation.

Kubecrate needs to prove that application services can consume narrowed projected Secrets instead of reading broad bootstrap trust material directly. A kind-first ESO smoke slice gives that proof with the smallest production-inspired shape: install ESO as a GitOps-managed platform service, seed local source material only for the smoke path, project a service-specific Secret, and have CrateCheck report, through its normal check framework, that the ESO secret projection path is operational.

## What Changes

- Introduce External-Secrets Operator as a real platform service for the kind-first local path.
- Place the reusable ESO platform service base under `platform-services/external-secrets-operator/base/` and the `kind-dev-misc-local` binding under `clusters/kind-dev-misc-local/platform-services/external-secrets-operator/`.
- Use namespace `core-external-secrets-operator` for ESO because it is a dedicated platform service namespace and follows the `core-<service-name>` rule.
- Keep ESO under GitOps-managed operation. Bootstrap installation remains responsible only for reaching the GitOps handoff; this change may document or provide a post-bootstrap seed step for local source material, but it does not make ESO bootstrap-critical.
- Add the minimum local secret projection path using the ESO Kubernetes provider that proves projection from locally seeded Kubernetes Secret material.
- Integrate with CrateCheck so that ESO-related checks (HelmRelease readiness, SecretStore readiness, ExternalSecret readiness, projected Secret existence) are validated through CrateCheck's standard check framework and appear in CrateCheck's status output.
- Define AI-runnable acceptance evidence that proves installation, controller health, provider readiness, ExternalSecret readiness, target Secret creation, and a red test where intentional breakage makes CrateCheck report the ESO path as non-green, then restored green.

## Capabilities

### New Capabilities

- `external-secrets-operator-smoke`: Defines the bounded External-Secrets Operator smoke-test vertical slice for secret projection on the kind-first local path.

### Modified Capabilities

- `cratecheck`: Extends CrateCheck check configuration and RBAC to validate ESO platform service health and secret projection path.

## Impact

- Adds one GitOps-managed platform service and one end-to-end platform service consumption proof through CrateCheck.
- Adds only the runtime manifests, configuration, and validation commands needed for ESO secret projection on `kind-dev-misc-local`.
- Does not introduce provider-specific external backends such as AWS Secrets Manager, GCP Secret Manager, Vault, or production credential flows.
- Does not make ESO part of bootstrap installation acceptance or change the first Flux bootstrap contract.
- Does not add an ESO-specific status app, ingress, certificate management, observability, Kyverno, wave-like promotion mechanics, or broader secret-management policy.
- Preserves Kubecrate's two-axis model: lifecycle phase remains bootstrap installation or GitOps-managed operation, and workload category remains platform services or application services.
