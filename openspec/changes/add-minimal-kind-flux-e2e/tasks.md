## 1. Establish the Minimal Candidate

- [ ] 1.1 Verify clean PR #17 head `3cfb4e320eff8d2a738cb36fd2420862b1db45c3`, active `faksibot`, required tools, and repository-owned kind/Flux manifests.
- [ ] 1.2 Identify narrow reusable ESO/CrateCheck assertions and explicitly exclude temporary-ref, deploy-key, inventory, and marker lifecycle code.

## 2. Implement the Direct Runner

- [ ] 2.1 Add one linear runner that creates a unique disposable kind cluster and traps cleanup.
- [ ] 2.2 Verify PR head and remote branch head, configure Flux HTTPS source for that existing branch, and inject the runtime-only credential into the disposable cluster without logging or retaining it.
- [ ] 2.3 Install pinned Flux components, apply the repository entrypoint, wait for readiness, and verify the reconciled artifact revision.
- [ ] 2.4 Verify ESO readiness and exact projected Secret value.
- [ ] 2.5 Reuse or minimally adapt focused CrateCheck API/UI baseline, controlled-red, restoration, and projected-value assertions.
- [ ] 2.6 Delete the disposable cluster on every exit and verify absence; report its name if deletion fails.

## 3. Focused Tests and Review

- [ ] 3.1 Add tests for exact revision mismatch, shared/wrong context refusal, credential sentinel non-leakage, readiness failure, assertion failure, interrupt cleanup, and cleanup failure.
- [ ] 3.2 Run shell syntax, Python tests, OpenSpec strict validation, manifest/CrateCheck/Flux validations, and `git diff --check`.
- [ ] 3.3 Run one independent comprehensive review restricted to the direct workflow, credential handling, exact revision, assertions, and cluster cleanup; reject generalized framework expansion.
- [ ] 3.4 Apply at most one bounded fix/re-review cycle for defects in this small direct workflow; otherwise stop for triage.

## 4. Live E2E and PR Delivery

- [ ] 4.1 Commit the reviewed candidate and advance PR #17 with force-with-lease only after verifying the expected old head.
- [ ] 4.2 Run the direct disposable-cluster E2E once; allow one unchanged rerun only for a demonstrated transient kind, registry, or network failure.
- [ ] 4.3 Verify exact Flux revision, ESO projected value, CrateCheck API/UI green-red-green, cluster deletion, clean worktree, and required GitHub checks.
- [ ] 4.4 Record concise evidence and leave PR #17 open and unmerged for Christian’s review.
