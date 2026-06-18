## Why

Backlog 0008 is the forcing implementation change that transitions Kubecrate from planning artifacts into a concrete, runnable kind-first local path. Planning changes `define-install-flow` and `define-gitops-component-management` established contracts, boundaries, and deferred decisions that 0008 must now concretize, supersede, or resolve with runtime files. The project needs a small end-to-end tracer bullet—bootstrap installation through GitOps-managed operation—on a prepared kind cluster before any broader platform work.

## What Changes

- **Concretize GitOps controller choice**: Flux is the first concrete GitOps controller. The prior changes deferred the controller choice; 0008 resolves it.
- **Supersede bootstrap packaging preference**: `define-install-flow` recorded Helm as the preferred bootstrap packaging candidate. 0008 adopts a **Kustomize-first** bootstrap path (`kubectl apply -k` or a thin wrapper). HelmRelease remains appropriate inside GitOps-managed operation for Helm-native platform services, but Helm is not the bootstrap package for this slice.
- **Supersede ESO provider baseline**: `define-gitops-component-management` set the ESO Fake provider as the kind-first local path baseline. 0008 requires Seed Secrets projection from a bootstrap-created Kubernetes Secret. The Fake provider does not validate this path because it does not read `seed-secrets`. The first Seed Secrets projection uses the ESO Kubernetes provider or an equivalent local provider that can read the bootstrap-created Kubernetes Secret.
- **Move ESO to bootstrap-critical**: `define-gitops-component-management` classified ESO as the first GitOps-managed platform service installed after handoff. 0008 installs ESO during bootstrap installation, before Flux, so Flux can consume projected Git credentials. ESO remains bootstrap-critical for 0008.
- **Resolve repository boundary**: Prior changes deferred the repository boundary. 0008 places the first concrete runtime files directly in this repository. Template/example repository indirection is out of scope for the first slice.
- **Resolve runtime layout**: Prior changes left source-structure roles conceptual. 0008 adopts a concrete layout: reusable platform service definitions under `platform-services/<service>/base`, concrete cluster enablement/config/version binding under `clusters/<cluster>/platform-services/<service>.yaml`, and `clusters/<cluster>/entrypoint` as the first GitOps reconciliation root. The first concrete cluster is `kind-dev-misc-local`.
- **Define kind validation plumbing**: Kind cluster creation and preparation remain outside bootstrap installation, but repository-owned kind validation plumbing—kind config, prerequisite checks, setup/teardown commands (Make targets or equivalent), and evidence commands—is within 0008 local validation scope.
- **Add a tracer bullet**: A concrete end-to-end validation path that proves GitOps-managed operation performs an update: install/reconcile one version, then change the Git-managed version/config and confirm Flux upgrades/reconciles it.
- **Supersede non-runnable guardrails**: Prior changes explicitly prohibited Kubernetes manifests and installation scripts. 0008 is the forcing implementation change that adds the first concrete runtime files needed by the tracer bullet. The AGENTS.md "current phase guardrails" are planning-pass guardrails; 0008 overrides them for its own implementation scope.
- **Flux self-management handoff**: Bootstrap applies/loads the same Flux desired-state path that Flux later reconciles. No duplicate independent Flux definitions under bootstrap installation and platform services. Bootstrap is a loader/reference, not a second source of truth.

## Capabilities

### New Capabilities

- `first-installable-slice`: The first end-to-end bootstrap-to-GitOps vertical slice on a kind-first local path. Covers Kustomize-first bootstrap installation, ESO Seed Secrets projection, Flux self-management handoff, the first GitOps-managed platform service, kind validation plumbing, and tracer bullet validation evidence.

### Modified Capabilities

None. No existing global OpenSpec specs exist to modify. This change supersedes planning assumptions in prior OpenSpec changes (`define-install-flow`, `define-gitops-component-management`) through explicit design decisions rather than requirement deltas.

## Impact

- Adds the first concrete runtime files to this repository: bootstrap installation manifests, Flux desired-state path, ESO Kubernetes provider configuration, Seed Secrets bootstrap materialization, cluster binding for `kind-dev-misc-local`, and kind validation plumbing (kind config, Make targets or equivalents, evidence commands).
- Reclassifies ESO from GitOps-managed platform service to bootstrap-critical service installed before Flux handoff.
- Replaces the Helm-preferred bootstrap packaging assumption with Kustomize-first bootstrap.
- Replaces the ESO Fake provider baseline with Kubernetes provider for Seed Secrets projection.
- Resolves the deferred repository boundary question: this repository holds concrete runtime files.
- Resolves the deferred runtime layout: `platform-services/<service>/base`, `clusters/<cluster>/`, and `clusters/<cluster>/entrypoint`.
- Updates AGENTS.md phase guardrails to reflect that implementation has begun.
- Excludes ingress, certificate management, observability, policy (0011), and wave-like promotion policy/gating (0012).
