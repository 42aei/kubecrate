---
task_id: "0004"
title: "Define repository layout"
status: "done"
depends_on: ["0001"]
---

## Goal

Define repository placement rules that support small vertical slices without adding runtime structure before an installable slice needs it.

## Notes

Docs and planning artifacts live under `docs/` until an installable slice requires runtime files.

Do not add empty technical skeleton directories.

Do not create top-level lifecycle or workload folders until a proposal needs concrete files.

Future runtime layout must preserve both axes: lifecycle phase (`bootstrap installation` or `GitOps-managed operation`) and workload category (`platform services` or `application services`).

Environment-specific structure is deferred until a change needs more than the kind-first local path.
