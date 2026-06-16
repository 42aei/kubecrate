# Documentation

This repository starts with docs before implementation.

That is intentional. The first goal is to make the project model, language, and direction clear before adding manifests, scripts, or component structure.

## Documents in this folder

- `architecture.md` explains the core model.
- `install-flow.md` defines what `point at a cluster and install` means, including the bootstrap installation contract, GitOps-managed operation handoff, kind-first local path, and how platform services and application services fit after handoff.
- `roadmap.md` shows the near-term order of work.
- `backlog/` holds lightweight raw captures that can later become OpenSpec proposals.

## How to read the docs

If you are new to the project, start with:

1. the top-level `README.md`
2. `architecture.md`
3. `install-flow.md`
4. `roadmap.md`
5. the backlog items for near-term slices

## Current boundaries

This docs set is for the first Kubecrate bootstrap pass.

It defines intent and direction. It is not implementation-ready, and it does not yet define final manifests, component wiring, or installation mechanics.
