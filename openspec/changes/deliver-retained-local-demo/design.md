## Context

The existing GitOps entrypoint composes Flux, External Secrets Operator, Envoy Gateway, cert-manager, Kyverno, CrateCheck, and smoke consumers. The direct E2E runner uses authenticated temporary Git state and cleans up. The retained demo instead keeps a named cluster and evidence until explicit teardown.

Current QA may use authenticated access to the exact PR revision. Anonymous source access is a future public-use expectation, not a current QA blocker.

## Goals / Non-Goals

**Goals:**
- Provide one lifecycle script with thin Make wrappers.
- Check candidate identity before cluster creation.
- Retain a healthy or inspectable failed cluster with bounded sanitized evidence.
- Report the exact source revision and complete service status.
- Delete only workflow-owned state.

**Non-Goals:**
- Replace the destructive QA runner.
- Add a custom CLI, release flow, production hosting, or general QA framework.
- Mutate a shared cluster, default branch, or remote repository.

## Decisions

### Exact source binding

The workflow derives the selected URL from `origin`, normalizes supported GitHub SSH/HTTPS forms to HTTPS, and uses the current branch by default. Runtime overrides may select another URL or ref. Before kind runs, preflight requires a clean commit, one remotely advertised branch SHA, and an exact SHA match.

The retained workflow currently renders Flux without a Git credential Secret, so that source must be anonymously readable. This supports future public upstreams and forks. It is not required for current QA, which may validate the exact PR through the authenticated direct runner.

### Retained lifecycle

`scripts/local-demo.sh` owns lifecycle behavior. Make targets only invoke its subcommands. State and evidence live below ignored `.tmp/kubecrate-local/`. The default cluster is `kubecrate-local`; runtime overrides are recorded before mutation.

### Failure and cleanup

Up records the candidate, source, cluster, context, and phase before mutation. A failed up records the phase, captures bounded sanitized evidence, and leaves the cluster available for inspection. Down requires coherent workflow state, deletes only the recorded cluster, proves absence, then clears active state while retaining evidence.

### Readiness and evidence

Up and status use explicit context, bounded waits, exact Flux revision validation, child Kustomization checks, controller and workload readiness, native service checks, the exact-green CrateCheck contract, HTTP, and trusted HTTPS. Status is read-only. Evidence writes a stable JSON summary plus bounded sanitized command output.

## Risks / Trade-offs

- The retained source must currently be anonymously readable; current private-repository QA uses the authenticated exact-PR runner instead.
- Fixed host ports `10080` and `10443` allow one retained demo at a time.
- Retaining failures consumes local resources until explicit down or recreate.
