## Why

Kubecrate needs a retained kind-first demo that operators can start, inspect, recover, and stop through one documented interface. Current QA may use authenticated access to the exact PR revision; anonymous use remains the direction for future public sources.

## What Changes

- Add check, up, status, evidence, restart, recreate, and down operations.
- Verify a clean checkout and exact remote revision before cluster creation.
- Reconcile the current platform services, application services, and smoke consumers into a retained kind cluster.
- Add bounded readiness, exact-green status checks, trusted HTTP/HTTPS proof, sanitized evidence, and scoped cleanup.
- Add thin Make targets, a short runbook, and entrypoint-level behavioral tests.

## Capabilities

### New Capabilities
- `retained-local-demo`: Retained and inspectable kind-first local demo lifecycle, designed to support anonymously readable public sources.

### Modified Capabilities
- None.

## Impact

Changes are limited to the local workflow, its tests and Make targets, ignored `.tmp` state, the runbook, the Flux source renderer's anonymous mode, and this OpenSpec change. The destructive QA runner remains separate. No release, production ingress, shared-cluster, or private-consumer contract changes.
