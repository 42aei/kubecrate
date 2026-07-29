# Documentation

This repository started with docs before implementation.

That remains intentional. The docs carry the project model, language, and contracts, and the repository now also includes the first installable slice for the kind-first local path.

## Documents in this folder

- `architecture.md` explains the core model.
- `platform-and-application-service-model.md` defines the working model for platform services and application services, including ownership, scope boundaries, and practical classification rules.
- `bootstrap-installation-contract.md` defines what `point at a cluster and install` means, including bootstrap installation boundaries, GitOps-managed operation handoff, and how platform services and application services fit after handoff.
- `gitops-component-management.md` defines the management-unit contract, the minimal initial set of GitOps-managed platform services, the source-structure contract, and the packaging posture.
- `vanilla-composition.md` defines the reusable public Vanilla composition, the kind-first local reference consumer, and migration notes from the old kind-local service entrypoint.
- `consumer-repositories.md` defines how private consumer repositories use Kubecrate through exact SemVer releases and the `42aei/kubecrate-consumer-template` starting point.
- `kind-local-workflow.md` defines the local reference workflow for the kind-first local path.
- `ai-repository-guide.md` maps source-of-truth documents, backlog-to-OpenSpec readiness, and validation expectations for AI-assisted work.
- `roadmap.md` shows the near-term order of work.
- `backlog/` holds lightweight raw captures that can later become OpenSpec proposals.

## How to read the docs

If you are new to the project, start with:

1. the top-level `README.md`
2. `architecture.md`
3. `platform-and-application-service-model.md`
4. `bootstrap-installation-contract.md`
5. `gitops-component-management.md`
6. `vanilla-composition.md`
7. `consumer-repositories.md`
8. `kind-local-workflow.md`
9. `ai-repository-guide.md`
10. `roadmap.md`
11. the backlog items for near-term slices

## Current boundaries

This docs set still defines the architecture and contract boundary for Kubecrate.

Read it alongside the first runtime files for the first installable slice on the kind-first local path and the reusable Vanilla composition consumed by that reference path.
