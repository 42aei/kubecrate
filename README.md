<p align="center">
  <img src="docs/logos/kubecrate-logo.svg" alt="KubeCrate logo" width="600">
</p>

# Kubecrate

Kubecrate is a minimal cloud-native platform in a box.

The target experience is simple: point at a cluster and install.

The long-term goal is cluster-provider agnostic operation. The first path is a kind-first local path so early slices stay small and testable.

Kubecrate is for people who need a practical platform starting point without a large platform team. That includes newer platform engineers, homelab users, and small teams that want a clear baseline instead of a highly configurable framework.

## Project posture

Kubecrate is opinionated on purpose.

- minimal over comprehensive
- opinionated over configurable
- open source first
- GitOps by default
- production-inspired, not production-ready

## Core model

Kubecrate has two axes:

1. lifecycle phase: bootstrap installation or GitOps-managed operation
2. workload category: platform services or application services

Platform services are shared capabilities that make the platform usable.

Application services are the workloads that run on it.

Bootstrap is not a third workload category. It is a lifecycle or management mode.

In practice, some platform services need bootstrap installation before GitOps exists. After that, they should move into GitOps-managed operation.

## Current repository scope

This repository is currently in an architecture and planning phase.

It defines the project model, vocabulary, roadmap, and backlog before adding Kubernetes manifests, installation scripts, or runtime structure.

## Documents

- `docs/README.md` for the docs map
- `docs/architecture.md` for the operating model
- `docs/bootstrap-installation-contract.md` for the bootstrap installation contract and GitOps handoff
- `docs/roadmap.md` for the near-term direction
- `docs/backlog/` for lightweight raw captures

## Status

Kubecrate is early.

The next goal is a small first installable slice on the kind-first local path, without losing the broader cluster-provider agnostic direction.
