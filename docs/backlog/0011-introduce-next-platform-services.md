---
task_id: "0011"
title: "Introduce next platform services after first slice"
status: "proposed"
depends_on: ["0008"]
---

## Goal

Introduce additional platform services (ingress, certificate management, observability, policy) after the first installable slice establishes the bootstrap-to-GitOps baseline. Each service is introduced only when there is a clear operational reason, following the project posture of minimal over comprehensive.

## Notes

- Additional platform services identified and deferred by the define-gitops-component-management change: ingress controller, cert-manager, observability stack, policy engine.
- These are platform services under the two-axis model and should be GitOps-managed management units.
- This item is intentionally underspecified. Each platform service should be evaluated independently before becoming an OpenSpec proposal. Do not bundle all four into a single implementation change.
- The forcing function for each service should come from an operator-visible need (e.g., "ingress is needed to reach application services from outside the kind cluster").
- The kind-first local path should remain the reference environment for introducing each service.
- This backlog item may be split into individual items (0011a, 0011b, ...) or separate follow-up items when a specific service is ready for OpenSpec evaluation.
