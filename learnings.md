# Learnings

Format: the workflow skill's section Learnings (https://github.com/anovio/ai-config/blob/main/claude/skills/workflow/SKILL.md#learnings).

### After a cert-manager rollout, read the controller log from T + 2 minutes, because the first seconds after a restart carry a known error line that is no failure
- Why: on 2026-11-27, during the five-step cert-manager upgrade v1.16.3 → v1.21.3 on tenant-02, the new controller container logged `"re-queuing item due to error processing" err="ACME client for issuer not initialised/available"` within 30 seconds of its start (T) in steps 1, 3 and 4 (T + 21 s, T + 27 s, T + 19 s), while the ClusterIssuer stayed Ready and no Certificate was reissued; the line was first seen at the parent's start on 2026-11-13.
- Evidence: https://github.com/42aei/kubecrate-tenant-02/issues/54#issuecomment-7215443150
- Applies when: a Lead checks a cert-manager chart change after it reaches a consumer cluster. Take T from the controller container's `startedAt`, and at T + 17 minutes read `kubectl -n core-cert-manager logs deploy/cert-manager --since=15m` for error lines (`"level":"error"` or ` E<mmdd> `), naming the start-up lines of `--since=20m` apart.
- Added: 2026-11-27
- Revalidate by: 2027-02-25
