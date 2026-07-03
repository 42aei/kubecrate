---
task_id: "0018"
title: "Introduce Kyverno policy guardrails"
status: "proposed"
depends_on: ["0011", "0014"]
---

## Goal

Introduce Kyverno as the policy platform service for the kind-first local path, with an end-to-end proof that expected allowed and denied application service behavior is observable and explainable.

## Notes

- Do not implement this from the backlog item alone. Expand it into OpenSpec before adding runtime files.
- Use Kyverno as the policy implementation unless the OpenSpec proposal discovers a blocking operational reason and records the decision explicitly.
- Kyverno is a platform service under the two-axis model and should be a GitOps-managed management unit unless a proposal explicitly justifies another lifecycle handling.
- The first policy slice should stay minimal and operator-visible. It should prove that the platform can enforce one or a few clear guardrails without becoming a broad compliance framework.
- The validation app from 0014, or a small companion application service manifest, should demonstrate both allowed and denied behavior.
- The policy check should report through the status UI and status JSON where practical, and should explain what is being validated and help distinguish likely failure areas: Kyverno controller health, policy installation, admission behavior, background scan behavior if used, target resource matching, exception handling, and the exact reason a workload was allowed or denied.
- Keep the first Kyverno slice focused on proving policy enforcement and explainability. Large policy catalogs, production compliance profiles, multi-tenant governance, and environment-specific policy promotion can remain later work.
- If Kyverno needs a dedicated namespace, use the `core-<service-name>` pattern with a clear service name chosen in the OpenSpec proposal.
