## Context

Kubecrate's current docs define a two-axis model: lifecycle phase (`bootstrap installation` or `GitOps-managed operation`) and workload category (`platform services` or `application services`). They also state the target experience as `point at a cluster and install`, with a kind-first local path that preserves the long-term goal of cluster-provider agnostic operation.

The missing piece is the install-flow contract. Without it, later implementation work can accidentally collapse cluster creation, bootstrap installation, GitOps setup, platform services, and application services into one vague installer. This change keeps those boundaries explicit before any manifests or scripts are added.

## Goals / Non-Goals

**Goals:**

- Define where Kubecrate bootstrap installation starts and ends.
- Define what an operator or calling tool must provide at the conceptual level.
- Define the handoff into GitOps-managed operation.
- Define conceptual GitOps source structure roles for platform services and application services.
- Preserve kind-first as the first reference path without making kind the product interface.
- Record compatibility criteria for future bootstrap packaging decisions.
- Include an illustrative example flow that shows the lifecycle without creating runnable implementation artifacts.

**Non-Goals:**

- Do not define how clusters are created.
- Do not add Kubernetes manifests, installation scripts, Helm charts, or technical skeleton directories.
- Do not choose the final minimum platform services component set.
- Do not define final repository paths for all GitOps content.
- Do not make Terraform, Cluster API, Crossplane, Ansible, or kind-specific integration artifacts.

## Decisions

### Kubecrate begins at a reachable Kubernetes API

Kubecrate bootstrap installation starts after a conforming Kubernetes API is reachable and the operator or calling tool can provide credentials to apply bootstrap resources.

This keeps cluster creation outside the Kubecrate bootstrap boundary. The kind-first local path can create a local cluster for reference use later, but that is a driver for the contract, not the contract itself.

Alternatives considered:

- Include kind cluster creation in the install-flow contract. Rejected because it would make the first local path look like the product boundary.
- Define separate flows for Terraform, Cluster API, Crossplane, and Ansible. Rejected for this change because it would over-design integrations before the core bootstrap contract exists.

### Bootstrap ends at GitOps control, not at a complete platform

Bootstrap installation is complete when a GitOps controller is running, bound to a Git source, and has an established structure for loading platform services and application services through GitOps-managed operation.

This makes bootstrap a lifecycle phase. It does not create a third workload category and does not require every platform service to be installed before handoff.

Alternatives considered:

- Treat bootstrap as complete only after all selected platform services are installed. Rejected because it blurs bootstrap installation with GitOps-managed operation.
- Treat bootstrap as only controller installation. Rejected because the controller also needs a Git source and initial reconciliation structure before handoff is meaningful.

### Define GitOps structure roles before final paths

This change should define the roles a GitOps source structure must support, not final directory names. The structure must distinguish the GitOps entrypoint, platform services, application services, and cluster or environment binding.

Final paths can be decided by later implementation proposals once the kind-first local path and first installable slice are ready.

Alternatives considered:

- Mandate exact paths now. Rejected because that would prematurely harden implementation details.
- Avoid repository structure discussion entirely. Rejected because handoff into GitOps-managed operation would remain too abstract.

### Prefer widely consumable bootstrap packaging

The install flow should prefer bootstrap packaging that common Kubernetes automation tools can consume without Kubecrate-specific interfaces. Helm is the preferred candidate because it is widely supported by local workflows, Terraform, Ansible, GitOps controllers, and other Kubernetes automation paths.

This is a working assumption and compatibility criterion, not a chart implementation in this change. A later proposal can validate or replace the packaging choice with concrete evidence.

Alternatives considered:

- Create a bespoke Kubecrate installer interface. Rejected because it would be harder for future tooling to adopt.
- Decide all packaging and rendering mechanics now. Rejected because this change is defining the install-flow contract, not building the package.

## Risks / Trade-offs

- [Risk] The proposal remains too abstract to guide implementation. → Mitigation: include an illustrative install-flow document with concrete lifecycle stages and GitOps structure roles.
- [Risk] Helm as preferred candidate is mistaken for a final implementation commitment. → Mitigation: describe it as a working assumption and compatibility criterion to be validated later.
- [Risk] kind-first work later expands the product boundary to include cluster creation. → Mitigation: explicitly state that Kubecrate begins at a reachable Kubernetes API and kind is a reference path.
- [Risk] GitOps structure roles become final paths by implication. → Mitigation: label any example repository shape as illustrative and non-final.
