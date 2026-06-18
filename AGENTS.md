# AGENTS

This repository is in an early architecture-led phase. Implementation files are added only when a proposal-approved OpenSpec change explicitly authorizes them.

Use the project language consistently. Keep changes small, reviewable, and aligned with the project model.

## Repository working principles

- Keep the project minimal over comprehensive.
- Prefer opinionated choices over early configurability.
- Prefer open source components and open operating models.
- Treat the target experience as point at a cluster and install.
- Preserve the long-term goal of cluster-provider agnostic operation.
- Preserve the implementation reality that the first local and reference path is kind-first.
- Keep the project production-inspired, not production-ready.
- Avoid adding complexity before there is a clear operational reason.

## Required project language

Use these terms consistently in docs, tasks, and proposals:

- platform services
- application services
- bootstrap installation
- GitOps-managed operation
- kind-first local path
- point at a cluster and install

Do not introduce competing terms unless there is a clear reason and the change is made explicitly across the repo.

## Architecture framing to preserve

Kubecrate uses a two-axis model. Preserve it in repository work:

- lifecycle phase: bootstrap installation or GitOps-managed operation
- workload category: platform services or application services

Bootstrap is a lifecycle or management mode, not a separate service category.

Do not collapse these axes together in docs or tasks.

## Backlog and planning rules

- Backlog items in `docs/backlog/` are lightweight raw captures.
- They are starting points, not full specifications.
- Before expanding a backlog item into OpenSpec, first evaluate whether the idea is large, concrete, and ready enough to justify a scoped change. Small ideas, loose thoughts, and undersized follow-ups should stay as discussion or lightweight backlog notes until that threshold is met.
- A backlog item marked `proposed` is only a candidate for evaluation, not permission to create an OpenSpec change. When asked what is next from the backlog, first return a readiness verdict: `ready for OpenSpec`, `not ready`, or `unclear`, with the recommended next action. Do not return `ready for OpenSpec` unless the item already has enough concrete scope and acceptance criteria to justify a change; otherwise return `unclear` and ask what decision or outcome should be clarified next.
- Do not over-template backlog entries.
- AI agents must keep backlog item frontmatter status current whenever they create, expand, start, complete, or obsolete backlog work. Do not expect the user to handle routine status hygiene manually.

## Slicing expectations

- Prefer vertical slices.
- Each OpenSpec change should produce a reviewable increment.
- Avoid horizontal layer-only slices unless there is a clear justification.
- Tie each slice to a user-visible or operator-visible outcome where possible.

## Repository placement rules

- Docs and planning artifacts live under `docs/` until an installable slice requires runtime files.
- Do not add empty technical skeleton directories.
- Do not create top-level lifecycle or workload folders until a proposal needs concrete files.
- Future runtime layout must preserve both axes:
  - lifecycle phase: bootstrap installation or GitOps-managed operation
  - workload category: platform services or application services
- Environment-specific structure is deferred until a change needs more than the kind-first local path.

## Current phase guardrails

For this architecture and planning pass:

- focus on repository docs and backlog definition
- proposal-approved implementation for `openspec/changes/create-first-installable-slice/` may add runtime manifests, installation scripts, and supporting config only in the paths approved by that OpenSpec change
- outside that approved exception, do not add Kubernetes manifests, installation scripts, or runtime/config expansion
- do not add unrelated or empty technical skeleton directories beyond `docs/backlog`
- do not edit `.opencode` files in this pass
