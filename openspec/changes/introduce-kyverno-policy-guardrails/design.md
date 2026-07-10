## Context

The kind-first local path has Flux bootstrap installation and CrateCheck as the validation application service. Backlog 0018 introduces Kyverno as the policy guardrails platform service. This change adds Kyverno with a minimal smoke policy that proves admission control enforcement, validated end-to-end through CrateCheck.

This change intentionally stays kind-first and production-inspired but not production-ready. It proves the platform capability with a single namespace-labeling policy and CrateCheck validation. Production compliance profiles, multi-tenant governance, and background scanning are deferred.

## Goals / Non-Goals

**Goals:**

- Add Kyverno as the next real GitOps-managed platform service for `kind-dev-misc-local`.
- Keep Kyverno independent from bootstrap installation acceptance while preserving handoff into GitOps-managed operation.
- Use `core-kyverno` as the dedicated Kyverno namespace.
- Prove real admission control through a ClusterPolicy that requires a namespace label, with an allowed fixture that satisfies the policy.
- Extend CrateCheck with Kyverno validation checks: HelmRelease readiness, ClusterPolicy readiness, and allowed fixture namespace existence.
- Provide AI-runnable validation evidence covering controller health, policy readiness, and allowed fixture acceptance.
- Include a red test that intentionally breaks the Kyverno path and proves CrateCheck reports Kyverno checks as non-green, then restores green.

**Non-Goals:**

- Making Kyverno bootstrap-critical for the first GitOps handoff.
- Installing or validating production compliance profiles, multi-tenant governance, background scanning, or exception management.
- Defining a complete policy catalog, production security policy framework, or per-team policy promotion strategy.
- Introducing observability, cert-manager, Envoy Gateway, or wave-like promotion mechanics through this slice.
- Creating a separate Kyverno-specific status app — CrateCheck is the single validation surface.

## Decisions

### Kyverno is a GitOps-managed platform service

Kyverno is operator-owned policy enforcement infrastructure and is therefore platform services scope. It is installed after the GitOps handoff through the existing `kind-dev-misc-local` entrypoint. The reusable service definition lives at `platform-services/kyverno/base/`. The concrete cluster binding lives at `clusters/kind-dev-misc-local/platform-services/kyverno/`.

Two Flux `Kustomization` objects are introduced: one for the Kyverno controller (HelmRelease), and one for the smoke policy resources (ClusterPolicy and allowed fixture namespace). The smoke `Kustomization` depends on the controller `Kustomization`.

### Namespace follows the core service rule

Kyverno uses namespace `core-kyverno`. This follows the `core-<service-name>` rule.

### Single ClusterPolicy proves real admission control

The acceptance proof uses a single `require-ns-label` ClusterPolicy in Enforce mode that requires namespaces to carry the label `kubecrate.io/validated: "true"`. An allowed fixture namespace (`kyverno-smoke-allowed`) carries the label and proves the policy allows compliant resources through. The deny path is documented in the runbook as a manual test: attempting to create a namespace without the label is rejected by Kyverno, proving real admission control.

### CrateCheck is the validation surface

CrateCheck validates the Kyverno path through its standard check framework. Checks cover: HelmRelease controller health, ClusterPolicy readiness, and allowed fixture namespace existence. CrateCheck's ClusterRole is extended to read Kyverno resources (HelmRelease, ClusterPolicy).

The deny behavior is validated through the runbook as operational evidence rather than a CrateCheck check, because CrateCheck reads existing resources and cannot directly observe denied API calls. The ClusterPolicy Ready status proves the policy is active and enforcing.

### Acceptance evidence is operational and end-to-end

Static rendering and OpenSpec validation are required but not sufficient. Runtime success requires kind-first operational evidence:

1. intended Kubernetes context targets `kind-dev-misc-local`;
2. Kyverno namespace, controller resources, and CRDs exist;
3. Kyverno controller workload is ready;
4. ClusterPolicy `require-ns-label` is Ready and enforcing;
5. allowed fixture namespace `kyverno-smoke-allowed` exists;
6. a namespace without the required label is denied on creation (runbook evidence);
7. CrateCheck reports Kyverno checks as green;
8. a red test intentionally breaks the Kyverno path (e.g., deletes the ClusterPolicy), verifies CrateCheck reports Kyverno checks as non-green, then restores green.

## Risks / Trade-offs

- [Risk] CrateCheck cannot directly observe denied API calls → Mitigation: validate ClusterPolicy Ready status (proves enforcement is active) and document the deny test in the runbook as manual evidence.
- [Risk] Namespace-labeling policy is minimal and not production-grade → Mitigation: explicitly scope this as kind-first smoke only; production policy catalogs are deferred.
- [Risk] Kyverno install may become tangled with bootstrap installation → Mitigation: keep Kyverno reconciled through GitOps-managed operation only.
