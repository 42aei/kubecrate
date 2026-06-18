---
task_id: "0007"
title: "Choose minimal component set"
status: "done"
depends_on: ["0005", "0006"]
---

## Goal

Choose the smallest useful set of platform services needed for the first installable Kubecrate baseline.

## Notes

Reflect the project posture of minimal over comprehensive.

Every component should have a clear reason to exist in the first slice, especially if it affects bootstrap installation complexity.

Work completed in `openspec/changes/define-gitops-component-management/` (combined with 0010).
