## Why

Backlog 0018 is ready for OpenSpec because it names a concrete platform service (Kyverno), a clear operator-visible outcome (policy enforcement with allow/deny proof), and an established validation consumer (CrateCheck). The kind-first local path already has Flux bootstrap installation and CrateCheck; this change brings Kyverno as the policy guardrails platform service to prove admission control and policy enforcement.

Kubecrate needs to prove that platform services can enforce policies on application service resources and that CrateCheck can validate the Kyverno path: controller health, policy readiness, and allowed fixture existence.

## What Changes

- Introduce Kyverno as a real platform service for the kind-first local path.
- Place the reusable Kyverno platform service base under `platform-services/kyverno/base/` and the `kind-dev-misc-local` binding under `clusters/kind-dev-misc-local/platform-services/kyverno/`.
- Use namespace `core-kyverno` for Kyverno because it is a dedicated platform service namespace and follows the `core-<service-name>` rule.
- Keep Kyverno under GitOps-managed operation. Bootstrap installation remains responsible only for reaching the GitOps handoff.
- Add a smoke policy: a `require-ns-label` ClusterPolicy that requires namespaces to carry the label `kubecrate.io/validated: "true"`, plus an allowed fixture namespace that satisfies the policy.
- Integrate with CrateCheck so that Kyverno checks (HelmRelease readiness, ClusterPolicy readiness, allowed fixture namespace existence) are validated through CrateCheck's standard check framework.
- Define AI-runnable acceptance evidence that proves installation, controller health, policy readiness, allowed fixture acceptance, and a red test where intentional breakage makes CrateCheck report Kyverno checks as non-green, then restored green.

## Capabilities

### New Capabilities

- `kyverno-policy-guardrails`: Defines the bounded Kyverno policy guardrails vertical slice for admission control on the kind-first local path.

### Modified Capabilities

- `cratecheck`: Extends CrateCheck check configuration, RBAC, and test validation to cover Kyverno platform service health and policy enforcement.

## Impact

- Adds one GitOps-managed platform service and one end-to-end platform service consumption proof through CrateCheck.
- Adds runtime manifests, configuration, and validation for Kyverno policy guardrails on `kind-dev-misc-local`.
- Does not introduce production compliance profiles, multi-tenant governance, background scanning, or environment-specific policy promotion.
- Does not make Kyverno part of bootstrap installation acceptance or change the Flux bootstrap contract.
- Preserves Kubecrate's two-axis model (lifecycle phase and workload category).
