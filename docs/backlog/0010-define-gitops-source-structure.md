---
task_id: "0010"
title: "Define GitOps source structure"
status: "proposed"
depends_on: ["0002", "0003"]
---

## Goal

Define the GitOps source structure and repository boundary for Kubecrate, including whether this repo is a one-stop shop or whether template or example repositories should hold platform services and application services definitions.

## Notes

Keep the conceptual roles from the bootstrap installation contract.

Preserve platform services and application services, GitOps-managed operation, and the two-axis model.

Decide the repository boundary before the first installable slice if that decision becomes necessary.
