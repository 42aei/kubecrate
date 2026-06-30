## Why

Kubecrate needs to define its minimal initial set of GitOps-managed platform services and the source-structure contract that allows those services to be rolled out per-environment for the point at a cluster and install target experience before the first installable slice. The component selection (backlog 0007) and GitOps source shape (backlog 0010) are coupled because the structure contract must support environment-specific, per-service rollout. Addressing them together avoids locking early repository layout or component decisions in isolation from the rollout needs they must serve.

## What Changes

- Define each platform service as a separately targetable GitOps-managed management unit that supports environment-specific rollout and wave-like promotion.
- Define the minimal initial platform services set contract in a planning-safe way: GitOps controller (bootstrap-required for handoff), with any previously discussed External-Secrets Operator candidate selection explicitly treated as superseded by the Flux-first first installable slice and deferred to a later change.
- Define the source-structure contract conceptually: what a management unit must satisfy, what a source layout must express (platform services, application services, environment binding), and what ordering/ownership boundaries must be preserved. Defer the repository boundary question raised by backlog 0010 (one-stop-shop vs template/example repos) to the first installable slice or source-layout implementation.
- Explicitly decide packaging posture: contract-first stance; concrete packaging (Helm chart, Kustomize overlay, or controller wrapper such as Flux/Argo) can be chosen later provided the choice satisfies the management-unit contract.
- Defer the GitOps controller choice unless an OpenSpec instruction for a later change requires it.
- Do not add Kubernetes manifests, installation scripts, or technical skeleton directories. Keep the source-structure contract non-runnable.

## Capabilities

### New Capabilities

- `gitops-component-management`: Defines the minimal GitOps-managed platform service set, the per-service management-unit contract, and the source-structure roles needed for environment-specific rollout.

### Modified Capabilities

- None.

## Impact

- Adds OpenSpec requirements for GitOps component management and source structure.
- Combines backlog items 0007 and 0010 into a single coordinated planning decision.
- No runtime code, Kubernetes manifests, install scripts, or platform component implementations are introduced.
