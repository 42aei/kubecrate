---
task_id: "0008"
title: "Create first kind-first installable bootstrap-to-GitOps slice"
status: "started"
depends_on: ["0003", "0004", "0007", "0010"]
---

## Goal

Create the first reviewable installable vertical slice for Kubecrate using the kind-first local path that proves a small end-to-end path from bootstrap installation toward GitOps-managed operation.

This item should become an OpenSpec proposal before implementation. Do not turn it into a full specification in this backlog entry.

## Scope

A vertical slice that targets a prepared kind cluster and installs a minimal platform baseline into it. It is not a broad horizontal platform foundation. Ingress, certificate management, observability, and policy are explicitly out of scope for 0008 (see 0011). Wave-like promotion policy and gating are also out of scope for 0008 (see 0012), but the slice must preserve environment-specific configuration and future wave-like promotion as capabilities.

Kind cluster creation and preparation that validates the local environment is repository-owned local validation setup for the kind-first local path. It is not bootstrap installation. Bootstrap installation — `point at a cluster and install` — starts only once the Kubernetes API is reachable and the installer has usable credentials. This boundary keeps the bootstrap lifecycle phase focused on cluster-internal operations and avoids conflating environment preparation with lifecycle management.

## Accepted 0008 direction

The planning discussion already resolved the following 0008 design direction. The OpenSpec proposal should treat these as accepted inputs, not open questions.

- **GitOps controller** — 0008 uses **Flux** as the first concrete GitOps controller.
- **Bootstrap packaging / interface** — 0008 uses a **Kustomize-first** bootstrap path, likely `kubectl apply -k` or a very thin wrapper around it. Helm is not the Kubecrate bootstrap package for this first slice. HelmRelease remains appropriate inside GitOps-managed operation for Helm-native platform services.
- **Seed Secrets and ESO** — 0008 uses **Seed Secrets** as the operator-provided local input path. A real `.env` file must not be committed. Bootstrap installation materializes one Secret named `seed-secrets` in the `core-external-secrets-operator` namespace. ESO is bootstrap-critical for 0008 and is installed before Flux so Flux can consume projected Git credentials. Services and controllers consume narrow ESO-projected Secrets, not the raw `seed-secrets` Secret. The Fake provider does not validate this path because it does not read `seed-secrets`. The first Seed Secrets projection should therefore use the ESO Kubernetes provider or an equivalent local provider that can read the bootstrap-created Kubernetes Secret.
- **Flux self-management handoff** — 0008 uses a self-managing controller model. Bootstrap installation applies or loads the same Flux desired-state path that Flux later reconciles. There must not be duplicate independent Flux definitions under bootstrap installation and platform services. Bootstrap installation is a loader or reference, not a second source of truth.
- **Runtime layout direction** — Reusable platform service definitions live under `platform-services/<service>/base`. Concrete cluster enablement, configuration, and version binding live under `clusters/<cluster>/platform-services/<service>.yaml` or an equivalent cluster binding path. `clusters/<cluster>/entrypoint` is the first GitOps reconciliation root for a concrete cluster. Do not make `platform-services/<service>/kind` the default pattern. Introduce reusable variants only if later duplication justifies them.
- **Repository boundary** — 0008 uses this repository for the first concrete runtime files needed by the tracer bullet. Template or example repository indirection is not part of the first slice.
- **Concrete cluster model** — Concrete cluster directories are the first runtime model. The first naming convention is `<provider>-<environment>-<workload>-<location>`, for example `gcp-prod-web-eu1`, `gcp-prod-web-us1`, `gcp-prod-storage-eu1`, `gcp-staging-web-eu1`, `gcp-staging-storage-eu1`, `aws-prod-web-eu1`, and `kind-dev-misc-local`. This preserves environment as a capability through concrete cluster identity rather than replacing environment with clusters only. It is a pragmatic first convention, not an immutable taxonomy.
- **Kind plumbing** — Kind cluster creation and preparation remain outside bootstrap installation, but repository-owned kind validation plumbing is a substantial part of 0008 local validation scope. The slice should define kind config, prerequisite docs or checks, setup commands such as Make targets or equivalents, teardown and recreate expectations, and evidence commands needed to prove the kind-first local path.
- **Tracer bullet validation** — 0008 should include a tracer bullet that proves GitOps-managed operation performs an update, for example by reconciling one version first and then changing the Git-managed version and confirming Flux upgrades it.

## OpenSpec proposal focus

The proposal still needs to turn the accepted direction into a reviewable slice. The main work is to define the smallest concrete implementation and validation path that proves the model.

## Tasks

The following are candidate tasks for the OpenSpec proposal. They are listed here as starting points; the proposal may refine, reorder, or merge them.

1. Define the smallest concrete runtime files that express the accepted Flux, Seed Secrets, and cluster binding direction.
2. Define the bootstrap installation path for a prepared kind cluster using the accepted Kustomize-first interface.
3. Define the Flux self-management handoff so bootstrap installation references the same desired-state path that Flux later reconciles.
4. Define the local validation and evidence contract, including repository-owned kind setup plumbing needed for the kind-first local path.
5. Implement bootstrap installation against a prepared kind cluster with Flux and bootstrap-critical ESO.
6. Implement the first tracer bullet secret-handling path, including Seed Secrets projection for Flux and the Flux-managed `kubecrate-reconciliation-marker` validation marker/config proof needed to prove the slice. The marker is not a platform service or application service.
7. Validate the end-to-end slice, including a GitOps-driven update.

## Acceptance direction

- A reviewer can exercise `point at a cluster and install` on the kind-first local path by targeting a prepared kind cluster from a defined starting point.
- Repository-owned kind validation plumbing exists for local proof, including kind config, prerequisite docs or checks, setup commands such as Make targets or equivalents, teardown and recreate expectations, and evidence commands, but bootstrap installation still starts only from a cluster with a reachable Kubernetes API and usable credentials.
- Against a prepared kind cluster, the slice produces bootstrap-critical ESO, projected Seed Secrets for Flux, a running Flux controller, and the Flux-managed `kubecrate-reconciliation-marker` validation marker/config proof needed by the tracer bullet. The marker is not a platform service or application service.
- Flux becomes self-managing after handoff without duplicate independent Flux definitions in bootstrap installation and platform services.
- Runtime files follow the accepted first model: reusable platform service definitions plus concrete cluster binding rooted at a concrete cluster entrypoint.
- Validation evidence proves reconciliation works and that a Git-managed change causes Flux to update the tracer bullet.

## Notes

- Active OpenSpec change: `openspec/changes/create-first-installable-slice/`.
- For 0008, the active OpenSpec change supersedes older wording that treated the tracer bullet as workload-category content and replaces it with the Flux-managed `kubecrate-reconciliation-marker` validation marker/config proof. The marker is not a platform service or application service.
- This is a vertical slice, not a broad horizontal platform foundation. Ingress, certificate management, observability, and policy are deferred (see 0011). Wave-like promotion policy and gating are deferred (see 0012), but environment-specific configuration and future wave-like promotion remain preserved capabilities.
- The management-unit contract and source-structure contract from the define-gitops-component-management change are binding inputs.
- The kind-first local path (0003), repository placement rules (0004), minimal component set (0007), and GitOps source structure (0010) are all completed prerequisites.
- Explicitly identify which previously deferred decisions this slice now resolves for 0008 and which broader contracts remain intentionally controller-agnostic.
