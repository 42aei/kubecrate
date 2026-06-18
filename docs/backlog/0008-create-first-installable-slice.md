---
task_id: "0008"
title: "Create first kind-first installable bootstrap-to-GitOps slice"
status: "proposed"
depends_on: ["0003", "0004", "0007", "0010"]
---

## Goal

Create the first reviewable installable vertical slice for Kubecrate using the kind-first local path that proves a small end-to-end path from bootstrap installation toward GitOps-managed operation.

This item should become an OpenSpec proposal before implementation. Do not turn it into a full specification in this backlog entry.

## Scope

A vertical slice that targets a prepared kind cluster and installs a minimal platform baseline into it. It is not a broad horizontal platform foundation. Ingress, certificate management, observability, policy, and multi-environment/wave-like promotion are explicitly out of scope for 0008 (see 0011 and 0012).

Kind cluster creation and preparation that validates the local environment is repository-owned local validation setup for the kind-first local path. It is not bootstrap installation. Bootstrap installation — `point at a cluster and install` — starts only once the Kubernetes API is reachable and the installer has usable credentials. This boundary keeps the bootstrap lifecycle phase focused on cluster-internal operations and avoids conflating environment preparation with lifecycle management.

The slice must make concrete decisions in these areas:

- **GitOps controller selection** — Choose the first GitOps controller (e.g., Flux, Argo CD, or another) for the kind-first bootstrap. The controller is initially installed during bootstrap installation, not as a GitOps-managed management unit at install time. The bootstrap installation contract's deferred controller choice is resolved here.

- **Bootstrap packaging / interface** — Define how bootstrap installation installs into the prepared cluster. Contract-first packaging posture is settled; this slice selects the concrete packaging format (Helm chart, Kustomize overlay, controller wrapper, or a combination) that satisfies the management-unit contract from the define-gitops-component-management change. Bootstrap installation must not depend on a GitOps provider to install the controller itself.

- **Runtime source layout** — Define the first runtime directory structure under the repository placement rules, preserving the two-axis model (lifecycle phase: bootstrap installation / GitOps-managed operation; workload category: platform services / application services). The layout must express platform services as separate management units, distinguish environment binding, and keep ordering and ownership boundaries clear.

- **Repository boundary** — Resolve whether this repository is a one-stop shop or whether template or example repositories hold platform services and application services definitions. This decision is forced by the need to place runtime files.

- **Controller self-management / bootstrap-to-GitOps ownership handoff mechanics** — Define how the initially bootstrap-installed GitOps controller and supporting bootstrap resources come under GitOps-managed operation after handoff. The controller is not a GitOps-managed management unit at initial installation time; this task defines its subsequent ownership model. This covers the concrete mechanics deferred by the define-gitops-component-management change.

- **ESO Fake provider validation** — Confirm that External-Secrets Operator with the Fake provider (or an equivalent ConfigMap-based local provider) works as the kind-first local path secret-handling baseline. If exact ESO provider naming or API is not validated here, capture it as a proposal validation task rather than a hard implementation claim.

- **Local validation / evidence contract** — Define what validation gates and evidence an installable slice must satisfy before it is considered complete: e.g., cluster bootstrap succeeds, GitOps controller reconciles, ESO deploys and can sync a secret from the Fake provider, and the setup survives a kind cluster restart.

## Decisions to make

- Which GitOps controller for the kind-first bootstrap?
- What concrete packaging format for the bootstrap-delivered controller and the first GitOps-managed platform service?
- What runtime directory layout expresses the two-axis model with separate management units and separable environment binding?
- Single-repository vs. template/example repository boundary?
- How does the bootstrap-installed controller hand off ownership to GitOps-managed operation (controller self-management style)?
- What is the minimum validation evidence that proves the slice works?

## Tasks

The following are candidate tasks for the OpenSpec proposal. They are listed here as starting points; the proposal may refine, reorder, or merge them.

1. Choose the first GitOps controller for the kind-first bootstrap path.
2. Define the first runtime source layout and repository boundary.
3. Define bootstrap-to-GitOps ownership handoff mechanics.
4. Define the local validation/evidence contract for installable slices.
5. Implement bootstrap installation against a prepared kind cluster with the chosen GitOps controller.
6. Implement the first GitOps-managed platform service (ESO with Fake provider) as a management unit.
7. Validate the end-to-end slice.

## Acceptance direction

- A reviewer can exercise `point at a cluster and install` on the kind-first local path by targeting a prepared kind cluster from a defined starting point.
- Kind cluster creation and credential setup is repository-owned local validation infrastructure; bootstrap installation starts from a cluster with a reachable Kubernetes API and usable credentials.
- Against a prepared kind cluster, the slice produces a running GitOps controller and at least one GitOps-managed platform service (ESO with Fake / ConfigMap-based local provider).
- The bootstrap-installed resources come under GitOps-managed operation after handoff.
- Validation evidence is captured and reproducible.

## Notes

- This is a vertical slice, not a broad horizontal platform foundation. Ingress, certificate management, observability, and policy are deferred (see 0011). Multi-environment and wave-like promotion are deferred (see 0012).
- The management-unit contract and source-structure contract from the define-gitops-component-management change are binding inputs.
- The kind-first local path (0003), repository placement rules (0004), minimal component set (0007), and GitOps source structure (0010) are all completed prerequisites.
- Explicitly identify which decisions from the define-gitops-component-management change this slice resolves and which it carries forward or defers.
