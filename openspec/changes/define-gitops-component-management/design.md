## Context

Backlog items 0007 (choose minimal component set) and 0010 (define GitOps source structure) are coupled. Picking components without a rollout contract risks an umbrella bundle that blocks per-service iteration. Defining the source structure without naming services leaves the first installable slice too abstract. This change resolves both together so the management-unit contract and the minimal component set reinforce each other.

The bootstrap installation contract already defines where platform services fit: after handoff into GitOps-managed operation. This change fills in the next layer: which platform services come first, and how the GitOps source expresses them as separately targetable units.

## Goals / Non-Goals

**Goals:**

- Define each platform service as a separately targetable GitOps-managed management unit.
- Define a management-unit contract that supports environment-specific rollout (change one platform service in one environment before wider rollout) and preserves the option of wave-like promotion later.
- Select the minimal initial platform services set for the first installable slice.
- Define the source-structure contract conceptually: what a management unit must express, what the source layout must distinguish, and what ordering/ownership boundaries must be preserved.
- Decide packaging posture: contract-first; concrete packaging can be chosen later.
- Explicitly record which decisions are deferred and why.

**Non-Goals:**

- Do not add Kubernetes manifests, Helm charts, Kustomize overlays, installation scripts, or technical skeleton directories.
- Do not pick a final GitOps controller.
- Do not pick a final packaging format (Helm vs Kustomize) beyond the contract posture.
- Do not define application services or final environment directory names.
- Do not expand the bootstrap installation contract.

## Decisions

### Combine backlog 0007 and 0010

Component selection and GitOps source shape are coupled by environment rollout needs. An umbrella bundle that installs everything together blocks per-service, per-environment iteration. A source structure without named services cannot guide the first installable slice. This change resolves both together.

Alternatives considered:

- Handle each backlog item separately. Rejected because the decisions each item needs are interdependent.
- Defer component selection entirely to a later change. Rejected because a concrete minimal set is needed now to validate the management-unit contract.

### Management-unit contract: per-service, per-environment targetable

Each platform service SHALL be a separately targetable GitOps-managed management unit. A management unit, or service unit, is one separately targetable GitOps-managed platform service. A management unit MUST support:

- independent installation in a target environment without requiring all other platform services in that environment
- environment-specific configuration (values, overlays, or equivalent binding data)
- wave-like promotion across environments as a firm preserved capability (e.g., local → staging → production)
- dependency ordering through simple source-structure conventions (layer or name ordering, similar in spirit to systemd-style naming), not through custom dependency metadata files, unit descriptors, generated graphs, or bespoke dependency models

A management unit MUST NOT be locked inside a single indivisible umbrella bundle that blocks per-service or per-environment operations. Dependency orchestration between genuinely dependent services is allowed; forcing unrelated services into an indivisible bundle is not.

Independent targeting does not mean dependency-free. Dependencies between services are expected and are expressed through source-structure conventions. The first implementation that needs ordering must show how the chosen GitOps controller makes dependency order clear and enforceable.

This contract is packaging-agnostic. It can be satisfied by a Helm release, a Kustomize overlay, a Flux HelmRelease/Kustomization, an Argo CD Application, or another GitOps controller wrapper, provided the controller support exists.

Alternatives considered:

- Define a single umbrella chart or monolithic bundle. Rejected because it blocks the environment-specific rollout that the project direction requires.
- Define the management unit as a Helm chart only. Rejected because it couples the contract to one packaging format before the first installable slice validates a concrete choice.

### Minimal initial platform services set

The first installable slice requires bootstrap installation to hand off into GitOps-managed operation. After handoff, the minimal initial set distinguishes the bootstrap-required controller from the first GitOps-managed platform service:

**Bootstrap-required (installed during bootstrap, not as management units under this change):**

- **GitOps controller** — installed during bootstrap installation (not as a GitOps-managed unit) because it is required for handoff. This change decides the controller is bootstrap-required for handoff into GitOps-managed operation. Consistent with the kind-local-workflow authority, the bootstrap-installed GitOps controller and supporting bootstrap resources are expected to come under GitOps-managed operation after handoff. This change defers only the concrete implementation details of how those bootstrap resources are brought under GitOps-managed operation.

  Bootstrap installation is responsible for receiving and collecting operator-provided secret and trust inputs needed to start bootstrap-required services. This includes the GitOps controller, External-Secrets Operator if ESO is bootstrap-required, and any other bootstrap-required service. Bootstrap-required services may be installed during bootstrap and then handed off to GitOps-managed operation. This design states the input rule without prematurely classifying every service.

**First GitOps-managed platform service:**

- **External-Secrets Operator (ESO)** — the first GitOps-managed platform service under the management-unit contract defined in this change. ESO provides the secret-sync infrastructure that the first installable baseline requires.

External-Secrets Operator is a platform service under the project's two-axis model. The operator provides the trust material for the backing secret store; application teams declare which secrets their workloads need through the operator's documented interface.

For the kind-first local path, the Fake provider is the recommended local secret-handling baseline because it requires no external secret store credentials and keeps the local development path simple. Real providers (AWS Secrets Manager, GCP Secret Manager, Vault, etc.) can be introduced later as provider-specific needs arise, without changing the management-unit contract or the source structure.

Additional platform services (ingress, certificate management, observability, policy) are deferred until later changes. The project posture of minimal over comprehensive applies: start with the smallest set of platform services needed to demonstrate a working GitOps-managed lifecycle, and grow only when there is a clear operational reason.

Alternatives considered:

