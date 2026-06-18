## 1. Tracer bullet: end-to-end bootstrap-to-GitOps vertical slice

The first implementation task is the narrow end-to-end tracer bullet. The following sub-tasks are minimum enabling steps required for the tracer bullet, not standalone horizontal phases. The tracer bullet deploys `kubecrate-reconciliation-marker`, a Flux-managed validation marker/config proof whose sole purpose is to prove Flux reconciliation: install at version X, Git-managed bump to version Y, and evidence of the update.

### 1.1 Repository authority alignment (enabling)

- [x] 1.1.1 Update `AGENTS.md` current phase guardrails so proposal-approved implementation for `openspec/changes/create-first-installable-slice/` may add runtime manifests, installation scripts, and supporting config only in the paths approved by that OpenSpec change, while minimality, the two-axis model, the kind-first local path, no unrelated skeleton directories, and no `.opencode` edits remain in force.

### 1.2 Minimum kind plumbing (enabling)

- [x] 1.2.1 Create kind cluster configuration for `kind-dev-misc-local` with sufficient resources for ESO, Flux, and the reconciliation marker path.
- [x] 1.2.2 Add prerequisite documentation or checks verifying kind, kubectl, and other tool versions.
- [x] 1.2.3 Add Make targets or equivalent setup commands to create, teardown, and recreate the kind cluster from the config.
- [x] 1.2.4 Add evidence commands that capture cluster state (e.g. `kubectl get` output) for validation.

### 1.3 Minimum runtime layout (enabling)

- [x] 1.3.1 Create `clusters/kind-dev-misc-local/entrypoint/` as the first GitOps reconciliation root without introducing empty `platform-services/` or `application-services/` skeleton directories.
- [x] 1.3.2 Create the cluster entrypoint Kustomization at `clusters/kind-dev-misc-local/entrypoint/kustomization.yaml`.
- [x] 1.3.3 Create `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml` (or an equivalent concrete cluster-owned path) with version X (`v0.1.0`) stored in a ConfigMap or equivalent proof resource.
- [x] 1.3.4 Ensure the reconciliation marker is clearly documented and labeled as a validation marker/config proof, not a platform service or application service.

### 1.4 Minimum bootstrap manifests (enabling)

- [x] 1.4.1 Commit `.env.example` with the minimal Seed Secret contract and usage documentation. Verify `.env` remains in `.gitignore`. No real credential material is committed.
- [x] 1.4.2 Create the bootstrap Kustomize overlay that references ESO installation manifests (upstream or vendored), materializes the `seed-secrets` Secret in the ESO namespace via `kubectl create secret generic seed-secrets -n eso --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -` (or equivalent documented wrapper), and references the cluster entrypoint Flux desired-state path.
- [x] 1.4.3 Define the ESO ClusterSecretStore (or equivalent) using the Kubernetes provider to read the `seed-secrets` Secret.
- [x] 1.4.4 Define ESO ExternalSecret resources that project Git credentials from `seed-secrets` for Flux consumption using the `username` and `password` keys Flux HTTPS basic auth expects.
- [x] 1.4.5 Create the Flux Git source: `GitRepository` resource pointing to this repository's HTTPS remote and the current implementation branch, referencing the ESO-projected credential Secret backed by a fine-grained PAT that is read-capable now and ready for write-back before `ImageUpdateAutomation` is enabled.
- [x] 1.4.6 Create the Flux desired-state path under the cluster entrypoint: Flux installation manifests (controller, CRDs, RBAC) referenced from the entrypoint Kustomization, with Flux configured to reconcile the entrypoint path itself.

### 1.5 Bootstrap installation execution

- [x] 1.5.1 Prepare the kind cluster using kind plumbing from 1.2.
- [x] 1.5.2 Run `kubectl apply -k <bootstrap-overlay>` against the prepared cluster.
- [x] 1.5.3 Verify ESO is running and the `seed-secrets` Secret exists in the ESO namespace.
- [x] 1.5.4 Verify ESO ClusterSecretStore is connected and ExternalSecrets are projected (Git credentials synced).
- [x] 1.5.5 Verify Flux controller is running, has reconciled its initial state, and the `GitRepository` is Ready using the HTTPS remote and projected credentials.

Acceptance: ESO status shows Healthy. `kubectl get secret seed-secrets -n eso` exists. ESO ExternalSecrets show SecretSynced. `flux get all` shows Flux running with Ready GitRepository and the first reconciliation complete. Evidence commands capture the state.

### 1.6 Flux self-management and `kubecrate-reconciliation-marker` at version X

- [x] 1.6.1 Confirm Flux is self-managing: verify Flux reconciles its own installation from the cluster entrypoint path.
- [x] 1.6.2 Verify `kubecrate-reconciliation-marker` is reconciled through Flux at version X (`data.version: v0.1.0` or equivalent tracked config value).
- [x] 1.6.3 Capture baseline evidence: Flux Kustomization status, `kubecrate-reconciliation-marker` version via `kubectl get configmap kubecrate-reconciliation-marker -n <ns> -o jsonpath='{.data.version}'`, and resource presence or status.

Acceptance: Flux Kustomization for itself shows Ready. The reconciliation marker is present at version X. The evidence command confirms `v0.1.0`. No bootstrap re-run is needed for Flux or the reconciliation marker proof to be active.

### 1.7 GitOps-managed update: `kubecrate-reconciliation-marker` version X→Y

- [x] 1.7.1 Change the Git-managed `kubecrate-reconciliation-marker` version from X to Y (bump `data.version` from `v0.1.0` to `v0.2.0` in `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml` or the equivalent cluster-owned marker path).
- [ ] 1.7.2 Commit and push the change to the implementation branch. Wait for Flux reconciliation or trigger reconciliation.
- [ ] 1.7.3 Verify Flux detects the change, reconciles, and `kubecrate-reconciliation-marker` reports version Y.
- [ ] 1.7.4 Capture update evidence: before/after marker version via evidence command, Flux reconciliation logs or events, and updated ConfigMap content.

Acceptance: `kubecrate-reconciliation-marker` is verified at version Y (`v0.2.0`) after Flux reconciliation. Evidence command output shows the version transition from X to Y triggered by the Git commit. Flux events or logs confirm the reconciliation.

## 2. Repository hygiene

- [x] 2.1 Update `docs/backlog/0008-create-first-installable-slice.md` frontmatter status from `proposed` to `started` with a note referencing this OpenSpec change.
- [x] 2.2 Verify runtime files are added only in proposal-approved paths (`clusters/kind-dev-misc-local/`, bootstrap overlay directory, kind plumbing directory, and any Flux path explicitly referenced by the entrypoint) and no unrelated manifests, scripts, or empty workload-category skeleton directories are introduced.
- [x] 2.3 Run `openspec status --change "create-first-installable-slice"` and confirm all apply-required artifacts are present.
