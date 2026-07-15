## Why

Kubecrate needs one repeatable command that proves the real kind-first operator journey: create a disposable kind cluster, bootstrap Flux from the PR branch, observe ESO and CrateCheck behavior, and delete the cluster. The existing exact-tree QA path instead grew into a GitHub ref/deploy-key transaction framework whose failures prevent the cluster scenario from running.

## What Changes

- Add one small direct E2E runner for disposable kind + Flux + ESO + CrateCheck.
- Use PR #17’s existing remote branch and a runtime-only HTTPS GitHub credential from the active `faksibot` session.
- Inject the credential only into the disposable cluster’s Flux Secret; never print it or commit it.
- Reuse existing repository manifests and focused ESO/CrateCheck assertions.
- Prove healthy projection, controlled failure, restoration, and cluster deletion.
- Delete or bypass the exact-tree path’s temporary Git ref, per-run deploy-key, inventory, and recovery-marker machinery for this workflow.

## Capabilities

### New Capabilities
- `minimal-kind-flux-e2e`: A direct disposable-cluster command that validates Flux bootstrap and ESO consumption from an existing exact PR branch.

### Modified Capabilities

None.

## Impact

- Expected primary artifacts: one runner under `scripts/` and focused tests under `tests/`.
- May make small changes to the existing Flux source renderer or scenario helpers only where required for HTTPS runtime credentials and direct assertions.
- Does not merge PR #17 or modify `main`.
- Supersedes the remaining execution scope of `stabilize-exact-tree-eso-delivery` and Kanban card `t_ec221ec4`.
