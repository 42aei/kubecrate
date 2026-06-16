## Why

Kubecrate needs a clear bootstrap installation contract document before adding implementation. The current docs define the vocabulary, but they do not yet specify what `point at a cluster and install` means from the operator point of view or where bootstrap installation hands off to GitOps-managed operation.

## What Changes

- Define the operator-facing meaning of `point at a cluster and install`.
- Define the bootstrap installation start and end boundaries.
- Define the GitOps-managed operation handoff condition.
- Define conceptual GitOps source structure roles for platform services and application services after handoff.
- Document the kind-first local path as the first reference path, not the product boundary.
- Document bootstrap packaging criteria that favor widely consumable Kubernetes tooling, with Helm as the preferred candidate unless a later proposal identifies a concrete incompatibility.
- Add a docs-only bootstrap installation contract document with an illustrative, non-runnable example flow.
- Do not add Kubernetes manifests, installation scripts, or final component selections in this change.

## Capabilities

### New Capabilities

- `bootstrap-install-flow`: Defines the bootstrap installation contract document for bootstrap installation, GitOps handoff, operator inputs, and future-compatible packaging expectations.

### Modified Capabilities

- None.

## Impact

- Adds OpenSpec requirements for the bootstrap installation flow.
- Adds `docs/bootstrap-installation-contract.md` as the bootstrap installation contract document.
- Updates `docs/README.md` and `README.md` so the bootstrap installation contract document is discoverable.
- No runtime code, Kubernetes manifests, install scripts, or platform component choices are introduced.
