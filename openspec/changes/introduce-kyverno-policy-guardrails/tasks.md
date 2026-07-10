## 1. Repository authority and backlog hygiene

- [x] 1.1 Keep this change scoped to backlog 0018 and the Kyverno policy guardrails vertical slice.
- [x] 1.2 Update `docs/backlog/0018-introduce-kyverno-policy-guardrails.md` status to `started` and reference `openspec/changes/introduce-kyverno-policy-guardrails/` as the active OpenSpec change.
- [x] 1.3 Confirm this change preserves the required project language: platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install.
- [x] 1.4 Confirm Kyverno remains platform services scope and CrateCheck remains application services scope.

Acceptance checks:
- Backlog 0018 frontmatter reflects that OpenSpec work has started.
- This change uses `core-kyverno` for the dedicated Kyverno platform service namespace.
- Bootstrap installation is described as a lifecycle phase and not as a service category.

## 2. Minimum Kyverno platform service implementation

- [x] 2.1 Add the reusable Kyverno platform service base under `platform-services/kyverno/base/`.
- [x] 2.2 Add the `kind-dev-misc-local` cluster binding under `clusters/kind-dev-misc-local/platform-services/kyverno/`.
- [x] 2.3 Wire the Kyverno binding into the existing `clusters/kind-dev-misc-local/entrypoint` so Flux reconciles it through GitOps-managed operation.
- [x] 2.4 Create namespace `core-kyverno` for Kyverno and keep Flux's `flux-system` namespace exception limited to Flux.
- [x] 2.5 Keep Kyverno independent from bootstrap installation acceptance; do not install or own Kyverno from the bootstrap installation path.

Acceptance checks:
- Kyverno manifests render from the cluster entrypoint.
- Kyverno is installed and reconciled as platform services scope through GitOps-managed operation.
- No unrelated platform service or application service skeleton directories are added.

## 3. Minimal smoke policy and allowed fixture

- [x] 3.1 Define a `require-ns-label` ClusterPolicy that requires namespaces to carry `kubecrate.io/validated: "true"` in Enforce mode.
- [x] 3.2 Create an allowed fixture namespace `kyverno-smoke-allowed` that carries the required label.
- [x] 3.3 Avoid committing sensitive or production policy material; use non-sensitive fixture data for the smoke proof.

Acceptance checks:
- ClusterPolicy readiness can be checked by an AI-runnable command.
- Allowed fixture namespace exists and carries the required label.
- A namespace without the label is denied on creation (manual runbook evidence).

## 4. CrateCheck Kyverno integration

- [x] 4.1 Extend CrateCheck check config (ConfigMap) with Kyverno checks: HelmRelease readiness, ClusterPolicy readiness, allowed fixture namespace existence.
- [x] 4.2 Extend CrateCheck ClusterRole with read access to Kyverno-related resources (HelmRelease, ClusterPolicy).
- [x] 4.3 Extend CrateCheck validation tests with Kyverno check ID presence and CEL dot-notation contract assertions.
- [x] 4.4 Use CrateCheck as the single validation surface; do not create a Kyverno-specific status app.

Acceptance checks:
- CrateCheck check config includes Kyverno checks with valid severity, resource, and expression fields.
- CrateCheck ClusterRole grants read access to Kyverno resource types.
- Kyverno checks report green only when the full Kyverno path is healthy.
- validate-cratecheck.py passes all Kyverno contract checks.

## 5. AI-runnable validation and evidence

- [x] 5.1 OpenSpec change directory created with proposal, design, tasks, and spec.
- [ ] 5.2 Run `openspec validate introduce-kyverno-policy-guardrails --type change --strict --json --no-interactive` and resolve any errors.
- [ ] 5.3 Run static rendering for the current kind-first local path entrypoint.
- [ ] 5.4 Run kustomize build and kubeconform against the entrypoint.
- [ ] 5.5 Run validate-cratecheck.py to confirm all checks pass.
- [ ] 5.6 Validate Kyverno namespace, CRDs, controller resources, controller readiness, ClusterPolicy readiness, allowed fixture namespace existence, and CrateCheck Kyverno check output.
- [ ] 5.7 Check recent relevant events or logs for blocking Kyverno reconciliation errors.
- [ ] 5.8 Run a controlled red test by intentionally breaking the Kyverno path in a reversible way; verify CrateCheck reports Kyverno checks as non-green with useful diagnostics.
- [ ] 5.9 Restore the Kyverno path after the red test and verify CrateCheck returns Kyverno checks to green.

Acceptance checks:
- OpenSpec validation succeeds.
- Static rendering succeeds.
- Runtime validation proves real Kyverno admission control through CrateCheck.
- Red-test evidence proves CrateCheck detects Kyverno failure and recovers to green after restoration.
