# Documentation

The docs carry the project model, language, and contracts for the reusable distribution.

## Documents in this folder

- `architecture.md` explains the core model.
- `platform-and-application-service-model.md` defines the working model for platform services and application services, including ownership, scope boundaries, and practical classification rules.
- `bootstrap-installation-contract.md` defines what `point at a cluster and install` means, including bootstrap installation boundaries, GitOps-managed operation handoff, and how platform services and application services fit after handoff.
- `gitops-component-management.md` defines the management-unit contract, the minimal initial set of GitOps-managed platform services, the source-structure contract, and the packaging posture.
- `ai-repository-guide.md` maps source-of-truth documents and validation expectations for AI-assisted work.
- `roadmap.md` shows the near-term order of work.

## How to read the docs

If you are new to the project, start with:

1. the top-level `README.md`
2. `architecture.md`
3. `platform-and-application-service-model.md`
4. `bootstrap-installation-contract.md`
5. `gitops-component-management.md`
6. `ai-repository-guide.md`
7. `roadmap.md`

## Current boundaries

This docs set still defines the architecture and contract boundary for Kubecrate.

Read it alongside the reusable platform-service and application-service manifests.
