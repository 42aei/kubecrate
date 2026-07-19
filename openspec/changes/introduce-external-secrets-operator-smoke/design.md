## Context

The first installable slice established Flux bootstrap installation and GitOps-managed operation without ESO. CrateCheck was introduced as an image-backed application service providing status/check validation. Backlog 0015 is the first concrete secret-handling platform service follow-up: prove that a platform service can project secrets and that CrateCheck can validate the full ESO path through its standard check framework.

This change intentionally stays kind-first and production-inspired but not production-ready. It proves the platform capability with local Kubernetes source material and a real CrateCheck validation path. Provider-specific external backends, production credential onboarding, rotation policy, and multi-environment promotion are deferred until there is a concrete operational need.

## Goals / Non-Goals

**Goals:**

- Add ESO as the next real GitOps-managed platform service for `kind-dev-misc-local`.
- Keep ESO independent from bootstrap installation acceptance while preserving handoff into GitOps-managed operation.
- Use `core-external-secrets-operator` as the dedicated ESO namespace.
- Prove projection from locally seeded Kubernetes Secret material into a narrow service-specific Secret.
- Extend CrateCheck with ESO validation checks: HelmRelease readiness, SecretStore readiness, ExternalSecret readiness, and projected Secret existence.
- Provide AI-runnable validation evidence that distinguishes ESO controller health, SecretStore readiness, ExternalSecret readiness, target Secret creation, and projected Secret existence.
- Include a red test that intentionally breaks the ESO path and proves CrateCheck reports ESO checks as non-green with useful diagnostics, then restores green.

**Non-Goals:**

- Making ESO bootstrap-critical for the first GitOps handoff.
- Installing or validating cloud secret providers, Vault, production credential stores, or real production secret material.
- Defining a complete secret-management policy, rotation model, multi-tenant tenancy model, or application developer self-service API beyond the smoke projection path.
- Replacing the Flux SSH deploy-key bootstrap contract from the first installable slice.
- Introducing ingress, certificate management, observability, Kyverno, or wave-like promotion mechanics.
- Creating a separate ESO-specific status app — CrateCheck is the single validation surface.

## Decisions

### ESO is a GitOps-managed platform service

ESO is operator-owned secret projection infrastructure and is therefore platform services scope. It is installed after the GitOps handoff through the existing `kind-dev-misc-local` entrypoint, not as a prerequisite for bootstrap installation.
The reusable service definition lives at `platform-services/external-secrets-operator/base/`. The concrete cluster binding lives at `clusters/kind-dev-misc-local/platform-services/external-secrets-operator/`. The cluster entrypoint includes Flux `Kustomization` objects for the ESO controller, the ESO smoke resources, and CrateCheck so Flux reconciles ESO through GitOps-managed operation with explicit ordering.

The ESO controller `Kustomization` reconciles only the ESO namespace, HelmRepository, HelmRelease, and values. The smoke `Kustomization` depends on the controller `Kustomization` before applying the SecretStore and ExternalSecret custom resources. CrateCheck is already present and reconciles independently; its check configuration is extended to include ESO checks.

Bootstrap installation may document any prerequisite seed input expected after handoff, but bootstrap installation does not install ESO or own its lifecycle in this slice.

### Namespace follows the core service rule

ESO uses namespace `core-external-secrets-operator`. This follows the `core-<service-name>` rule. The Flux `flux-system` exception remains limited to the GitOps controller bootstrap or self-management path.

### Local provider proves real projection

The acceptance proof uses the ESO Kubernetes provider to read source material from Kubernetes Secret state and project a narrower Secret for the smoke path. The source Secret is local smoke material only — non-sensitive fixture data, clearly named as validation material.

### CrateCheck is the validation surface

CrateCheck validates the ESO path through its standard check framework. ESO checks cover: HelmRelease controller health, SecretStore readiness, ExternalSecret readiness (synced status), and projected Secret existence. CrateCheck's ClusterRole is extended to read ESO-related resources (HelmRelease, SecretStore, ExternalSecret, Secrets). No separate ESO-specific status app is created.

CrateCheck's status output shows green ESO checks only when each resource is actually healthy. Non-green output guides the operator toward the likely layer: ESO controller health, provider readiness, ExternalSecret status, target Secret creation, or CrateCheck RBAC/permissions.

### Acceptance evidence is operational and end-to-end

Static rendering and OpenSpec validation are required but not sufficient. Runtime success requires kind-first operational evidence after reconciliation:

1. intended Kubernetes context targets `kind-dev-misc-local`;
2. ESO namespace, controller resources, and CRDs exist;
3. ESO controller workload is ready;
4. SecretStore is ready;
5. ExternalSecret is ready and has reconciled;
6. target Secret exists and contains only the intended narrow smoke key;
7. CrateCheck reports ESO checks as green;
8. recent events or logs do not show blocking reconciliation errors;
9. a red test intentionally breaks the ESO path, verifies CrateCheck reports ESO checks as non-green, then restores the path and verifies green again.

Deeper diagnosis stays symptom-driven.

## Risks / Trade-offs

- [Risk] Local Kubernetes source material can be mistaken for a production secret source. → Mitigation: keep it explicitly smoke-only, use non-sensitive fixture data, and defer production provider contracts.
- [Risk] Secret projection could be claimed by target Secret existence alone. → Mitigation: require CrateCheck to validate the full chain (controller, store, external secret, projected secret) and prove failure detection with a red test.
- [Risk] ESO install may become tangled with bootstrap installation. → Mitigation: keep ESO reconciled through GitOps-managed operation and state explicitly that bootstrap installation acceptance remains Flux handoff only.
- [Risk] The Kubernetes provider needs RBAC that is easy to over-broaden. → Mitigation: scope RBAC to the smoke source namespace and document any broader permission as out of scope unless a later change justifies it.

### Red test requirement

The implementation must include a controlled red test for CrateCheck's ESO checks. The red test should break the ESO projection path in a reversible way, such as deleting the source Secret, renaming the ExternalSecret target, or otherwise disrupting projection without exposing sensitive data. During the red test, CrateCheck must report the affected ESO checks as non-green with diagnostics that identify the likely layer. After the test, the implementation must restore the expected configuration and verify CrateCheck returns to green.
