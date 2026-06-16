## 1. Bootstrap installation contract documentation

- [x] 1.1 Create `docs/bootstrap-installation-contract.md` defining the operator-facing meaning of `point at a cluster and install`.
- [x] 1.2 Document the bootstrap installation start boundary as an already reachable Kubernetes API with usable credentials.
- [x] 1.3 Document the bootstrap completion condition as a running GitOps controller bound to a Git source with an initial reconciliation structure.
- [x] 1.4 Document conceptual GitOps source structure roles for GitOps entrypoint, platform services, application services, and cluster or environment binding.
- [x] 1.5 Include an illustrative non-runnable flow diagram that shows bootstrap installation handing off to GitOps-managed operation.
- [x] 1.6 Reconcile lifecycle wording and the illustrative flow so bootstrap installation ends at GitOps controller plus Git source plus reconciliation structure, not at a `minimum platform services installed` stage or final platform service selection.

Acceptance checks:
- `docs/bootstrap-installation-contract.md` states that `point at a cluster and install` starts from a reachable Kubernetes API and usable credentials.
- `docs/bootstrap-installation-contract.md` states that bootstrap installation completes when a GitOps controller is running, bound to a Git source, and can reconcile an initial structure for platform services and application services.
- `docs/bootstrap-installation-contract.md` identifies GitOps entrypoint, platform services, application services, and cluster or environment binding as structure roles without fixing final repository paths.
- The illustrative flow is clearly labeled non-runnable and shows handoff into GitOps-managed operation.
- The lifecycle wording does not treat `minimum platform services installed` as the bootstrap completion boundary and does not require final platform service selection before handoff.

## 2. Compatibility and scope boundaries

- [x] 2.1 Document kind-first as the first local reference path without making kind the product interface.
- [x] 2.2 Document bootstrap packaging compatibility criteria and Helm as a preferred candidate, with final packaging validation deferred to a later proposal.
- [x] 2.3 Explicitly state non-goals: cluster creation, runnable manifests, install scripts, final repository paths, and final component selection.

Acceptance checks:
- The bootstrap installation contract document describes the kind-first local path as a reference path and keeps the contract cluster-provider agnostic.
- Helm is described only as a preferred candidate or compatibility criterion for bootstrap packaging, not as an implemented chart, a Helm-only interface, or a final packaging decision.
- The non-goals section explicitly excludes cluster creation, runnable manifests, install scripts, final repository paths, and final platform service selection.

## 3. Repository integration and validation

- [x] 3.1 Link `docs/bootstrap-installation-contract.md` from `docs/README.md` and the top-level `README.md`.
- [x] 3.2 Update `docs/backlog/0002-define-install-flow.md` to reflect that this OpenSpec change now captures the work.
- [x] 3.3 Verify the change preserves required project language and the two-axis architecture framing.
- [x] 3.4 Run `openspec validate define-install-flow --type change --strict --json --no-interactive` and `openspec status --change define-install-flow --json`.

Acceptance checks:
- `docs/README.md` and `README.md` both link to `docs/bootstrap-installation-contract.md`.
- `docs/backlog/0002-define-install-flow.md` points to this OpenSpec change as the expanded planning reference for the work.
- The updated planning artifacts preserve the required terms `platform services`, `application services`, `bootstrap installation`, `GitOps-managed operation`, `kind-first local path`, and `point at a cluster and install`.
- The planning artifacts preserve the two axes by describing lifecycle phase separately from workload category.
- `openspec validate define-install-flow --type change --strict --json --no-interactive` exits successfully with no validation errors.
- `openspec status --change define-install-flow --json` exits successfully and reports the change artifacts for `define-install-flow`.
