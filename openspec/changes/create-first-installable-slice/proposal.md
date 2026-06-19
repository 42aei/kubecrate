## Why

Backlog 0008 is the forcing implementation change that transitions Kubecrate from planning artifacts into a concrete, runnable kind-first local path. Planning changes `define-install-flow` and `define-gitops-component-management` established contracts, boundaries, and deferred decisions that 0008 must now concretize, supersede, or resolve with runtime files. The project needs a small end-to-end tracer bullet—bootstrap installation through GitOps-managed operation with a Flux-managed reconciliation marker proof—on a prepared kind cluster before any broader platform services or application services work.

## What Changes

- **Concretize GitOps controller choice**: Flux is the first concrete GitOps controller. The prior changes deferred the controller choice; 0008 resolves it.
- **Supersede bootstrap packaging preference**: `define-install-flow` recorded Helm as the preferred bootstrap packaging candidate. 0008 adopts a **Kustomize-first** bootstrap path (`kubectl apply -k` or a thin wrapper). HelmRelease remains appropriate inside GitOps-managed operation for Helm-native platform services, but Helm is not the bootstrap package for this slice.
- **Supersede ESO provider baseline**: `define-gitops-component-management` set the ESO Fake provider as the kind-first local path baseline. 0008 requires Seed Secrets projection from a bootstrap-created Kubernetes Secret. The Fake provider does not validate this path because it does not read `seed-secrets`. The first Seed Secrets projection uses the ESO Kubernetes provider or an equivalent local provider that can read the bootstrap-created Kubernetes Secret.
- **Move ESO to bootstrap-critical**: `define-gitops-component-management` classified ESO as GitOps-managed after handoff. 0008 installs ESO during bootstrap installation, before Flux, so Flux can consume projected Git credentials. ESO remains bootstrap-critical for 0008.
- **Resolve repository boundary**: Prior changes deferred the repository boundary. 0008 places the first concrete runtime files directly in this repository. Template/example repository indirection is out of scope for the first slice.
- **Resolve runtime layout**: Prior changes left source-structure roles conceptual. 0008 adopts `clusters/<cluster>/entrypoint` as the first GitOps reconciliation root and allows `kubecrate-reconciliation-marker` to live directly in that concrete cluster path as validation material, without requiring empty workload-category skeleton directories. The first concrete cluster is `kind-dev-misc-local`, and the two-axis model remains the rule for future platform services and application services.
- **Apply the first platform services namespace rule**: dedicated platform services namespaces use the `core-<service-name>` pattern. For this slice, External-Secrets Operator uses `core-external-secrets-operator`.
- **Define kind validation plumbing**: Kind cluster creation and preparation remain outside bootstrap installation, but repository-owned kind validation plumbing—kind config, prerequisite checks, setup/teardown commands (Make targets or equivalent), and evidence commands—is within 0008 local validation scope.
- **Add a tracer bullet**: A concrete end-to-end validation path that proves GitOps-managed operation performs an update by reconciling marker version X, then changing the Git-managed marker version to Y and confirming Flux reconciles the update.
- **Normalize Seed Secret input contract**: `.env` is the real local operator input, `.env.example` is the committed documentation-only example, and bootstrap materializes `seed-secrets` from `.env` with a documented command or wrapper.
- **Set the initial Flux Git auth default**: Flux reconciles the repository's HTTPS remote and current branch using projected `username` and `password` credentials, with a fine-grained GitHub PAT as the default password value so read works now and write-back is ready before `ImageUpdateAutomation` is enabled.
- **Document later GitHub App reconsideration**: GitHub App auth is deferred in favor of the simpler PAT path now, but the design records when a GitHub App should be reconsidered.
- **Flux self-management handoff**: Bootstrap applies or loads the same Flux desired-state path that Flux later reconciles. Bootstrap is a loader/reference, not a second source of truth.

## Capabilities

### New Capabilities

- `first-installable-slice`: The first end-to-end bootstrap-to-GitOps vertical slice on a kind-first local path. Covers Kustomize-first bootstrap installation, ESO Seed Secrets projection, Flux self-management handoff, a Flux-managed reconciliation marker proof, kind validation plumbing, and tracer bullet validation evidence.

### Modified Capabilities

None. No existing global OpenSpec specs exist to modify. This change supersedes planning assumptions in prior OpenSpec changes (`define-install-flow`, `define-gitops-component-management`) through explicit design decisions rather than requirement deltas.

## Impact

- Adds the first concrete runtime files to this repository: bootstrap installation manifests, Flux desired-state path, ESO Kubernetes provider configuration, Seed Secrets bootstrap materialization from `.env`, the `kubecrate-reconciliation-marker` proof under the concrete cluster path for `kind-dev-misc-local`, and kind validation plumbing (kind config, Make targets or equivalents, evidence commands).
- Reclassifies ESO from GitOps-managed post-handoff installation to bootstrap-critical service installed before Flux handoff.
- Replaces the Helm-preferred bootstrap packaging assumption with Kustomize-first bootstrap.
- Replaces the ESO Fake provider baseline with Kubernetes provider for Seed Secrets projection.
- Resolves the deferred repository boundary question: this repository holds concrete runtime files.
- Resolves the deferred runtime layout: `clusters/<cluster>/entrypoint` is required now, while future workload-category structures remain available when real platform services or application services exist.
- Updates AGENTS.md phase guardrails to reflect that implementation has begun.
- Excludes ingress, certificate management, observability, policy (0011), and wave-like promotion policy/gating (0012).
