## Context

The current branch already contains the application and platform-service manifests needed to validate ESO through CrateCheck. It also contains reusable scenario assertions for JSON/UI green, controlled red, restoration, and projected Secret content. The failure is the surrounding exact-tree transport: temporary Git refs, generated per-run deploy keys, GitHub inventory validation, ownership markers, and crash-recovery logic.

The direct path can use the existing PR branch `kubecrate/cratecheck-restack-eso` at an exact verified commit. Flux supports HTTPS GitRepository authentication with a Kubernetes Secret containing username/password. The runner can obtain a token at runtime from the active `faksibot` `gh` session, create that Secret only inside its disposable cluster, and redact command output.

## Goals / Non-Goals

**Goals:**

- One command creates, validates, and deletes a unique disposable kind cluster.
- Flux reconciles the exact verified PR #17 commit through its existing remote branch.
- ESO projects the exact expected value.
- CrateCheck API and structured UI show green, controlled ESO red, and restored green.
- No credential appears in files, arguments visible in logs, stdout/stderr, or retained evidence.
- The runner is understandable as a linear operator workflow.

**Non-Goals:**

- Temporary Git refs or QA branches.
- Creating, listing, validating, or deleting GitHub deploy keys.
- Crash-safe ownership protocols for remote GitHub resources.
- Generalized credential-inventory, multi-service scenario, or QA-platform abstractions.
- Hostile ambient-state handling beyond refusing shared clusters, wrong contexts, wrong PR heads, and missing prerequisites.
- Retaining or repairing `scripts/final-qa-exact-tree.sh`, deploy-key preflight, or their generalized lifecycle as part of this outcome.

## Decisions

### Use the existing PR branch at a verified exact commit

The runner accepts or discovers PR #17’s branch and expected commit. Before cluster creation it verifies the remote branch and PR head both equal the expected commit. Flux follows that existing branch. No temporary remote ref is created.

This is sufficiently exact for the requested workflow because the runner gates before mutation and records the reconciled GitRepository artifact revision. If the branch moves during the run, the observed revision mismatch fails the run.

### Use runtime-only HTTPS authentication

The runner obtains an access token from the active `faksibot` GitHub CLI session without printing it. It creates a standard Flux HTTPS authentication Secret inside the disposable cluster using stdin or a temporary private file removed immediately. The GitRepository URL uses HTTPS and references that Secret.

No deploy key is generated or registered. The workflow introduces no mutable GitHub resource, so no GitHub cleanup protocol is needed.

### Keep the runner linear

The implementation target is one shell runner plus focused tests. It may call existing narrow validation helpers for status JSON/UI and Secret restoration, but it must not introduce a generalized orchestration framework.

Complexity budget:

- one new primary runner;
- focused test additions;
- only small support edits required to render HTTPS source values or reuse scenario assertions;
- no new remote-resource lifecycle module, marker format, inventory parser, or credential abstraction.

Any implementation exceeding this shape must stop and justify why the direct sequence cannot work before adding code.

### Reuse repository-owned cluster and scenario behavior

The runner uses `kind/config.yaml`, the pinned Flux charts and repository manifests. It creates a unique cluster name, verifies `kind-<name>` before every mutation phase, and never falls back to `kind-dev-misc-local` or `kubecrate-fix-eso`.

After reconciliation it proves:

1. Flux source and Kustomizations are Ready at the expected revision.
2. ESO controller, SecretStore, and ExternalSecret are Ready.
3. The projected Secret strictly decodes to `kubecrate-eso-smoke-ok`.
4. CrateCheck API and structured UI show exact expected green checks.
5. Deleting the owned source Secret yields intended ESO red while unrelated checks remain green.
6. Restoring the fixture yields the expected Secret value and green API/UI again.

### Cleanup means deleting the owned cluster

The runner traps exit, interrupt, and termination and deletes only the unique cluster name it created. It verifies that name is absent from `kind get clusters`. There are no remote refs or deploy keys to clean up.

If cluster deletion fails, the run fails and reports the exact cluster name. It does not need remote-resource ownership evidence because no remote resource is created.

## Risks / Trade-offs

- [Risk] The PR branch moves between verification and reconciliation. → Mitigation: compare PR head, remote branch head, and Flux artifact revision to the expected commit; fail on mismatch.
- [Risk] Runtime token leaks through shell tracing or command arguments. → Mitigation: prohibit `set -x`, pass credentials through protected stdin/private temporary state, avoid echoing rendered Secret data, and test sentinel non-leakage.
- [Risk] Token lacks read access. → Mitigation: fail before or during Flux source readiness with a stable authentication diagnostic, then delete the cluster.
- [Risk] Cluster deletion fails. → Mitigation: report the unique cluster name plainly for direct operator cleanup; do not add a generalized recovery subsystem.

## Migration Plan

1. Start from PR #17’s current remote head `3cfb4e320eff8d2a738cb36fd2420862b1db45c3` in a clean worktree.
2. Implement and statically test the direct runner.
3. Independently review only the linear workflow, credential non-leakage, exact revision gate, assertions, and cluster cleanup.
4. Push the reviewed candidate to PR #17 using force-with-lease against the verified old head.
5. Run the direct E2E once, with one retry only for a demonstrated transient kind/registry/network failure.
6. Leave PR #17 open and unmerged with concise evidence.

## Open Questions

None. Christian explicitly requested the minimal direct workflow and rejected the generalized QA/deploy-key framework.