- Select ingress, cert-manager, or observability as first platform services. Rejected for this change because secret handling is a more foundational platform capability for the first working slice, and selecting multiple services at once would over-scope the first installable slice.
- Defer ESO selection to a later change. Rejected because the management-unit contract needs at least one concrete platform service to validate the per-service, per-environment rollout model.
- Require a real secret store provider from the start. Rejected because it adds external dependencies to the kind-first local path, contradicting the goal of a simple local reference workflow.

### Source-structure contract: conceptual roles

The GitOps source structure SHALL express these conceptual roles, building on the roles already defined in the bootstrap installation contract:

| Role | What it expresses for this change |
| --- | --- |
| **GitOps entrypoint** | The reconciled entrypoint that defines what the controller starts from. |
| **platform services** | One management unit per platform service. Each unit carries its own environment binding or references shared binding data. |
| **application services** | One or more units for application workloads (not implemented in this change). |
| **environment binding** | Configuration that binds management units to a target environment, such as values, overlays, destination settings, or controller-specific binding data. Environment binding MUST be separable per management unit so a single service can be updated in one environment without affecting others. |
| **ordering and ownership boundaries** | A way to keep reconciliation order and responsibility understandable, especially between platform services and environment binding. |

These are roles, not final directory paths or file names. The source-structure contract does not require a particular directory layout, only that the structure can express these roles and satisfy the management-unit contract.

Alternatives considered:

- Define final directory names and repository layout now. Rejected because environment-specific structure is deferred until a change needs more than the kind-first local path.
- Avoid source-structure discussion beyond the bootstrap installation contract. Rejected because the management-unit contract requires source-structure roles to define what a separately targetable unit means in practice.

### Repository boundary: deferred to first installable slice

Backlog 0010 raises the question of whether this repository is a one-stop shop or whether template or example repositories hold platform services and application services definitions. This change does not decide the final repository boundary. The source-structure contract defines conceptual roles only. Whether those roles live in a single repository, separate template repos, or a reference-and-copy model is deferred.

The forcing function is the source-layout implementation change that backlog 0010 itself identifies as its resolution point. Until a concrete slice needs to place runtime files, the repository boundary question has no operational cost to resolve. This change ensures the conceptual roles are defined so that any boundary decision made later can satisfy them.

This disposition is consistent with the bootstrap installation contract, which already records "repository boundaries" as a deferred decision.

Alternatives considered:

- Decide the repository boundary in this change. Rejected because the project has no runtime files yet and the boundary decision would be speculative without a concrete source layout to validate.
- Leave the question entirely unaddressed. Rejected because backlog 0010 explicitly raises it and the reader should know this change considered and deferred it.

### Packaging posture: contract-first, concrete later

Helm and Kustomize are the two most common packaging patterns in GitOps-managed Kubernetes environments. Both can satisfy the management-unit contract:

- **Helm**: A Helm release can be a management unit. Environment-specific values files or `--set` overrides provide binding.
- **Kustomize**: A Kustomize overlay can be a management unit. Patches and overlays provide environment binding.
- **Controller wrappers**: Flux HelmRelease/Kustomization or Argo CD Application objects can wrap either and provide additional reconciliation features. Controller-specific objects are replaceable adapters for the selected GitOps controller, not the portable contract. The durable expression of a management unit must remain separable from any particular controller.

The contract does not require Helm, Kustomize, or any specific wrapper today. The decision posture is:

1. The management-unit contract is the binding constraint. Any packaging choice made later MUST satisfy it.
2. Helm is the current preferred candidate for bootstrap packaging (per the bootstrap installation contract), but that preference does not extend to GitOps-managed management units unless a later change validates it.
3. The first installable slice that implements a management unit will be the forcing function that selects a concrete packaging approach.
4. Bootstrap installation must not depend on a GitOps provider to install the controller itself.

This keeps the contract stable while allowing implementation to choose the right packaging for the first concrete use case.

Alternatives considered:

- Choose Helm for everything now. Rejected because the first management-unit implementation has not yet validated Helm as the right choice for GitOps-managed platform services.
- Choose Kustomize for everything now. Rejected for the same reason: the contract should not lock packaging before the first implementation validates it.

### GitOps controller choice: deferred

The GitOps controller choice (Flux vs Argo CD vs another) is deferred. The bootstrap installation contract requires a GitOps controller for handoff but does not name one. This change does not add new reasons to pick a controller now. The management-unit contract and source-structure contract are designed to be compatible with Flux, Argo CD, and other common GitOps controllers.

The forcing function for a controller choice is the first installable slice that implements bootstrap installation with a concrete controller. That decision belongs in the change that creates the bootstrap implementation, not in this planning change.

## Risks / Trade-offs

- [Risk] External-Secrets Operator with only the Fake provider may be insufficient when real secret store credentials are needed. → Mitigation: the Fake provider keeps the kind-first local path simple and requires no external secret store credentials. Real providers are deferred until a later change that introduces a concrete secret store need.
- [Risk] The management-unit contract is too abstract to guide the first implementation. → Mitigation: include concrete acceptance criteria in the spec that any implementation MUST satisfy.
- [Risk] Contract-first packaging posture leads to indecision that blocks implementation. → Mitigation: the first management-unit implementation change is the forcing function; this change documents the contract so the implementation change has clear constraints.
- [Risk] The Fake provider for ESO is mistaken for a production recommendation. → Mitigation: explicitly scope Fake to the kind-first local path as the local secret-handling baseline; note that real providers are introduced later.
