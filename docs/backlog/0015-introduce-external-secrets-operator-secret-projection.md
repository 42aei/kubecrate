---
task_id: "0015"
title: "Introduce External-Secrets Operator secret projection"
status: "started"
depends_on: ["0011", "0014"]
---

## Goal

Introduce External-Secrets Operator as the post-baseline secret projection platform service for the kind-first local path, with an end-to-end proof that the validation application service loads a projected Secret rather than reading broad bootstrap input material directly.

## Notes

- Do not implement this from the backlog item alone. Expand it into OpenSpec before adding runtime files.
- Earlier ESO and Seed Secrets work exists on branch `docs/0008-seed-secrets-layout` and remote branch `origin/docs/0008-seed-secrets-layout`. Use that branch as historical context, not as automatically accepted current design.
- That branch explored Seed Secrets, bootstrap-critical ESO, `seed-secrets`, and the ESO Kubernetes provider path. The current main branch pivoted the first installable slice away from ESO, so this task should re-evaluate what still applies after the Flux SSH deploy-key baseline.
- The core outcome is secret projection for consumers: operator-supplied or locally seeded trust material is narrowed into service-specific Secrets in the namespaces that need them.
- The validation app from 0014 should consume a projected Secret and report a green secret-loading check in both the status UI and status JSON.
- The check should explain what is being validated and help distinguish likely failure areas: ESO controller health, SecretStore or ClusterSecretStore readiness, ExternalSecret status, target Secret creation, application environment or volume wiring, and application read behavior.
- The kind-first local path should use the ESO Kubernetes provider or an equivalent local provider that proves projection from operator-supplied/local Kubernetes Secret material. The Fake provider may be useful for smoke/demo behavior, but it must not be the only proof if it does not validate the real local trust-material flow.
- ESO remains a platform service under the two-axis model. If the OpenSpec proposal chooses any bootstrap installation behavior, it must explain why that lifecycle handling is required and how handoff into GitOps-managed operation is preserved.
- Use `core-external-secrets-operator` as the dedicated namespace if ESO needs one, preserving the `core-<service-name>` rule.

## OpenSpec

Active OpenSpec change: `openspec/changes/introduce-external-secrets-operator-smoke/`.

This change scopes the ESO work as a kind-first, GitOps-managed platform services smoke slice that proves projected Secret consumption through the kubecrate validation status application service.
