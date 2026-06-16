# Kubecrate

Kubecrate is a minimal cloud-native platform in a box.

The intended format is simple: point at a cluster and install.

The long-term goal is cluster-provider agnostic operation, where any conforming Kubernetes cluster can eventually work. The implementation roadmap starts with a kind-first local path so the first slices stay small, testable, and easy to understand.

This project is aimed at people who need a practical platform starting point without a large internal platform team behind it. That includes newer platform engineers, homelab and dev platform users, and small teams that want a clear baseline rather than a highly configurable framework.

## What Kubecrate is trying to do

Kubecrate is opinionated on purpose.

The project prefers:

- minimal over comprehensive
- opinionated over configurable
- open source first
- GitOps by default
- production-inspired, not production-ready

The main idea is to keep long-term handling of platform services and application services as aligned as possible. In practice, that should reduce operational drift and lower the amount of special-case process around the platform itself.

## Core model

Kubecrate uses two workload categories:

- platform services: shared capabilities that make the platform usable, often upstream or open source components
- application services: user or company workloads that consume the platform

Bootstrap is not a third workload category. It is a lifecycle or management mode.

Some platform services need to be installed before GitOps exists. After GitOps is available, those same services should move toward GitOps-managed operation for ongoing maintenance.

That gives the project two axes to reason about:

1. lifecycle phase: bootstrap installation or GitOps-managed operation
2. workload category: platform services or application services

## Current repository scope

This first pass is docs-first.

The repository currently focuses on defining the project shape, architecture language, roadmap, and backlog. It does not yet include Kubernetes manifests, installation scripts, or technical scaffolding for runtime components.

## Documents

- `docs/README.md` for the docs map
- `docs/architecture.md` for the operating model
- `docs/roadmap.md` for the implementation direction
- `docs/backlog/` for lightweight raw task captures

## Status

Kubecrate is early.

The immediate goal is to define a small first installable slice around the kind-first local path, while keeping the wording and repository structure aligned with the broader cluster-provider agnostic vision.
