## 1. Tracer bullet: end-to-end bootstrap-to-GitOps vertical slice

The first implementation task is the narrow end-to-end tracer bullet. The following sub-tasks are minimum enabling steps required for the tracer bullet, not standalone horizontal phases. The tracer bullet deploys `tracer-echo`, a minimal GitOps-managed platform service whose sole purpose is to prove Flux reconciliation: install at version X, Git-managed bump to version Y, and evidence of the update.

### 1.1 Minimum kind plumbing (enabling)

- [ ] 1.1.1 Create kind cluster configuration for `kind-dev-misc-local` with sufficient resources for ESO, Flux, and `tracer-echo`.
- [ ] 1.1.2 Add prerequisite documentation or checks verifying kind, kubectl, and other tool versions.
- [ ] 1.1.3 Add Make targets or equivalent setup commands to create, teardown, and recreate the kind cluster from the config.
- [ ] 1.1.4 Add evidence commands that capture cluster state (e.g., `kubectl get` output) for validation.

### 1.2 Minimum runtime layout (enabling)

- [ ] 1.2.1 Create `platform-services/tracer-echo/base/` directory with concrete Kustomization and deployment manifest for `tracer-echo`.
- [ ] 1.2.2 Create `clusters/kind-dev-misc-local/` directory structure with `entrypoint/` and `platform-services/` subdirectories.
- [ ] 1.2.3 Create the cluster entrypoint Kustomization at `clusters/kind-dev-misc-local/entrypoint/kustomization.yaml` as the first GitOps reconciliation root.
- [ ] 1.2.4 Create cluster binding for `tracer-echo` at `clusters/kind-dev-misc-local/platform-services/tracer-echo.yaml` with version X (e.g., image tag `v0.1.0`).

### 1.3 Minimum bootstrap manifests (enabling)

- [ ] 1.3.1 Commit `seed-secrets.env.example` with placeholder values and usage documentation. Add `seed-secrets.env` to `.gitignore`. No real credential material is committed.
- [ ] 1.3.2 Create the bootstrap Kustomize overlay that references ESO installation manifests (upstream or vendored), materializes the `seed-secrets` Secret in the ESO namespace via `kubectl create secret generic seed-secrets -n eso --from-env-file=seed-secrets.env --dry-run=client -o yaml | kubectl apply -f -` (or equivalent documented wrapper), and references the cluster entrypoint Flux desired-state path.
- [ ] 1.3.3 Define the ESO ClusterSecretStore (or equivalent) using the Kubernetes provider to read the `seed-secrets` Secret.
- [ ] 1.3.4 Define ESO ExternalSecret resources that project Git credentials from `seed-secrets` for Flux consumption.
- [ ] 1.3.5 Create the Flux Git source: `GitRepository` resource pointing to this repository's HTTPS remote and the current implementation branch, referencing the ESO-projected credential Secret.
- [ ] 1.3.6 Create the Flux desired-state path under the cluster entrypoint: Flux installation manifests (controller, CRDs, RBAC) referenced from the entrypoint Kustomization, with Flux configured to reconcile the entrypoint path itself.

### 1.4 Bootstrap installation execution

- [ ] 1.4.1 Prepare the kind cluster using kind plumbing from 1.1.
- [ ] 1.4.2 Run `kubectl apply -k <bootstrap-overlay>` against the prepared cluster.
- [ ] 1.4.3 Verify ESO is running and the `seed-secrets` Secret exists in the ESO namespace.
- [ ] 1.4.4 Verify ESO ClusterSecretStore is connected and ExternalSecrets are projected (Git credentials synced).
- [ ] 1.4.5 Verify Flux controller is running, has reconciled its initial state, and the `GitRepository` is Ready using the HTTPS remote and projected credentials.

Acceptance: ESO status shows Healthy. `kubectl get secret seed-secrets -n eso` exists. ESO ExternalSecrets show SecretSynced. `flux get all` shows Flux running with Ready GitRepository and the first reconciliation complete. Evidence commands capture the state.

### 1.5 Flux self-management and `tracer-echo` at version X

- [ ] 1.5.1 Confirm Flux is self-managing: verify Flux reconciles its own installation from the cluster entrypoint path.
- [ ] 1.5.2 Verify `tracer-echo` is deployed through Flux reconciliation at version X (image tag `v0.1.0` or equivalent tracked config value).
- [ ] 1.5.3 Capture baseline evidence: Flux Kustomization/HelmRelease status, `tracer-echo` version via `kubectl get deployment tracer-echo -n <ns> -o jsonpath='{.spec.template.spec.containers[0].image}'`, pod status.

Acceptance: Flux Kustomization for itself shows Ready. Flux Kustomization/HelmRelease for `tracer-echo` shows Ready at version X. Evidence command confirms the image tag is `v0.1.0`. No bootstrap re-run needed for Flux or `tracer-echo` to be running.

### 1.6 GitOps-managed update: `tracer-echo` version X→Y

- [ ] 1.6.1 Change the Git-managed `tracer-echo` version from X to Y (e.g., bump image tag from `v0.1.0` to `v0.2.0` in `clusters/kind-dev-misc-local/platform-services/tracer-echo.yaml`).
- [ ] 1.6.2 Commit and push the change to the implementation branch. Wait for Flux reconciliation or trigger reconciliation.
- [ ] 1.6.3 Verify Flux detects the change, reconciles, and `tracer-echo` is upgraded to version Y.
- [ ] 1.6.4 Capture update evidence: before/after image tag via evidence command, Flux reconciliation logs or events, updated pod status.

Acceptance: `tracer-echo` is verified running at version Y (image tag `v0.2.0`) after Flux reconciliation. Evidence command output shows the version transition from X to Y triggered by the Git commit. Flux events or logs confirm the reconciliation.

## 2. Repository hygiene

- [ ] 2.1 Update `docs/backlog/0008-create-first-installable-slice.md` frontmatter status from `proposed` to `started` with a note referencing this OpenSpec change.
- [ ] 2.2 Update AGENTS.md phase guardrails to reflect that implementation has begun and the prior non-runnable/planning-pass guardrails no longer apply to this change's scope.
- [ ] 2.3 Verify runtime files are added only in proposal-approved paths (`platform-services/tracer-echo/`, `clusters/kind-dev-misc-local/`, bootstrap overlay directory, kind plumbing directory) and no unrelated manifests, scripts, or skeleton directories are introduced.
- [ ] 2.4 Run `openspec status --change "create-first-installable-slice"` and confirm all apply-required artifacts are present.
