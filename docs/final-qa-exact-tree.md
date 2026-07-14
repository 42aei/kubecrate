# Exact-tree final QA

`scripts/final-qa-exact-tree.sh` is the authoritative executable runbook for the final ESO QA gate. The Makefile target is only a convenience wrapper.

## Safety and exact-tree model

The workflow takes an immutable local commit (`KUBECRATE_QA_CANDIDATE`, default `HEAD`) and directly pushes that commit to a unique `kubecrate-qa/*` ref. It then reads the remote ref back and requires both its SHA and tree to equal the candidate. It never commits a QA branch override into that tree.

Instead, the workflow generates an ignored `.tmp` values artifact and replaces only the rendered `ConfigMap/flux-sync-values` in the manifest stream applied to the disposable cluster. That runtime-only artifact points Flux to the unique QA branch whose remote SHA/tree were just proved exact. The committed `helm-values-sync.yaml` remains the reviewed normal source, and the workflow verifies the worktree/index tree did not change.

It refuses `main`, `master`, and `default` branch refs, refuses shared cluster names `kind-dev-misc-local` and `kubecrate-fix-eso`, and checks the exact expected kubecontext before every mutating cluster phase.

## Prerequisites

- clean worktree/index at the candidate;
- authenticated `gh` with repository deploy-key administration;
- permission to create/delete a unique remote QA branch;
- `git`, `gh`, `kind`, `kubectl`, `kustomize`, `helm`, `flux`, `python3`, `ssh-keygen`, `curl`, and Chromium/Chrome;
- Docker/kind capacity for a disposable cluster.

The run is intentionally live and mutating. Do not invoke it during coding or review. Final QA invokes:

```sh
KUBECRATE_QA_CANDIDATE=<reviewed-commit> \
KUBECRATE_QA_RUN_ID=<unique-safe-id> \
make final-qa-exact-tree
```

Optional variables are `KUBECRATE_GITHUB_REPO`, `KUBECRATE_QA_REMOTE`, `KUBECRATE_QA_BRANCH`, `KUBECRATE_QA_CLUSTER`, and `KUBECRATE_QA_EVIDENCE`. Branch and cluster overrides remain subject to guardrails.

## Executed proof

In fail-closed order the script:

1. proves a clean candidate and publishes its exact commit to a unique QA ref;
2. verifies remote SHA and tree before cluster creation;
3. runs the real disposable deploy-key create/read/delete preflight;
4. creates a unique kind cluster and applies the runtime-only Flux source artifact;
5. creates a unique read-only deploy key and verifies matching ID/title plus boolean `read_only=true`, `verified=true`, and `enabled=true`;
6. verifies Flux reconciliation on the expected context;
7. captures and validates `/status.json` and a headless-browser `/status` rendering showing baseline 7/7;
8. suspends the smoke Kustomization, deletes only the non-sensitive source Secret, and verifies an ESO check is non-green in JSON while capturing the UI;
9. restores the committed source Secret, resumes/reconciles Flux, and verifies restored JSON plus browser UI 7/7;
10. uses an exit trap on success, failure, interrupt, or termination to remove and verify absence of the exact captured deploy-key ID, exact QA branch, and exact cluster. Private/public key request artifacts are removed as well.

Evidence remains under the ignored `.tmp/final-qa-*` directory. A cleanup-verification failure overrides the original result and fails the run.
