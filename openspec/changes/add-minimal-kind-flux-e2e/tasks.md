## 1. Establish the Minimal Candidate

- [x] 1.1 Verify the clean current PR #17 head, active `faksibot`, required tools, and repository-owned kind/Flux manifests.
- [x] 1.2 Identify narrow reusable ESO/CrateCheck assertions and explicitly exclude temporary-ref, deploy-key, inventory, and marker lifecycle code.

## 2. Implement the Direct Runner

- [x] 2.1 Add one linear runner that creates a unique disposable kind cluster and traps cleanup.
- [x] 2.2 Verify PR head and remote branch head, configure Flux HTTPS source for that existing branch, and inject the runtime-only credential into the disposable cluster without logging or retaining it.
- [x] 2.3 Install pinned Flux components, apply the repository entrypoint, wait for readiness, and verify the reconciled artifact revision.
- [x] 2.4 Verify ESO readiness and exact projected Secret value.
- [x] 2.5 Validate the JSON-only CrateCheck baseline, controlled-red, restoration, and projected-value assertions.
- [x] 2.6 Delete the disposable cluster on every exit and verify absence; report its name if deletion fails.

The earlier exact-tree/deploy-key/ref lifecycle implementation was superseded by this direct workflow and has been removed together with its dedicated docs, tests, and Make targets.

## 3. Focused Tests and Review

- [x] 3.1 Add tests for exact revision mismatch, shared/wrong context refusal, credential sentinel non-leakage, readiness failure, assertion failure, interrupt cleanup, and cleanup failure.
- [x] 3.2 Run shell syntax, Python tests, OpenSpec strict validation, manifest/CrateCheck/Flux validations, and `git diff --check`.
- [x] 3.3 Run one independent comprehensive review restricted to the direct workflow, credential handling, exact revision, assertions, and cluster cleanup; reject generalized framework expansion.
- [x] 3.4 Apply at most one bounded fix/re-review cycle for defects in this small direct workflow; otherwise stop for triage.

## 4. Live E2E and PR Delivery

- [x] 4.1 Commit the reviewed candidate and advance PR #17 with force-with-lease only after verifying the expected old head.
- [x] 4.2 Run the direct disposable-cluster E2E once; allow one unchanged rerun only for a demonstrated transient kind, registry, or network failure.
- [x] 4.3 Verify exact Flux revision, ESO projected value, CrateCheck `/status.json` green-red-green, cluster deletion, clean worktree, and required GitHub checks.
- [x] 4.4 Record concise evidence and leave PR #17 open and unmerged for Christian’s review.
