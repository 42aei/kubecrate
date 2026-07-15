## Context

Backlog 0008 remains the forcing change that moves Kubecrate from planning-only artifacts toward the first installable tracer bullet. This branch defines the proposal-approved runtime files for that slice under the existing AGENTS.md guardrails, while keeping the implementation narrow: prove bootstrap installation through GitOps-managed operation on the kind-first local path with the fewest moving parts that still preserve production-shaped behavior.

The revised 0008 direction keeps Flux as the first GitOps controller and keeps Flux self-management handoff plus the `kubecrate-reconciliation-marker` proof, while pivoting away from ESO projection for the first slice. The first tracer bullet is now prepared kind cluster → Helm-driven Flux bootstrap → `flux2-sync` SSH deploy-key generation and operator registration step → GitOps-managed operation → reconciliation marker update evidence.

## Goals / Non-Goals

**Goals:**

- Define the smallest concrete tracer bullet: prepared kind cluster → Helm-driven Flux bootstrap → `flux2-sync` SSH deploy-key generation and registration step → Flux self-management handoff → Flux-managed update evidence.
- Define exact lifecycle boundaries for what kind plumbing owns versus what bootstrap installation owns versus what GitOps-managed operation owns.
- Define the operator workflow for generated deploy-key registration, including what is safe to display and what remains in-cluster as Secret material.
- Define the file model and source-of-truth rules for Flux bootstrap and reconciliation without introducing committed credential material.
- Preserve the two-axis model: lifecycle phase vs workload category, with bootstrap installation kept separate from platform services and application services.
- Define the validation/evidence plan for the tracer bullet, including the `kubecrate-reconciliation-marker` update-proving step.
- Minimize horizontal enabling work so all setup serves the first vertical slice.

**Non-Goals:**

- Ingress, certificate management, observability, policy, wave-like promotion policy/gating.
- Template/example repository indirection or multi-repository source models.
- Provider-specific clusters beyond the kind-first local path.
- ESO projection in the first tracer bullet.
- Full platform services catalog or application services definitions beyond the tracer bullet need.

## Decisions

### Tracer bullet is the first implementation task

The first implementation task is the tracer bullet: prepared kind cluster → Helm-driven Flux bootstrap installation → `flux2-sync` SSH deploy-key generation and operator registration step → Flux handoff/self-management → Flux-managed update evidence. All other tasks are minimum enabling steps nested inside the tracer bullet task, not standalone horizontal phases.

The tracer bullet deploys a Flux-managed reconciliation marker named `kubecrate-reconciliation-marker` whose sole purpose is to prove GitOps reconciliation: bootstrap prepares it at version X, then a Git-managed change bumps the marker version to Y, and Flux reconciles the update. The marker is a validation marker/config proof, not a platform service or application service.

This ensures the first reviewable increment proves the entire vertical slice works end-to-end. Horizontal setup is scoped to what the tracer bullet needs, not a broad foundation.

Alternatives considered:
- Lay out all directories, manifests, and plumbing before the tracer bullet. Rejected because it delays the first working proof and risks building scaffolding the tracer bullet never exercises.
- Keep ESO in the first tracer bullet. Rejected for this slice because it adds extra moving parts before the first Flux bootstrap and reconciliation proof exists.

### Lifecycle boundaries: kind plumbing, bootstrap installation, GitOps-managed operation

Three distinct lifecycle boundaries exist in 0008:

1. **Kind plumbing** (outside bootstrap installation): repository-owned kind config, prerequisite docs/checks, setup commands (Make targets or equivalent), teardown/recreate expectations, and evidence commands. Kind cluster creation and preparation validates the local environment but does not install Kubecrate. The Kubernetes API is reachable and the operator has usable credentials at the end of kind plumbing.

2. **Bootstrap installation** starts when kind plumbing completes and the operator runs `point at a cluster and install` against a reachable Kubernetes API with usable credentials. Bootstrap installs Flux from Helm charts, creates or applies the first Flux desired-state path, runs `flux2-sync` in SSH mode so the private key material remains in-cluster as a Secret, and exposes the generated public key for operator registration with the Git provider.

