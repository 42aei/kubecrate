# GitOps Component Management

This document defines the management-unit contract, the minimal initial set of GitOps-managed platform services, the source-structure contract, and the packaging posture for Kubecrate. It is a durable reference document, not a runnable implementation. No Kubernetes manifests, installation scripts, Helm charts, Kustomize overlays, or technical skeleton directories are introduced here.

This document builds on the [architecture](architecture.md) (two-axis model) and the [bootstrap installation contract](bootstrap-installation-contract.md) (handoff into GitOps-managed operation). The decisions recorded here were made in `openspec/changes/define-gitops-component-management/` and combine backlog items 0007 and 0010.

## Management-unit contract

Each GitOps-managed platform service is a **separately targetable management unit**. A management unit is the smallest independently operated piece of a platform service under GitOps-managed operation.

### Contract requirements

A management unit MUST satisfy all of the following:

#### Independent installation

A management unit can be installed in a target environment without requiring all other platform services in that environment. Installing or updating External-Secrets Operator in staging does not require cert-manager, ingress, or any other platform service to be present or reconciled first.

#### Environment-specific configuration

A management unit accepts environment-specific configuration (values, overlays, or equivalent binding data) without changing the shared definition of the service. The same service definition can target a local kind cluster with one set of binding data and a production cluster with another.

#### No umbrella bundle lock-in

No management unit is locked inside a single umbrella bundle that blocks per-service or per-environment operations. A monochart or monolithic overlay that forces all platform services to deploy or update together violates this contract.

#### Future wave-like promotion

The contract preserves the ability for a management unit to be promoted across environments in a wave-like pattern (for example, local → staging → production) as a later capability. Per-environment targeting and per-environment configuration are the foundation that enables wave-like promotion. The wave-like promotion mechanism itself is deferred to a later change when environment sequencing and gating requirements are clear.

### Why contract-first

The contract is packaging-agnostic. It can be satisfied by a Helm release, a Kustomize overlay, a Flux HelmRelease or Kustomization, an Argo CD Application, or another GitOps controller wrapper, provided the controller support exists. The contract constrains the *behavior* of a management unit, not the packaging format used to express it.

## Minimal initial platform services set

The two-axis model separates lifecycle phase (bootstrap installation or GitOps-managed operation) from workload category (platform services or application services). The initial platform services set follows this model.

### GitOps controller (bootstrap-installed, not a management unit)

The GitOps controller is installed during bootstrap installation because it is required for handoff into GitOps-managed operation. Under this change's contract, the GitOps controller is **not classified as a GitOps-managed management unit**.

The bootstrap-installed controller and supporting bootstrap resources are expected to come under GitOps-managed operation after handoff. Only the concrete mechanics of how those bootstrap resources are brought under GitOps-managed operation are deferred.

