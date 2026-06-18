---
task_id: "0013"
title: "AI-enable repository structure and conventions"
status: "proposed"
depends_on: []
---

## Goal

Make the repository AI-friendly so that AI assistants produce reliable, low-hallucination outputs when working with Kubecrate. Build on AGENTS.md as the existing foundation and extend AI-facing structure to documentation, examples, and conventions.

## Notes

- AGENTS.md is the existing AI-facing foundation (project language, architecture framing, slicing expectations, guardrails). This item evaluates what additional structure helps AI assistants stay grounded without requiring OpenSpec changes to other backlog items.
- Focus on durable improvements that reduce ambiguity and hallucination risk: clear source-of-truth references, consistent markdown and frontmatter patterns, explicit consumer/dependency naming in docs and eventual code comments, and validation commands that AI agents can invoke.
- Targets are AGENTS.md refinements, doc conventions, README patterns, and explicit examples. Once runtime files exist, code/config examples should include concrete filenames, provider names, and expected output formats.
- Do not treat this as permission to edit `.opencode` files, skills, or agent configurations. If opencode configuration changes are needed later, they require an explicit scoped change with its own OpenSpec proposal.
- AI-friendliness should not introduce redundant documentation that duplicates the source of truth or adds maintenance burden.
- Preserve the two-axis model (lifecycle phase: bootstrap installation / GitOps-managed operation; workload category: platform services / application services) and required project language in any AI-facing additions.
- This item is lightweight and scoped to repository structure and conventions. It does not prescribe specific agent workflows, toolchains, or MCP configurations.