3. **GitOps-managed operation** begins after Flux handoff and public-key registration. Flux reconciles the same desired-state path bootstrap applied. Flux self-manages its own configuration. Real platform services or application services remain future workload-category content; the first proof in 0008 is only the reconciliation marker.

Bootstrap is a lifecycle phase, not a service category. This first slice does not require a bootstrap-critical platform service beyond Flux itself.

Alternatives considered:
- Collapse kind plumbing into bootstrap installation. Rejected because it conflates environment preparation with lifecycle management.
- Treat bootstrap as a service category. Rejected because it would violate the two-axis model: lifecycle phase vs workload category.

### Helm-driven Flux bootstrap path

Bootstrap installation uses Flux Helm charts as the first concrete installation path for this tracer bullet. The operator workflow stays minimal: install Flux controllers, establish the Git source and cluster sync path, hand off to Flux self-management, and then prove reconciliation with `kubecrate-reconciliation-marker`.

The bootstrap execution path is a small Helm-driven sequence that:
- Installs Flux controllers from the selected Helm chart path
- Creates or applies the first cluster entrypoint and `flux2-sync` resources for the current repository and branch
- Generates SSH deploy-key material through `flux2-sync`, keeping the private key in-cluster as Secret material
- Exposes the generated public key so the operator can register it as a deploy key with the Git provider
- Hands off to Flux so it reconciles the same desired-state path that bootstrap prepared

No committed Helm values or other Git-managed files may contain raw credential material. Generated private key material remains cluster state, and the displayed or retrieved public key is the only credential-related material safe to show for operator registration.

Alternatives considered:
- Keep a Kustomize-first bootstrap path for this slice. Rejected because this pivot is intentionally reducing the first installable path to Flux Helm charts plus sync setup.
- Commit static SSH key material or other credentials in values files. Rejected because committed credential material is not acceptable.

### SSH deploy-key generation and operator registration

The first slice uses SSH deploy-key generation through `flux2-sync` instead of a bootstrap-provided credential projection flow. The generated private key remains in-cluster as Secret material owned by Flux resources. The generated public key is safe to retrieve, display, and register with the Git provider as a deploy key.

The operator workflow is:
1. Bootstrap installs Flux and applies the initial sync resources for the current repository and branch.
2. `flux2-sync` generates SSH key material and stores the private key in-cluster.
3. Bootstrap output or follow-up guidance retrieves the generated public key.
4. The operator registers that public key with the Git provider as a deploy key.
5. Flux reaches Ready state against the configured repository and branch, then enters GitOps-managed operation.

This keeps raw secret material out of committed files while preserving the point at a cluster and install operator story, with one explicit manual registration step.

Alternatives considered:
- Commit static deploy keys. Rejected because committed credential material is not acceptable.
- Keep the first slice dependent on a separate projection controller. Rejected because it is unnecessary for the first reconciliation proof.

### Flux self-management handoff

Flux self-management means Flux reconciles its own installation from the same desired-state path that bootstrap applied. Bootstrap is a loader/reference, not a second source of truth.

The handoff sequence:
1. Bootstrap installs Flux and prepares the Flux desired-state path.
2. Bootstrap prepares the same cluster entrypoint content that Flux will later reconcile.
3. Flux starts, reaches repository access after deploy-key registration, finds itself in the desired-state path, and becomes self-managing.
4. Subsequent changes to Flux configuration in the desired-state path are reconciled by Flux itself.

There is one source of truth for Flux configuration: the cluster path under `clusters/<cluster>/` and the reusable manifests it references. Bootstrap does not maintain a duplicate.

Alternatives considered:
- Bootstrap installs Flux independently, then Flux reconciles a different path. Rejected because it creates two sources of truth for Flux configuration.
- Bootstrap installs a boot Flux that installs a real Flux. Rejected as unnecessary indirection for the kind-first local path.

### Flux Git source contract for kind

Flux reconciles this repository and the current implementation branch through SSH. The Flux `GitRepository` manifest is the source of truth for the repository SSH URL and selected branch. These repository and branch values are Git-managed desired state, not operator-entered secret values.

The first slice uses `flux2-sync` generated SSH key material for repository access. The private key remains in-cluster as Secret material. The public key is safe to retrieve and register with the Git provider as a deploy key. No raw username/password credential path is part of the first tracer bullet.

