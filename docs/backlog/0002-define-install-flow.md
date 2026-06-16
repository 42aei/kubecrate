---
task_id: "0002"
title: "Define install flow"
status: "proposed"
depends_on: ["0001"]
---

## Goal

Describe what point at a cluster and install should mean for Kubecrate from the operator point of view.

## Notes

Identify the expected inputs, the bootstrap installation boundary, and the conditions that mark the handoff into GitOps-managed operation.

Keep it implementation-facing, but do not tie it to a specific script shape yet.

This work is now expanded in OpenSpec change `define-install-flow` under `openspec/changes/define-install-flow/`. The change defines what `point at a cluster and install` means, including the bootstrap installation boundaries, GitOps-managed operation handoff condition, conceptual GitOps source structure roles for platform services and application services, and an illustrative non-runnable flow diagram. The kind-first local path is the first reference path, and Helm is noted as a preferred bootstrap packaging candidate with final validation deferred to a later proposal.
