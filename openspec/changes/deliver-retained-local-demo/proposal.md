## Why

Kubecrate has a complete kind-first stack and a destructive QA runner, but a public user cannot yet clone the repository, bring up the exact checked-out revision anonymously, inspect a retained demo, and tear it down through one documented interface.

## What Changes

- Add a retained local demo entrypoint with check, up, status, evidence, restart, recreate, and down operations.
- Derive an anonymous public Git source and exact ref from the checkout, with runtime-only overrides and pre-mutation exactness checks.
- Bootstrap Flux and reconcile the complete current platform services, application services, and smoke consumers into a named persistent kind cluster.
- Add bounded readiness, exact CrateCheck green validation, HTTP and trusted HTTPS proof, sanitized retained evidence, and scoped cleanup.
- Add Make wrappers, a prominent README-linked runbook, and behavioral tests that execute the shipped entrypoint with fake commands.

## Capabilities

### New Capabilities
- `retained-local-demo`: Anonymous, retained, inspectable kind-first local Kubecrate demo lifecycle.

### Modified Capabilities
- None.

## Impact

Changed areas are limited to a new local workflow script and tests, Make wrappers, ignored `.tmp` state, public documentation, the existing Flux source renderer's anonymous mode, and this OpenSpec change. The destructive QA runner remains separate. No release, private-consumer contract, production ingress, or shared-cluster behavior changes.
