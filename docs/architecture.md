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

Some bootstrap components have to be installed before GitOps-managed operation exists. That is a lifecycle constraint, not a different class of service.

This handoff is the main reason to keep the lifecycle axis separate from the workload category axis.

```mermaid
stateDiagram-v2
    [*] --> bootstrap_installation
    bootstrap_installation: bootstrap installation
    bootstrap_installation --> gitops_handoff_ready
    gitops_handoff_ready: GitOps controller running\nbound to Git source\nable to reconcile initial structure
    gitops_handoff_ready --> gitops_managed_operation
    gitops_managed_operation: GitOps-managed operation
```

Once GitOps-managed operation is available, platform services and application services should be reconciled through GitOps unless a later proposal explicitly documents why a bootstrap-managed exception is still necessary.

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
