# AGENTS

This repository is an upstream distribution of reusable platform and application services. Keep changes small, reviewable, and aligned with the project model.

Use the project language consistently. Keep changes small, reviewable, and aligned with the project model.

## Repository working principles

- Keep the project minimal over comprehensive.
- Prefer opinionated choices over early configurability.
- Prefer open source components and open operating models.
- Treat the target experience as point at a cluster and install.
- Preserve the long-term goal of cluster-provider agnostic operation.
- Preserve cluster-provider agnostic operation and the point at a cluster and install experience.
- Keep the project production-inspired, not production-ready.
- Avoid adding complexity before there is a clear operational reason.

## Required project language

Use these terms consistently in docs, tasks, and proposals:

- platform services
- application services
- bootstrap installation
- GitOps-managed operation
- point at a cluster and install

Do not introduce competing terms unless there is a clear reason and the change is made explicitly across the repo.

## Architecture framing to preserve

Kubecrate uses a two-axis model. Preserve it in repository work:

- lifecycle phase: bootstrap installation or GitOps-managed operation
- workload category: platform services or application services

When a platform service needs a dedicated Kubernetes namespace, name it with the `core-<service-name>` pattern. The first concrete example is External-Secrets Operator in `core-external-secrets-operator`.

Bootstrap is a lifecycle or management mode, not a separate service category.

Do not collapse these axes together in docs or tasks.

## Slicing expectations

- Prefer vertical slices.
- Each scoped change should produce a reviewable increment.
- Avoid horizontal layer-only slices unless there is a clear justification.
- Tie each slice to a user-visible or operator-visible outcome where possible.
- Each platform service slice should include an AI-runnable validation path with an end-to-end proof. Prefer a small application service fixture, such as nginx or a minimal Go/Node app, that consumes the platform service through its documented interface and proves the operator-visible outcome.
- Platform service validation should prove real consumption, not only installation. Examples: a secret projection service is validated by an application service loading a projected Secret; ingress is validated by reaching an application service through the ingress path; certificate management is validated by a certificate issued and used for TLS; observability is validated by application or platform signals appearing in the expected collector or dashboard path.

## Hermes / Kanban delivery workflow

- Use one durable delivery card assigned to the default/orchestrator profile for non-trivial implementation. Do not create routine coder, code-review, and QA profile cards.
- Inside that card, run sequential isolated subagent passes: coder implementation, independent review, coder fix/re-review loops as needed, then final QA.
- Keep `ready_for_review`, `needs_changes`, and `ready_for_qa` as concise verified checkpoints on the same card. Complete it only after the required final QA pass; Kanban completion does not imply merge or release.
- Create a separate child only when a phase must survive independently, wait for human authorization or credentials, or run later in a separate environment or window. Historical profile chains may be recovered, but are not templates for new work.
- The orchestrator owns the exact worktree and candidate identity, gives every subagent self-contained scope, acceptance criteria, prior findings, safety constraints, and output contract, and independently verifies filesystem, git, test, and live-evidence claims.
- Reviewer subagents inspect independently and do not rewrite implementation. If review or QA finds implementation defects, route a fresh coder fix pass through independent review before QA.
- Subagents are not durable and inherit no parent context. After interruption, resume from the latest verified card checkpoint and rerun any unverified pass.
- Use a QA-only rerun only when implementation did not change. Do not merge to the default branch without explicit authorization for that exact merge.

## Repository placement rules

- Docs and planning artifacts live under `docs/` until an installable slice requires runtime files.
- Do not add empty technical skeleton directories.
- Do not create top-level lifecycle or workload folders until a proposal needs concrete files.
- Future runtime layout must preserve both axes:
  - lifecycle phase: bootstrap installation or GitOps-managed operation
  - workload category: platform services or application services
- Environment-specific structure is deferred until a scoped change requires it.
- When a real platform service is introduced, place its reusable base at `platform-services/<service>/base/` and keep cluster-specific bindings in the consuming distribution.
- Do not keep a real platform service only in a temporary cluster-local path unless a scoped change explicitly allows that exception and includes a removal plan.

## Bootstrap orchestration guardrails

- Makefile targets are shortcut and evidence wrappers only. They must not be the authoritative source for bootstrap installation orchestration semantics.
- Authoritative bootstrap installation dependency and ordering semantics must live in repository manifests and docs, not only in Makefile targets.
- Do not fix bootstrap installation by adding new Makefile-only orchestration.

## Kubernetes validation guardrails

- Static rendering, schema, or build validation is necessary but not sufficient whenever bootstrap installation or GitOps-managed operation applies or reconciles Kubernetes resources.
- Before claiming success, verify the intended cluster context, expected resources, controller and workload health, readiness, or sync conditions, recent events or logs for blocking errors, and the operator-visible outcome.
- If health is failing or unclear, do not claim success. Use `debug-kubernetes` for bounded diagnosis before proposing or applying fixes.
- Keep deeper checks symptom-driven. Authorization or RBAC checks such as `kubectl auth can-i` are examples to use when evidence points to that layer, not a mandatory per-ServiceAccount checklist.

## Current phase guardrails

For this upstream distribution:

- focus on repository docs and reusable distribution artifacts
- use `docs/ai-repository-guide.md` as the concise source-of-truth map and validation checklist for AI-assisted repository work
- do not add unrelated or empty technical skeleton directories
