# Documentation

This repository starts with docs before implementation.

That is intentional. The first goal is to make the project model, language, and direction clear before adding manifests, scripts, or component structure.

## Documents in this folder

- `architecture.md` explains the core model.
- `bootstrap-installation-contract.md` defines what `point at a cluster and install` means, including bootstrap installation boundaries, GitOps-managed operation handoff, and how platform services and application services fit after handoff.
- `kind-local-workflow.md` defines the local reference workflow for the kind-first local path.
- `roadmap.md` shows the near-term order of work.
- `backlog/` holds lightweight raw captures that can later become OpenSpec proposals.

## How to read the docs

If you are new to the project, start with:

1. the top-level `README.md`
2. `architecture.md`
3. `bootstrap-installation-contract.md`
4. `kind-local-workflow.md`
5. `roadmap.md`
6. the backlog items for near-term slices

## Current boundaries

This docs set is for the first Kubecrate architecture and planning pass.

It defines intent and direction. It is not implementation-ready, and it does not yet define final manifests, component wiring, or installation mechanics.
