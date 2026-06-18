---
task_id: "0012"
title: "Define wave-like promotion across environments"
status: "proposed"
depends_on: ["0008"]
---

## Goal

Define how platform services and application services are promoted across environments (e.g., local → staging → production) in a wave-like pattern after the first installable slice establishes a working kind-first baseline.

## Notes

- Per-environment targeting and configuration is already a firm capability established by the management-unit contract from the define-gitops-component-management change. This item addresses the promotion mechanism: environment sequencing, gating, promotion workflow, and any tooling or process needed to move a management unit from one environment to the next.
- The kind-first local path is the first "environment" in the promotion sequence. Additional environments (staging, production) are not expected to exist as kind clusters; they belong to a later phase when cluster-provider agnostic operation is exercised.
- Wave-like promotion means a change can be rolled out incrementally: a single management unit is updated in one environment, validated, then promoted to the next, without requiring all services in all environments to move together.
- This item defers concrete environment directory structure, promotion CLI/tooling, and gating mechanisms until a change needs more than the kind-first local path.
- Dependencies on 0008: the first installable slice must establish the source layout, management-unit contract, and validation evidence pattern that wave-like promotion builds upon.
