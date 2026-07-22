## Context

The current GitOps entrypoint already composes Flux, External Secrets Operator, Envoy Gateway, cert-manager, Kyverno, CrateCheck, and smoke consumers. The direct E2E runner proves destructive red scenarios with authenticated temporary Git state and always cleans up. A public demo needs the opposite lifecycle: anonymous source access, exact immutable commit proof, a stable named cluster, read-only inspection, retained failure evidence, and explicit teardown.

## Goals / Non-Goals

**Goals:**
- Provide one repository script with lifecycle subcommands and thin Make wrappers.
- Fail source and candidate identity checks before cluster creation.
- Retain a healthy cluster, or an inspectable failed cluster with bounded sanitized evidence.
- Report exact source revision and complete service-native and CrateCheck evidence.
- Scope cleanup to state owned by this workflow.

**Non-Goals:**
- Replace or generalize the destructive QA runner.
- Add authentication, GitHub CLI, credentials, release/versioning, a custom CLI, production hosting, or a general QA framework.
- Mutate a shared cluster, default branch, or remote repository.

## Decisions

### Anonymous exact source binding

The workflow derives the selected remote URL from the checkout's `origin` URL, normalizes supported public GitHub SSH/HTTPS forms to public HTTPS, and uses the current local branch as the default selected ref. Runtime overrides can select another public URL or ref. Preflight requires a clean tracked and untracked worktree, a full commit HEAD, anonymous `git ls-remote` access, and an exact selected-ref SHA match before kind is invoked. This deliberately refuses detached, local-only, dirty, or unpushed candidates because Flux could not reconcile their exact local contents.

### One retained workflow entrypoint

`scripts/local-demo.sh` owns lifecycle semantics. Make targets only invoke its subcommands. State and bounded evidence live below ignored `.tmp/kubecrate-local/`. The default cluster is `kubecrate-local`; overrides are runtime-only and recorded before mutation.

### Anonymous Flux rendering

The existing renderer gains an explicit anonymous mode that disables generated SSH credentials and removes `secretRef`. The authenticated direct QA runner keeps its existing explicit Secret behavior.

### Failure and cleanup ownership

Up records phase, candidate, source, ref, cluster, and context before mutation. An EXIT trap changes the state to failed and captures bounded diagnostics when up fails. It does not silently delete an inspectable cluster. Down requires coherent workflow state and an exact cluster/context match, refuses protected or ambiguous targets, deletes only the recorded cluster, proves absence, then removes active state while retaining evidence.

### Readiness and evidence

Up and status use explicit context, bounded waits, exact Flux artifact revision validation, all current child Kustomizations, controller/workload readiness, ESO projection, Envoy Gateway, cert-manager Certificate and trusted HTTPS, Kyverno policy, and the full exact-green CrateCheck JSON contract. Status is read-only. Evidence writes a concise summary plus bounded sanitized command output under a documented stable path.

## Risks / Trade-offs

- Public Git hosts other than GitHub are not inferred initially. Runtime URL/ref overrides remain available, but the selected source must be anonymously readable.
- Host ports 10080 and 10443 make one default retained cluster per machine the supported path.
- Retaining a failed cluster consumes local resources; explicit `local-down` and `local-recreate` provide recovery.
