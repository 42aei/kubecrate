# Install flow

This document defines the contract for Kubecrate bootstrap installation. It explains what `point at a cluster and install` means from the operator point of view and where bootstrap installation hands off to GitOps-managed operation.

## Point at a cluster and install

`point at a cluster and install` is the target operator experience. The operator or a calling tool provides access to a Kubernetes cluster, and Kubecrate installs the bootstrap components that establish GitOps-managed operation.

The contract preserves the two-axis model:

- **lifecycle phase**: bootstrap installation or GitOps-managed operation
- **workload category**: platform services or application services

Bootstrap installation is a lifecycle phase, not a third workload category.

## Bootstrap installation start boundary

Bootstrap installation starts after:

- a conforming Kubernetes API is reachable, and
- the operator or calling tool can provide credentials to apply bootstrap resources.

Cluster creation is outside the bootstrap installation boundary. Any kind-first local cluster setup belongs to a separate reference path or future proposal; it is a driver for the contract, not the contract itself.

## Bootstrap installation completion and GitOps handoff

Bootstrap installation is complete when:

- a GitOps controller is running in the cluster,
- the controller is bound to a Git source, and
- the GitOps controller can reconcile an established initial structure for platform services and application services.

This is the handoff condition into GitOps-managed operation. Bootstrap does not require every platform service to be selected or installed before handoff. After handoff, additional platform services and application services are managed through GitOps.

## Operator inputs

The operator or calling tool provides two conceptual input categories:

1. **Kubernetes access**: a reachable API and credentials that allow applying bootstrap resources.
2. **GitOps source information**: a reference to a Git repository that the GitOps controller will reconcile, including any access credentials required.

These inputs are tool-neutral. The contract does not require a kind-specific, Terraform-specific, Ansible-specific, or bespoke Kubecrate interface.

## GitOps source structure roles

After bootstrap installation hands off to GitOps-managed operation, the Git source must support the following conceptual roles. These are structure roles, not final repository paths:

- **GitOps entrypoint**: the root or bootstrap reference that the GitOps controller watches and reconciles.
- **platform services**: definitions for shared platform capabilities (ingress, certificate management, observability, policy, etc.).
- **application services**: definitions for the workloads that run on the platform.
- **cluster or environment binding**: configuration that binds the GitOps definitions to a specific cluster or environment (target, overlays, values).

Final directory names and repository layout are not decided in this change. They will be resolved by later implementation proposals once the kind-first local path and first installable slice are ready.

## Kind-first local path

The kind-first local path is the first reference path for proving the install flow. It allows early slices to be small and testable on a local Kubernetes cluster without depending on a cloud provider.

Kind is a reference path, not the product interface or provider boundary. The install-flow contract remains cluster-provider agnostic. The same bootstrap installation boundaries, GitOps handoff condition, and structure roles apply regardless of the cluster provider.

## Bootstrap packaging compatibility

The install flow should prefer bootstrap packaging that common Kubernetes automation tools can consume without Kubecrate-specific interfaces.

Helm is the preferred candidate because it is widely compatible with local workflows, Terraform, Ansible, GitOps controllers, and other Kubernetes automation paths.

This is a working assumption and compatibility criterion, not an implemented chart, a Helm-only interface, or a final packaging decision. A later proposal will validate or replace the packaging choice with concrete evidence.

## Non-goals

This install-flow definition explicitly excludes:

- **Cluster creation**. Bootstrap installation starts with a reachable Kubernetes API. Cluster creation tools and workflows are outside this bootstrap installation contract.
- **Runnable manifests**. This document defines the contract. Kubernetes manifests, Helm charts, and other runnable artifacts belong in later implementation changes.
- **Installation scripts**. The contract is tool-neutral. Specific scripts, commands, or CLI interfaces are out of scope.
- **Final repository paths**. The GitOps source structure roles are conceptual. Final directory layout decisions belong in later implementation proposals.
- **Final platform service selection**. The contract defines where platform services fit in the structure. Choosing which platform services to include is out of scope for bootstrap installation.

## Illustrative flow (non-runnable)

The following diagram is illustrative only. It shows the lifecycle stages without defining runnable implementation.

```
Operator or calling tool
    │
    ├── Kubernetes API reachable ✓
    ├── Credentials to apply bootstrap resources ✓
    │
    ▼
┌─────────────────────────────────────────┐
│          BOOTSTRAP INSTALLATION          │
│  (lifecycle phase)                       │
│                                          │
│  • Apply bootstrap resources             │
│  • Install GitOps controller             │
│  • Bind GitOps controller to Git source  │
│  • Establish initial reconciliation      │
│    structure for platform services and   │
│    application services                  │
│                                          │
│  Handoff condition:                      │
│  GitOps controller running, bound to     │
│  Git source, able to reconcile initial   │
│  structure for platform and application  │
│  services                                │
└──────────────┬──────────────────────────┘
               │
               │  Handoff into
               │  GitOps-managed operation
               ▼
┌─────────────────────────────────────────┐
│        GITOPS-MANAGED OPERATION          │
│  (lifecycle phase)                       │
│                                          │
│  Git source structure roles:             │
│  ┌─────────────────────────────────┐     │
│  │ GitOps entrypoint               │     │
│  ├─────────────────────────────────┤     │
│  │ platform services               │     │
│  ├─────────────────────────────────┤     │
│  │ application services            │     │
│  ├─────────────────────────────────┤     │
│  │ cluster / environment binding   │     │
│  └─────────────────────────────────┘     │
│                                          │
│  • Platform services reconciled          │
│    through GitOps                        │
│  • Application services reconciled       │
│    through GitOps                        │
│  • Ongoing management through GitOps     │
└─────────────────────────────────────────┘
```

The handoff does not require a `minimum platform services installed` stage or final platform service selection. After bootstrap installation, the GitOps controller reconciles the structure. Platform services are installed incrementally through GitOps-managed operation, not during bootstrap.
