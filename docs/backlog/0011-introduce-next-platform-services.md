---
task_id: "0011"
title: "Define and sequence post-baseline platform services"
status: "done"
depends_on: ["0008"]
---

## Goal

Define and sequence the platform services that come after the first installable slice establishes the bootstrap-to-GitOps baseline. This item is the discussion and decision point for hashing out service candidates, their operator-visible outcomes, their dependencies, and the follow-up backlog items or OpenSpec changes they justify.

## Notes

- Additional platform services identified and deferred by earlier work include External-Secrets Operator or other secret projection, ingress controller, cert-manager, observability stack, and policy engine.
- These are platform services under the two-axis model and should be GitOps-managed management units unless a future proposal explicitly justifies a bootstrap installation exception.
- This item is intentionally an umbrella discussion item, not a single implementation change. It exists to decide the service sequence and split concrete follow-up backlog items.
- Each platform service should be evaluated independently before becoming an OpenSpec proposal. Do not bundle unrelated services into a single implementation change.
- The forcing function for each service should come from an operator-visible need, for example secret projection is needed before workloads can safely consume operator-supplied trust material, or ingress is needed before application services can be reached from outside the kind cluster.
- Each service-specific follow-up should identify an AI-runnable end-to-end validation path. Prefer a minimal application service fixture such as nginx or a small Go/Node app that consumes the platform service through its documented interface.
- The validation fixture should prove real consumption rather than installation only: loading a projected Secret, serving through ingress, using an issued certificate, emitting observable signals, or demonstrating expected policy behavior.
- The fixture remains an application service because it consumes platform services. It should be added only by a proposal-approved slice that needs concrete runtime files.
- The kind-first local path should remain the reference environment for introducing and validating each service.
- This backlog item should be split into individual follow-up items when a specific service has a clear outcome and validation path. Candidate splits include secret projection, ingress, certificate management, observability, and policy.
- Initial follow-up splits captured from this discussion:
  - 0014 creates the reusable application service validation status app.
  - 0015 introduces External-Secrets Operator secret projection and should consult historical branch `docs/0008-seed-secrets-layout`.
  - 0016 introduces Envoy Gateway ingress and the required kind local exposure plumbing.
  - 0017 introduces cert-manager certificate management, likely building on the ingress path.
  - 0018 introduces Kyverno policy guardrails.
- Observability remains intentionally less ready than the other splits. Prometheus, Loki, and Grafana are the familiar default direction, but they may be too resource-heavy for the kind-first local path. Do not create or approve an observability implementation slice until the minimal useful local signal path and resource posture are clearer.

0011 is complete as an umbrella backlog discussion item. The concrete follow-up work now lives in 0014, 0015, 0016, 0017, and 0018. Observability remains intentionally deferred until the minimal useful kind-first signal path and resource posture are clearer.
