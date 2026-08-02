# Documentation

The docs carry the project model, language, and contracts for the reusable distribution.

## Documents in this folder

- `architecture.md` explains the core model.
- `platform-and-application-service-model.md` defines the working model for platform services and application services, including ownership, scope boundaries, and practical classification rules.
- `consumer-repositories.md` defines the consumer-repository contract, bootstrap handoff, ownership boundaries, and exact Kubecrate release consumption.
- `bootstrap-installation-contract.md` defines what `point at a cluster and install` means, including bootstrap installation boundaries, GitOps-managed operation handoff, and how platform services and application services fit after handoff.
- `gitops-component-management.md` defines the management-unit contract, the minimal initial set of GitOps-managed platform services, the source-structure contract, and the packaging posture.
- `vanilla-composition.md` defines the reusable Vanilla composition and its source structure.
- `ai-repository-guide.md` maps source-of-truth documents and validation expectations for AI-assisted work.
- `roadmap.md` shows the project direction.

## How to read the docs

If you are new to the project, start with:

1. the top-level `README.md`
2. `architecture.md`
3. `platform-and-application-service-model.md`
4. `consumer-repositories.md`
5. `bootstrap-installation-contract.md`
6. `gitops-component-management.md`
7. `vanilla-composition.md`
8. `ai-repository-guide.md`
9. `roadmap.md`

## Boundaries

This docs set defines the architecture and contract boundary for Kubecrate. Read it alongside the reusable platform-service manifests and the Vanilla composition.
