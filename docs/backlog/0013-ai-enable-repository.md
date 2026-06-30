---
task_id: "0013"
title: "AI-enable repository structure and conventions"
status: "done"
depends_on: []
---

## Goal

Make the repository AI-friendly so that AI assistants produce reliable, low-hallucination outputs when working with Kubecrate. Build on AGENTS.md as the existing foundation and extend AI-facing structure to documentation, examples, and conventions.

## Notes

- AGENTS.md is the existing AI-facing foundation (project language, architecture framing, slicing expectations, guardrails). This item evaluates what additional structure helps AI assistants stay grounded without requiring OpenSpec changes to other backlog items.
- Focus on durable improvements that reduce ambiguity and hallucination risk: clear source-of-truth references, a source-of-truth map, naming and layout conventions, consistent markdown and frontmatter patterns, explicit consumer/dependency naming in docs and eventual code comments, validation commands that AI agents can invoke, and examples future agents can mechanically follow.
- Targets are AGENTS.md refinements, doc conventions, README patterns, review checklists, validation guidance, and explicit examples. Once runtime files exist, code/config examples should include concrete filenames, provider names, expected output formats, and file-placement expectations that help future work conform to the documented structure rather than merely describe it.
- Do not treat this as permission to edit `.opencode` files, skills, or agent configurations. If opencode configuration changes are needed later, they require an explicit scoped change with its own OpenSpec proposal.
- AI-friendliness should not introduce redundant documentation that duplicates the source of truth or adds maintenance burden. The goal is to make the documented structure enforceable in practice, not just easier to read.
- Preserve the two-axis model (lifecycle phase: bootstrap installation / GitOps-managed operation; workload category: platform services / application services) and required project language in any AI-facing additions.
- This item is lightweight and scoped to repository structure and conventions. It does not prescribe specific agent workflows, toolchains, or MCP configurations.

## OpenSpec

Active OpenSpec change: `openspec/changes/ai-enable-repository-structure/`.

This change should define the smallest reviewable AI-facing documentation and convention improvements before implementation. It should avoid introducing new agent tool configurations or workflow-specific automation.
