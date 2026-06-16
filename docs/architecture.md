# Architecture

## Context

Kubecrate is a minimal cloud-native platform in a box.

The target experience is point at a cluster and install. Over time, that should work with any conforming Kubernetes cluster. The first path is narrower on purpose: a kind-first local path for reference use.

## Design posture

The project follows a few practical preferences:

- minimal over comprehensive
- opinionated over configurable
- open source first
- GitOps by default
- production-inspired, not production-ready

The goal is not a platform framework. It is a small, understandable platform baseline.

## Two workload categories

Kubecrate separates workloads into two categories.

### Platform services

Platform services are shared capabilities that make the platform usable.

They are often upstream or open source components such as ingress, certificate management, secret handling, observability building blocks, or GitOps controllers.

### Application services

Application services are the user or company workloads that consume the platform.

They are the workloads people want to run once the shared capabilities exist.

## Bootstrap is a lifecycle mode

Bootstrap is not a separate workload category.

Some platform services have to be installed before GitOps exists. That is a lifecycle constraint, not a different class of service.

Once GitOps is available, those same services should move to GitOps-managed operation unless a later proposal explicitly documents why a bootstrap-managed exception is still necessary.

This keeps the long-term handling of platform services and application services aligned and reduces special-case operational paths.

## Two axes to preserve

Repository docs, proposals, and tasks should keep two axes visible:

1. lifecycle phase
   - bootstrap installation
   - GitOps-managed operation
2. workload category
   - platform services
   - application services

If those axes blur, the project becomes harder to reason about.

## Implications for implementation

The first implementation slices should answer a small set of questions:

- What is the minimum component set needed for a useful platform baseline?
- What must exist during bootstrap installation?
- What should move into GitOps-managed operation once the GitOps controller is running?
- What should the kind-first local path look like without treating it as the only future path?

That is why this first repository pass stays docs-first. The project needs a stable vocabulary and operating model before it needs scaffolding.
