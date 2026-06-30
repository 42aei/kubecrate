## 1. Source-of-truth map

- [x] 1.1 Add a concise source-of-truth map for AI agents and contributors that points to the authoritative documents for project language, architecture model, bootstrap installation, GitOps-managed operation, kind-first local path, backlog, OpenSpec changes, and runtime layout.
- [x] 1.2 Link the source-of-truth map from `docs/README.md`.
- [x] 1.3 If AGENTS.md needs a pointer to the new map, add only a short reference and do not duplicate the map contents there.

Acceptance checks:
- The map identifies which file owns each major decision area.
- The map points to existing concrete runtime paths such as `clusters/kind-dev-misc-local/entrypoint/`, `clusters/kind-dev-misc-local/platform-services/flux/`, and `platform-services/flux/base/` without inventing new runtime paths.
- `docs/README.md` links to the map.
- AGENTS.md, if changed, remains concise and does not duplicate the full source-of-truth map.

## 2. Backlog and OpenSpec readiness guidance

- [x] 2.1 Document how agents should evaluate backlog items before creating OpenSpec changes, preserving the required readiness verdicts: `ready for OpenSpec`, `not ready`, and `unclear`.
- [x] 2.2 Add a lightweight example of a backlog item that should stay as discussion and one that is ready to become an OpenSpec proposal.
- [x] 2.3 Keep backlog entries lightweight; do not add a heavy required template.

Acceptance checks:
- The guidance states that `proposed` means candidate for evaluation, not permission to create OpenSpec.
- The guidance says to default to `unclear` when scope or acceptance criteria are missing.
- The examples preserve the project language and two-axis model.

## 3. Validation guidance for future agents

- [x] 3.1 Add a small validation checklist that distinguishes docs/planning validation, static manifest rendering, and operational Kubernetes validation.
- [x] 3.2 Include concrete commands already used in this repository where appropriate, such as OpenSpec validation and Kustomize rendering, without making Makefile targets the sole authoritative source of bootstrap installation orchestration semantics.
- [x] 3.3 Re-state that runtime Kubernetes changes require operational evidence before success is claimed.

Acceptance checks:
- The checklist includes OpenSpec validation for OpenSpec changes.
- The checklist includes static rendering for manifest changes, while explicitly saying static rendering is necessary but not sufficient for bootstrap installation or GitOps-managed operation.
- The checklist includes cluster context, expected resources, controller/workload health, readiness or sync conditions, recent events/logs for blocking errors, and operator-visible outcome as operational evidence categories.

## 4. Scope guardrails

- [x] 4.1 Verify this change does not add Kubernetes manifests, installation scripts, runtime configuration, `.opencode` files, Hermes profiles, kanban setup, skills, MCP configuration, or external automation.
- [x] 4.2 Verify required project vocabulary and the two-axis model are preserved across changed docs.

Acceptance checks:
- File changes are limited to documentation, backlog, and OpenSpec artifacts.
- No new runtime directories or empty technical skeleton directories are added.
- Required terms remain consistent: platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install.

## 5. Validation

- [x] 5.1 Run `openspec validate ai-enable-repository-structure --type change --strict --json --no-interactive` and resolve any errors.
- [x] 5.2 Run `openspec status --change ai-enable-repository-structure --json` and confirm all required artifacts are present.
- [x] 5.3 Run existing static validation relevant to the current runtime files to ensure the cleanup did not break manifest rendering.

Acceptance checks:
- `openspec validate` exits successfully with no validation errors.
- `openspec status` reports required artifacts for the change.
- Existing runtime rendering still succeeds.
