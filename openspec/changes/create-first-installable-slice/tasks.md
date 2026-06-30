## 1. Tracer bullet: end-to-end bootstrap-to-GitOps vertical slice

The first implementation task is the narrow end-to-end tracer bullet. The following sub-tasks are minimum enabling steps required for the tracer bullet, not standalone horizontal phases. The tracer bullet deploys `kubecrate-reconciliation-marker`, a Flux-managed validation marker/config proof whose sole purpose is to prove Flux reconciliation: install at version X, Git-managed bump to version Y, and evidence of the update.

### 1.1 Repository authority alignment (enabling)

- [x] 1.1.1 Keep this change scoped to the first installable tracer bullet only: runtime files authorized by this OpenSpec change may be added under existing AGENTS.md guardrails, while preserving repository principles, the two-axis model: lifecycle phase vs workload category, the kind-first local path, and point at a cluster and install language.

### 1.2 Minimum kind plumbing (enabling)

- [x] 1.2.1 Add the minimum repository-owned kind config for `kind-dev-misc-local` so the tracer bullet can prepare a cluster for Flux bootstrap installation and reconciliation-marker validation.
- [x] 1.2.2 Add prerequisite guidance or checks for kind, kubectl, helm, flux CLI, and any other tools required for the Flux Helm chart and `flux2-sync` workflow.
- [x] 1.2.3 Add setup, teardown, recreate, and evidence commands that support the tracer bullet without becoming Makefile-only orchestration semantics.

### 1.3 Minimum runtime layout (enabling)

- [x] 1.3.1 Create `clusters/kind-dev-misc-local/entrypoint/` as the first GitOps reconciliation root and keep it limited to the direct `kubecrate-system` namespace manifest, the Flux self-management reference, and `kubecrate-reconciliation-marker`, without introducing empty `platform-services/` or `application-services/` skeleton directories.
- [x] 1.3.2 Create the minimum Flux durable layout for self-management handoff: `platform-services/flux/base/` for shared manifests and `clusters/kind-dev-misc-local/platform-services/flux/` for the cluster binding, including the cluster-local `helm-values.yaml` consumed by the Flux HelmRelease.
- [x] 1.3.3 Create `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` at the cluster entrypoint path with version X (`v0.1.0`) as a validation marker/config proof, not a platform service or application service.

### 1.4 Flux bootstrap and sync contract (enabling)

- [x] 1.4.1 Implement the Flux Helm chart bootstrap contract for release `flux-system` in namespace `flux-system`, including the minimum chart reference and values needed for the first tracer bullet and matching self-managed manifests under `platform-services/flux/base/` and `clusters/kind-dev-misc-local/platform-services/flux/`. Treat `flux-system` as the explicit approved Flux exception for this slice, while the general platform service dedicated namespace rule remains `core-<service-name>` for other services.
- [x] 1.4.2 Implement the `flux2-sync` contract for this repository and current implementation branch using SSH deploy-key generation, with `Secret/flux-system`, `GitRepository/flux-system`, and `Kustomization/flux-system` as the expected object names in namespace `flux-system`. Do not introduce `core-flux` for the first GitOps controller bootstrap or self-management path.
- [x] 1.4.3 Implement the public-key retrieval step from `Secret/flux-system` field `identity.pub` and expose it through bootstrap output or operator guidance so the operator can register it as a deploy key with the Git provider.
- [x] 1.4.4 Keep the generated private key in-cluster as Secret material and ensure no committed Helm values or other Git-managed files contain raw credential material.
- [x] 1.4.5 Wire `clusters/kind-dev-misc-local/entrypoint/kustomization.yaml` to reconcile the same desired-state path bootstrap prepared by including `kubecrate-system-namespace.yaml`, referencing `../platform-services/flux`, and including `kubecrate-reconciliation-marker.yaml`, preserving Flux self-management handoff.

### 1.5 Bootstrap installation execution

Validation note: static render or build checks are necessary but not sufficient after the bootstrap sequence or later reconciliation. Success for this slice requires the intended cluster context, expected resources, controller health, readiness or sync conditions, recent events or logs for blocking errors, and the operator-visible outcome. If health is failing or unclear, pause for bounded, symptom-driven diagnosis instead of claiming success.

- [x] 1.5.1 Prepare the kind cluster using kind plumbing from 1.2.
- [x] 1.5.2 Install Flux controllers through the planned Helm-driven bootstrap path against the prepared cluster.
- [x] 1.5.3 Run the planned `flux2-sync` workflow in SSH mode so the repository and branch are configured for GitOps-managed operation.
- [x] 1.5.4 Retrieve or display the generated public key from `Secret/flux-system`, register it with the Git provider as a deploy key for this repository, and record the registration evidence used in validation.
- [x] 1.5.5 Verify Flux controllers are running, `GitRepository/flux-system` is Ready through SSH access, `Kustomization/flux-system` is Ready, and the initial reconciliation completes after deploy-key registration.

Acceptance: Flux controllers are Healthy, `flux2-sync` has produced the required SSH key material in `Secret/flux-system`, the operator has a clear public-key registration step sourced from `identity.pub`, `flux get source git flux-system -n flux-system` and `flux get kustomization flux-system -n flux-system` show Ready, and evidence commands capture the state.

### 1.6 Flux self-management and `kubecrate-reconciliation-marker` at version X

- [x] 1.6.1 Confirm Flux is self-managing: verify Flux reconciles its own installation from the cluster entrypoint path.
- [x] 1.6.2 Verify `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` is reconciled through Flux at version X (`data.version: v0.1.0` or equivalent tracked config value) from `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml`.
- [x] 1.6.3 Capture baseline evidence: Flux status, `Secret/flux-system` presence, `GitRepository/flux-system` readiness, `Kustomization/flux-system` readiness, generated-public-key registration evidence, and `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` showing version X.

Acceptance: Flux Kustomization for itself shows Ready. `ConfigMap/kubecrate-reconciliation-marker` is present in namespace `kubecrate-system` at version X from `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml`. The evidence command `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` confirms `v0.1.0`. No bootstrap re-run is needed for Flux or the reconciliation marker proof to be active.

### 1.7 GitOps-managed update: `kubecrate-reconciliation-marker` version X→Y

- [x] 1.7.1 Change the Git-managed `kubecrate-reconciliation-marker` version from X to Y in `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml`.
- [x] 1.7.2 Push the change to the implementation branch and wait for Flux reconciliation or trigger reconciliation.
- [x] 1.7.3 Verify Flux detects the change, reconciles, and `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` reports version Y.
- [x] 1.7.4 Capture update evidence: `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` before and after the change, Flux reconciliation logs or events, and updated ConfigMap content.

Acceptance: `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` is verified at version Y (`v0.2.0`) after Flux reconciliation from `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml`. Evidence command output from `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` shows the version transition from X to Y triggered by the Git-managed change. Flux events or logs confirm the reconciliation.

## 2. Deferred platform services follow-up

- [ ] 2.1 Create or continue a separate branch or later OpenSpec change for External-Secrets Operator as deferred platform services work.
- [ ] 2.2 Define acceptance criteria for that ESO follow-up so it can introduce or finish External-Secrets Operator without blocking the Flux-first installable slice or first-slice readiness.
- [ ] 2.3 Keep the first installable slice scoped so the ESO follow-up is explicitly separate from the Flux-first tracer bullet and is not required for bootstrap installation or GitOps-managed operation acceptance in this change.