Local Git server alternatives are secondary and explicitly out of the default path for this slice. The repository-hosted SSH deploy-key path is the recommended default because it validates the real GitOps-managed operation contract without additional infrastructure.

### Runtime layout

The durable runtime layout for 0008 is:

```
platform-services/
  flux/
    base/
      kustomization.yaml
      helm-repository.yaml
      helm-release.yaml
clusters/
  kind-dev-misc-local/
    entrypoint/
      kustomization.yaml
      kubecrate-system-namespace.yaml
      kubecrate-reconciliation-marker.yaml
    platform-services/
      flux/
        kustomization.yaml
        helm-values.yaml
```

- `platform-services/flux/base/` is the reusable platform services base for Flux self-management manifests. It carries the shared HelmRepository, HelmRelease, and related base manifests for the Flux platform service.
- `clusters/kind-dev-misc-local/platform-services/flux/` is the cluster binding for that platform service on the kind-first local path. It carries the cluster-local `kustomization.yaml` and `helm-values.yaml` consumed by the self-managed Flux HelmRelease.
- `clusters/kind-dev-misc-local/entrypoint/` is the first GitOps reconciliation root for that cluster. `clusters/kind-dev-misc-local/entrypoint/kustomization.yaml` includes `kubecrate-system-namespace.yaml`, `../platform-services/flux` for Flux self-management, and `kubecrate-reconciliation-marker.yaml` for the reconciliation proof.
- `clusters/kind-dev-misc-local/entrypoint/kubecrate-system-namespace.yaml` creates namespace `kubecrate-system` directly in the entrypoint so the marker namespace exists before the marker is reconciled.
- `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml` defines `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` as the first validation proof. It remains cluster-owned validation material, not a platform service or application service.
- Future real platform services continue to use `platform-services/<service>/base/` plus `clusters/<cluster>/platform-services/<service>/`, which preserves the two-axis model: lifecycle phase vs workload category.
- Future real application services use `application-services/<service>/base/` plus `clusters/<cluster>/application-services/<service>/` when they are introduced.

The bootstrap installation contract must match that durable layout: bootstrap installs Flux controllers with the same release name, namespace, chart reference, and values shape later expressed by `platform-services/flux/base/` and `clusters/kind-dev-misc-local/platform-services/flux/`. The entrypoint path is therefore both the first applied desired state and the later Flux-reconciled source of truth.

Do not create empty workload-category skeleton directories before a real platform service or application service needs them. The Flux paths above are required because Flux is the first concrete platform service in this slice; no broader speculative scaffolding is needed.

### Flux namespace authority for the first slice

The general platform service dedicated namespace rule remains `core-<service-name>`. That rule continues to apply to future platform services that need their own namespace.

Flux is an explicit approved exception for this first slice: Flux controllers and the first GitOps controller bootstrap or self-management objects use namespace `flux-system`, not `core-flux`.

This exception is concrete and tool-specific, not a new workload-category rule. The first slice uses Flux Helm chart defaults plus the conventional `flux2-sync` bootstrap object conventions, which use `flux-system` for:

- Flux controllers
- generated Git credential `Secret/flux-system-sync`
- `GitRepository/flux-system-sync`
- `Kustomization/flux-system-sync`

Keeping `flux-system` avoids inventing a parallel `core-flux` namespace contract that would diverge from Flux chart defaults, Flux bootstrap ecosystem examples, and the object naming or namespace conventions used for the first GitOps controller bootstrap path. This keeps bootstrap installation and GitOps-managed operation aligned on the same controller namespace and object identities.

### Concrete `flux2-sync` contract for the first slice

The first slice uses the conventional Flux bootstrap object names in namespace `flux-system`:

- Secret: `flux-system-sync`
- GitRepository: `flux-system-sync`
- Kustomization: `flux-system-sync`

Bootstrap applies the initial Git source and reconciliation objects so those names are stable across bootstrap installation and GitOps-managed operation. `flux2-sync` runs in SSH mode against this repository and the active implementation branch. The generated private key remains in `Secret/flux-system-sync` in namespace `flux-system`.

