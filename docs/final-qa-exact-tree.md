# Exact-tree final QA

`scripts/final-qa-exact-tree.sh` is the authoritative executable runbook for the final ESO QA gate. The Makefile target is only a convenience wrapper.

## Safety and exact-tree model

The workflow takes an immutable local commit (`KUBECRATE_QA_CANDIDATE`, default `HEAD`). Before any remote or cluster operation it requires local `HEAD` to equal that commit, the index tree to equal its tree, and the tracked and untracked worktree to be empty. It atomically creates a unique `kubecrate-qa/*` ref with the GitHub refs API and accepts ownership only after a schema-valid create/readback proves the exact ref and SHA. A 422 race, malformed response, or unknown lookup fails closed. It never commits a QA branch override into that tree.

Instead, the workflow generates an ignored `.tmp` values artifact and replaces only the rendered `ConfigMap/flux-sync-values` in the manifest stream applied to the disposable cluster. That runtime-only artifact points Flux to the unique QA branch whose remote SHA/tree were just proved exact. The committed `helm-values-sync.yaml` remains the reviewed normal source, and the workflow verifies the worktree/index tree did not change.

It refuses `main`, `master`, and `default` branch refs, refuses shared cluster names `kind-dev-misc-local` and `kubecrate-fix-eso`, and checks the exact expected kubecontext before every mutating cluster phase.

## Prerequisites

- clean tracked worktree/index at the candidate with no non-ignored untracked files that could shadow run inputs;
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

1. proves the locally executed scripts/manifests are exactly the candidate commit and tree, with no tracked or untracked shadow files;
2. creates and verifies an exact GitHub QA ref atomically before cluster creation;
3. runs the real disposable deploy-key create/read/delete preflight;
4. creates a unique kind cluster, applies the runtime-only Flux source artifact, then boundedly waits for the generated sync credential `Secret/flux-system-sync` to contain a non-empty `identity.pub` without logging key material;
5. writes the generated public key only through a descriptor-confined `0700`/`0600` private path, durably records cleanup intent containing only the OpenSSH-style `SHA256:<base64-without-padding>` fingerprint of the decoded key blob, creates the unique read-only deploy key, and requires exact POST, GET, and complete paginated-list agreement on ID, title, normalized fingerprint, and strict enabled/read-only/verified metadata before removing private key artifacts;
6. explicitly requests the sync HelmRelease to reconcile, waits for it to become Ready only after deploy-key registration, then verifies Flux source and Kustomization reconciliation on the expected context;
7. requires the exact seven unique check IDs, strict summary counts, and structured browser check cards whose exact configured names and status attributes map back to those IDs (CrateCheck's current UI renders names rather than IDs);
8. suspends the smoke Kustomization, immediately records mutation state, deletes only the non-sensitive source Secret, and requires only `eso-externalsecret-ready` and/or `eso-projected-secret-exists` to be non-green while unrelated checks stay green;
9. resumes and reconciles on the explicit disposable context, proves the smoke Kustomization Ready, source Secret present, ExternalSecret Ready, and exact API/browser seven-green restoration;
10. uses an exit trap on success, failure, interrupt, or termination. If a red mutation occurred, verified restoration runs before teardown and any restore failure makes cleanup fail. The trap deletes the QA branch only with this run's create proof, only while it still targets the owned candidate SHA, and verifies absence; a moved ref is never deleted. It likewise removes and verifies absence of the exact deploy-key ID and exact cluster.

Evidence remains under the ignored `.tmp/final-qa-*` directory. A cleanup-verification failure overrides the original result and fails the run.

For local harness testing only, `KUBECRATE_QA_IDENTITY_GATE_ONLY=1` exits after the pre-mutation local identity gate. It performs no remote, key, kind, Flux, or Kubernetes operation.
