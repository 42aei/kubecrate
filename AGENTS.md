# AGENTS

This repository is in an early docs-first bootstrap phase.

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
- OpenSpec proposals expand them later when a task is ready.
- Do not over-template backlog entries.
- AI agents must keep backlog item frontmatter status current whenever they create, expand, start, complete, or obsolete backlog work. Do not expect the user to handle routine status hygiene manually.

## Slicing expectations

- Prefer vertical slices.
- Each OpenSpec change should produce a reviewable increment.
- Avoid horizontal layer-only slices unless there is a clear justification.
- Tie each slice to a user-visible or operator-visible outcome where possible.

## Current phase guardrails

For this bootstrap pass:

- focus on repository docs and backlog definition
- do not add Kubernetes manifests
- do not add installation scripts
- do not add technical skeleton directories beyond `docs/backlog`
- do not edit `.opencode` files in this pass
