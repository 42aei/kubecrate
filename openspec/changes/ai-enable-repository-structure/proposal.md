## Why

Kubecrate is now past the first installable slice and has enough repository structure that future AI-assisted work needs clearer source-of-truth guidance. AGENTS.md already defines the project language, two-axis model, slicing expectations, and guardrails, but future agents still need a small set of durable, repository-local aids that reduce rediscovery and hallucination risk.

This change turns backlog 0013 into a focused documentation and convention slice. It keeps the work limited to repository structure and handoff clarity: source-of-truth mapping, validation guidance, backlog/OpenSpec flow, and concrete examples that help agents conform to the existing model.

## What Changes

- Add or update AI-facing repository guidance that points agents to the authoritative documents for project language, architecture model, bootstrap installation, GitOps-managed operation, backlog, and OpenSpec work.
- Document a minimal source-of-truth map so future agents know where to look before changing runtime files, docs, backlog items, or OpenSpec artifacts.
- Add a small validation checklist that distinguishes static rendering/OpenSpec validation from operational Kubernetes validation for bootstrap installation and GitOps-managed operation.
- Clarify backlog-to-OpenSpec readiness flow using the existing readiness verdict language: `ready for OpenSpec`, `not ready`, and `unclear`.
- Keep AI-facing examples concrete and path-based without introducing new agent tools, .opencode changes, profile/kanban workflows, or external automation.

## Capabilities

### New Capabilities

- `ai-repository-enablement`: Defines repository-local guidance and conventions that make Kubecrate safer and easier for AI assistants to work on without rediscovering project structure or inventing unsupported implementation paths.

### Modified Capabilities

- None.

## Impact

- Updates documentation and backlog guidance only.
- May refine AGENTS.md or docs to point at the new AI-facing guidance, but must not duplicate the full source of truth in multiple places.
- Does not add Kubernetes manifests, installation scripts, runtime configuration, .opencode files, skills, agent profiles, kanban setup, or external automation.
- Preserves the required project language and the two-axis model: lifecycle phase (`bootstrap installation` or `GitOps-managed operation`) and workload category (`platform services` or `application services`).
