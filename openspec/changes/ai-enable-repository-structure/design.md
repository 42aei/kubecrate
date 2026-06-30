## Context

Kubecrate now has a first installable slice on the kind-first local path, plus architecture, bootstrap installation, GitOps component management, and backlog guidance. That is enough structure for future agents to work effectively, but only if they can quickly identify which documents are authoritative for which decisions.

The risk is not a lack of documentation. The risk is that future AI assistants duplicate guidance, follow stale backlog notes instead of completed OpenSpec changes, or infer runtime structure from examples without checking the source-of-truth documents and current manifests.

This change should make existing guidance easier to apply mechanically while keeping the repository minimal.

## Goals / Non-Goals

**Goals:**

- Provide a concise source-of-truth map for future AI agents and contributors.
- Make the backlog-to-OpenSpec workflow mechanically checkable enough that agents do not turn every backlog note into a proposal.
- Document validation expectations in one discoverable place, including the difference between static validation and operational Kubernetes validation.
- Add concrete path-based examples where they reduce ambiguity about existing repository structure.
- Keep AGENTS.md as the concise guardrail document and avoid copying complete docs into it.

**Non-Goals:**

- Do not add or modify Kubernetes manifests, Helm values, Kustomize overlays, installation scripts, or runtime configuration.
- Do not edit `.opencode` files.
- Do not create Hermes profiles, kanban boards, skills, MCP configuration, or agent-specific tool automation.
- Do not introduce a new documentation framework or heavy templates.
- Do not redefine the two-axis architecture model or required project language.

## Decisions

### Add source-of-truth guidance instead of duplicating docs

The repository should make it easy to answer, "Which file owns this decision?" without copying whole sections between documents.

A small source-of-truth map is preferable to a large AI handbook. The map should point to documents such as `AGENTS.md`, `docs/architecture.md`, `docs/bootstrap-installation-contract.md`, `docs/gitops-component-management.md`, `docs/kind-local-workflow.md`, `docs/backlog/README.md`, and active OpenSpec changes.

Alternatives considered:

- Expand AGENTS.md into a full contributor handbook. Rejected because AGENTS.md should stay concise and portable across agents.
- Add no new guidance. Rejected because the first installable slice created enough runtime structure that future agents need a reliable navigation aid.

### Keep validation guidance layered

For docs-only changes, OpenSpec validation and vocabulary checks are enough. For runtime Kubernetes changes, static rendering is necessary but not sufficient: agents must also check cluster context, resources, controller/workload health, readiness or sync conditions, recent blocking events/logs, and the operator-visible outcome.

This change should make that distinction discoverable without creating Makefile-only orchestration semantics.

Alternatives considered:

- Put every validation command directly into AGENTS.md. Rejected because commands may vary by slice and should remain close to the relevant docs or OpenSpec change.
- Treat static rendering as enough for runtime changes. Rejected because the project already has Kubernetes validation guardrails that require operational evidence.

### Preserve lightweight backlog flow

Backlog items are raw captures. A `proposed` backlog status remains only a candidate for evaluation, not approval to create an OpenSpec change. The AI-facing guidance should reinforce the readiness verdict flow and show what agents should look for before proposing a change.

Alternatives considered:

- Add a strict backlog template with many required fields. Rejected because the repository intentionally keeps backlog entries lightweight.
- Let every proposed backlog item become OpenSpec. Rejected because AGENTS.md explicitly requires readiness evaluation first.

## Risks / Trade-offs

- [Risk] AI-facing docs become another stale source of truth. → Mitigation: keep them as a map to authoritative files, not a duplicate of all rules.
- [Risk] Added checklists create bureaucracy. → Mitigation: keep the slice small and limited to existing validation expectations and concrete paths.
- [Risk] Guidance becomes agent-tool-specific. → Mitigation: prohibit `.opencode`, profile, kanban, skills, MCP, or automation changes in this slice.
- [Risk] Examples accidentally imply future runtime structure. → Mitigation: use only existing concrete paths or explicitly mark examples as future-only when tied to approved rules.