The controller choice itself (Flux, Argo CD, or another) is also deferred. See [Deferred decisions](#deferred-decisions).

### External-Secrets Operator (first GitOps-managed platform service)

**External-Secrets Operator (ESO)** is the first GitOps-managed platform service. ESO provides the secret-sync infrastructure that the first installable baseline requires. It is a platform service: the operator supplies the trust material for the backing secret store, and application teams declare which secrets their workloads need through the operator's documented interface.

#### Fake provider for the kind-first local path

For the kind-first local path, the **Fake provider** is the recommended local secret-handling baseline. It requires no external secret store credentials and keeps the local development path simple. The Fake provider is scoped to the kind-first local path only; it is not a production recommendation.

Real providers (AWS Secrets Manager, GCP Secret Manager, Vault, or others) can be introduced later as provider-specific needs arise, without changing the management-unit contract or the source structure.

### Deferred platform services

The following platform services are deferred to later changes. The project posture of minimal over comprehensive applies: start with the smallest set needed to demonstrate a working GitOps-managed lifecycle, and grow only when there is a clear operational reason.

- **Ingress** — deferred. Required before application services can receive external traffic, but not needed for the first GitOps-managed platform service.
- **Certificate management** — deferred. Required before TLS-terminated ingress is available, but not needed for the first installable slice.
- **Observability** — deferred. Required for operational visibility, but not needed to validate the management-unit contract.
- **Policy** — deferred. Required for governance and compliance, but not needed for the first management-unit implementation.

These services are deferred, not excluded. Each can be introduced in a later change when its operational need is clear.

## Source-structure contract

The GitOps source structure must express the conceptual roles needed to support the management-unit contract and environment-specific rollout, building on the roles already defined in the [bootstrap installation contract](bootstrap-installation-contract.md#gitops-source-structure-roles).

### Conceptual roles

| Role | What it expresses |
| --- | --- |
| **GitOps entrypoint** | The reconciled entrypoint that defines what the controller starts from. |
| **platform services** | One management unit per platform service. Each unit carries its own environment binding or references shared binding data. |
| **application services** | One or more units for application workloads (not implemented in this change). |
| **environment binding** | Configuration that binds management units to a target environment. This includes values, overlays, destination settings, or controller-specific binding data. |
| **ordering and ownership boundaries** | A way to keep reconciliation order and responsibility understandable, especially between platform services and environment binding. |

These roles are conceptual. They do not mandate final directory paths, environment directory names, or file-level layouts. The source-structure contract defines *what* must be expressible, not *how* the repository tree is organized.

### Environment binding separation

Environment binding MUST be separable per management unit. A single platform service can be updated in one environment without affecting other environments. This separation is what enables per-environment targeting and the future ability of wave-like promotion.

### Repository boundary deferred

The repository boundary question from backlog 0010 (whether this repository is a one-stop shop or whether template or example repositories hold platform services and application services definitions) is **explicitly deferred to the first installable slice or source-layout implementation change**. The source-structure contract defines conceptual roles only. Whether those roles live in a single repository, separate template repos, or a reference-and-copy model is deferred.

The forcing function for the repository boundary decision is the first change that needs to place runtime files for a concrete management unit. Until then, the conceptual roles are sufficient.

## Packaging posture

Kubecrate adopts a **contract-first** packaging posture. Concrete packaging can be chosen later provided the choice satisfies the management-unit contract.

### Candidate formats

The following packaging formats are identified as candidates that can satisfy the management-unit contract. No single format is selected as final.

| Format | How it satisfies the contract |
| --- | --- |
| **Helm** | A Helm release can be a management unit. Environment-specific values files or `--set` overrides provide binding. |
| **Kustomize** | A Kustomize overlay can be a management unit. Patches and overlays provide environment binding. |
| **Controller wrappers** | Flux HelmRelease or Kustomization objects, or Argo CD Application objects, can wrap either format and provide additional reconciliation features. |

Helm is the preferred candidate for bootstrap packaging (per the bootstrap installation contract), but that preference does not extend to GitOps-managed management units unless a later change validates it.

### Forcing function

The first change that implements a management unit is the forcing function for packaging selection. That change MUST validate that the chosen packaging satisfies the management-unit contract defined here.

## Deferred decisions

The following decisions are explicitly deferred. Each includes the rationale and the forcing function that will resolve it.

| Decision | Rationale | Forcing function |
| --- | --- | --- |
| **GitOps controller choice** (Flux, Argo CD, or another) | The management-unit and source-structure contracts are designed to be compatible with Flux, Argo CD, and other common GitOps controllers. The controller does not need to be named for this contract to be valid. | The first installable slice that implements bootstrap installation with a concrete controller. |
| **Final packaging format** (Helm, Kustomize, or controller wrapper) | The contract-first posture ensures any choice satisfies the management-unit contract. The first management-unit implementation has not yet validated a specific format. | The first change that implements a management unit. |
| **Additional platform services** (ingress, certificate management, observability, policy) | The project posture is minimal over comprehensive. External-Secrets Operator is a sufficient first platform service to validate the contract. Adding more services now would over-scope the first installable slice. | A later change that introduces a specific platform service when its operational need is clear. |
| **Environment-specific directory structure** | Environment-specific structure is deferred until a change needs more than the kind-first local path. The conceptual roles are sufficient for planning. | A later change that introduces multi-environment rollout or environment-specific structure. |

No deferred decision is indefinite or unresolvable. Each has a clear forcing function tied to a concrete future change.

## Non-runnable boundary

This document defines intent and contracts. It does not introduce:

- Kubernetes manifests (Deployments, Services, ConfigMaps, or any other Kubernetes resources)
- Helm charts or Kustomize overlays
- Installation scripts or CLI implementations
- Technical skeleton directories
- Runtime platform component implementations

The first installable slice that implements a management unit will introduce runnable artifacts. This document provides the contract those artifacts must satisfy.
