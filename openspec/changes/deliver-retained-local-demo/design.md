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

By default the retained workflow uses normal operator Git credentials only for the preflight proof that the selected remote/ref advertises the exact checked-out commit. Those credentials are not copied into the cluster.

Flux authenticates to the GitOps source through the existing `flux2-sync` SSH deploy-key generation flow. Bootstrap renders the selected branch into the durable SSH source, waits for `Secret/flux-system-sync`, prints the generated public key from `identity.pub`, and then waits for GitOps readiness after the operator registers that public key as a deploy key with the Git provider. The generated private key remains in-cluster.

Setting `KUBECRATE_LOCAL_ANONYMOUS_SOURCE=1` explicitly opts into a future public-source path. In that mode preflight uses a scrubbed anonymous probe and Flux is rendered without a Git credential Secret. Anonymous source access is not the current private-repository default.

### Retained lifecycle

`scripts/local-demo.sh` owns lifecycle behavior. Make targets only invoke its subcommands. State and evidence live below ignored `.tmp/kubecrate-local/`. The default cluster is `kubecrate-local`; runtime overrides are recorded before mutation.

### Failure and cleanup

Up records the candidate, source, cluster, context, and phase before mutation. A failed up records the phase, captures bounded sanitized evidence, and leaves the cluster available for inspection. Down requires coherent workflow state, deletes only the recorded cluster, proves absence, then clears active state while retaining evidence.

### Readiness and evidence

Up and status use explicit context, bounded waits, exact Flux revision validation, child Kustomization checks, controller and workload readiness, native service checks, the exact-green CrateCheck contract, HTTP, and trusted HTTPS. Status is read-only. Evidence writes a stable JSON summary plus bounded sanitized command output.

## Risks / Trade-offs

- The retained workflow requires the operator to register the generated deploy key before Flux can reconcile private GitOps sources. This matches the existing Flux deploy-key contract and avoids copying PAT/basic-auth material into the cluster.
- Fixed host ports `10080` and `10443` allow one retained demo at a time.
- Retaining failures consumes local resources until explicit down or recreate.