The public-key retrieval step is concrete for this slice: the operator retrieves the generated deploy key from `Secret/flux-system-sync` with an operator-visible command equivalent to `kubectl -n flux-system get secret flux-system-sync -o jsonpath='{.data.identity\\.pub}' | base64 -d`. Bootstrap output or companion docs may wrap that command, but the source of truth is the generated `identity.pub` field in `Secret/flux-system-sync`.

Registration and reconciliation evidence for the tracer bullet is:

1. `kubectl -n flux-system get secret flux-system-sync` shows the generated Secret exists.
2. The operator registers the retrieved public key with the Git provider as a deploy key for this repository.
3. `flux get sources git -n flux-system` or equivalent object-specific status shows `GitRepository/flux-system-sync` Ready against the configured SSH repository URL and branch.
4. `flux get kustomizations -n flux-system` or equivalent object-specific status shows `Kustomization/flux-system-sync` Ready.
5. The entrypoint content, including `kubecrate-reconciliation-marker`, reconciles without bootstrap re-applying desired state after deploy-key registration.

### Kind validation plumbing

Kind cluster creation and preparation are repository-owned local validation setup, not bootstrap installation. The plumbing includes:

- **kind config**: A kind cluster configuration file defining the `kind-dev-misc-local` cluster with sufficient resources for the tracer bullet.
- **Prerequisite checks**: Documentation or automated checks verifying kind, kubectl, helm, flux CLI, and other prerequisites are installed and at compatible versions.
- **Setup commands**: Make targets or equivalent scripts that create the kind cluster from the config.
- **Teardown/recreate expectations**: Commands to delete and recreate the cluster for clean-slate validation.
- **Evidence commands**: Commands that capture cluster state for validation evidence.

Evidence for this pivot must center on Flux install state, generated public-key retrieval, GitRepository or Kustomization readiness, and reconciliation marker version rather than deferred platform service controllers.

### Tracer bullet validation

The tracer bullet proves GitOps-managed operation performs an update using `kubecrate-reconciliation-marker`, a Flux-managed validation marker/config proof whose sole purpose is to demonstrate reconciliation:

1. **Baseline bootstrap and registration**: Bootstrap installs Flux, `flux2-sync` generates SSH key material, the operator retrieves the public key and registers it with the Git provider as a deploy key, and Flux reaches Ready state against the configured repository and branch.
2. **Baseline reconcile**: After registration, Flux reconciles the desired state and `kubecrate-reconciliation-marker` is present at version X (`data.version: v0.1.0` or equivalent config value tracked in `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml`).
3. **Git-managed change**: The operator commits a version bump for `kubecrate-reconciliation-marker` from `v0.1.0` to `v0.2.0` in the cluster entrypoint path and pushes to the implementation branch.
4. **Flux update evidence**: Flux detects the change, reconciles, and `kubecrate-reconciliation-marker` reports version Y. Evidence captures the before/after version value, Flux reconciliation logs or status, and the updated ConfigMap content.

Version X→Y is defined via a Git-managed config value with operator-visible evidence commands before and after the change.

The validation is operational and evidence-command based. Tests and checks focus on observable install/reconcile behavior rather than unit-test coverage.

## Risks / Trade-offs

- [Risk] The manual deploy-key registration step interrupts a fully automated bootstrap installation story. → Mitigation: keep the step explicit, small, and well-evidenced in the operator workflow for the first tracer bullet.
- [Risk] Flux chart installation may still create sensitive Helm release Secret content in-cluster. → Mitigation: keep raw credential material out of committed files and treat cluster-held release data as sensitive operational state.
- [Risk] Flux chart maintenance or community-status changes could affect the long-term bootstrap path. → Mitigation: record the chart choice explicitly and revisit if chart maintenance or upstream guidance changes.
- [Risk] The first slice does not prove ESO projection. → Mitigation: classify ESO clearly as deferred platform services work in a separate branch or later change with its own acceptance criteria; ESO is not required for first-slice readiness.
- [Risk] Kind plumbing may drift from the actual operator workflow. → Mitigation: the tracer bullet exercises the plumbing end-to-end, keeping it honest. Evidence commands capture actual output.
