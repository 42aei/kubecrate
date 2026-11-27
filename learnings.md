# Learnings

Format: the workflow skill's section Learnings (https://github.com/anovio/ai-config/blob/main/claude/skills/workflow/SKILL.md#learnings).

### After a cert-manager rollout, read the controller log from T + 2 minutes, because the first seconds after a restart carry a known error line that is no failure
- Why: on 2026-11-27, during the five-step cert-manager upgrade v1.16.3 → v1.21.3 on tenant-02, the new controller container logged `re-queuing item due to error processing" err="ACME client for issuer not initialised/available"` within 20 seconds of its start (T) in some steps; the ClusterIssuer was Ready and no Certificate changed. In the same minutes Kustomizations that depend on cert-manager showed not Ready and recovered on their own retry.
- Evidence: https://github.com/42aei/kubecrate-tenant-02/issues/54#issuecomment-7215443150
- Applies when: a Lead checks a cert-manager chart change after it reaches a consumer cluster. Take T from the controller container's `startedAt`, read `kubectl logs deploy/cert-manager --since=15m` at T + 17 for error lines (`"level":"error"` or ` E<mmdd> `), name the start-up lines of `--since=20m` apart, and read `kubectl get kustomizations -A` at T + 17, not right after the rollout.
- Added: 2026-11-27
- Revalidate by: 2027-02-25
