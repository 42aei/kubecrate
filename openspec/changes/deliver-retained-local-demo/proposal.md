## Why

Kubecrate needs a retained kind-first demo that operators can start, inspect, recover, and stop through one documented interface. Current private-repository use must not depend on anonymous Git access; Flux should authenticate to its GitOps source through the existing SSH deploy-key flow. Anonymous use remains explicit future/public-source context.

## What Changes

- Add check, up, status, evidence, restart, recreate, and down operations.
- Verify a clean checkout and exact remote revision before cluster creation.
- Reconcile the current platform services, application services, and smoke consumers into a retained kind cluster.
- Add bounded readiness, exact-green status checks, trusted HTTP/HTTPS proof, sanitized evidence, and scoped cleanup.
- Add thin Make targets, a short runbook, and entrypoint-level behavioral tests.

## Capabilities

### New Capabilities
- `retained-local-demo`: Retained and inspectable kind-first local demo lifecycle, using generated Flux SSH deploy keys by default and explicit anonymous mode only for future public sources.

### Modified Capabilities
- None.

## Impact

Changes are limited to the local workflow, its tests and Make targets, ignored `.tmp` state, the runbook, the Flux source renderer's deploy-key/anonymous modes, and this OpenSpec change. The destructive QA runner remains separate. No release, production ingress, shared-cluster, or private-consumer contract changes.
