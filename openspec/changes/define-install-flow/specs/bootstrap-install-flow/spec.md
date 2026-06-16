## ADDED Requirements

### Requirement: Define bootstrap installation boundary
Kubecrate SHALL define bootstrap installation as starting after a Kubernetes API is reachable, the operator or calling tool can provide credentials and permissions to apply bootstrap resources, and any pre-existing resources that bootstrap installation will own do not conflict with those bootstrap-owned resources.

#### Scenario: Cluster creation remains outside bootstrap boundary
- **WHEN** the install flow describes the beginning of bootstrap installation
- **THEN** it identifies a reachable Kubernetes API, usable permissions, and non-conflicting bootstrap-owned resources as prerequisites instead of describing cluster creation as part of Kubecrate bootstrap installation

### Requirement: Define GitOps handoff condition
Kubecrate SHALL define bootstrap installation as complete only when a GitOps controller is running, bound to a Git source, and able to reconcile an established structure for platform services and application services.

#### Scenario: Bootstrap handoff is meaningful
- **WHEN** the install flow describes the end of bootstrap installation
- **THEN** it identifies a running GitOps controller, Git source binding, and initial reconciliation structure as the handoff condition into GitOps-managed operation

### Requirement: Preserve lifecycle and workload category axes
Kubecrate SHALL describe bootstrap installation and GitOps-managed operation as lifecycle phases, and platform services and application services as workload categories.

#### Scenario: Bootstrap is not a service category
- **WHEN** the install flow describes services installed before and after handoff
- **THEN** it treats bootstrap as a lifecycle phase rather than a third workload category

### Requirement: Identify operator input categories
Kubecrate SHALL identify the conceptual input categories required for installation without requiring a specific script, command, or automation tool shape.

#### Scenario: Inputs are tool-neutral
- **WHEN** the install flow lists operator or calling-tool inputs
- **THEN** it includes Kubernetes access and GitOps source information without requiring a kind-specific, Terraform-specific, Ansible-specific, or bespoke Kubecrate interface

### Requirement: Define GitOps source structure roles
Kubecrate SHALL define the roles that the GitOps source structure must support for handoff into GitOps-managed operation.

#### Scenario: Structure roles are clear without final paths
- **WHEN** the install flow describes the GitOps source structure
- **THEN** it distinguishes the GitOps entrypoint, platform services, application services, and cluster or environment binding without mandating final repository paths

### Requirement: Preserve kind-first as reference path
Kubecrate SHALL preserve a cluster-provider agnostic bootstrap boundary and, when it references the kind-first local path, describe it as a separate reference validation path rather than the product interface or cluster-provider boundary.

#### Scenario: Kind does not define the contract
- **WHEN** the install flow references kind
- **THEN** it explains kind as a separate local reference validation path while preserving a cluster-provider agnostic bootstrap boundary

### Requirement: Prefer compatible bootstrap packaging
Kubecrate SHALL define bootstrap packaging criteria that prefer widely consumable Kubernetes tooling and avoid bespoke interfaces without clear operational reason.

#### Scenario: Helm is documented as preferred candidate
- **WHEN** the install flow discusses bootstrap packaging direction
- **THEN** it identifies Helm as the preferred candidate due to broad compatibility while leaving final implementation validation to a later proposal

### Requirement: Keep bootstrap installation contract document docs-only
Kubecrate SHALL keep this bootstrap installation contract document docs-only and SHALL NOT add Kubernetes manifests, installation scripts, Helm charts, or final component selections.

#### Scenario: Definition work avoids implementation artifacts
- **WHEN** the bootstrap installation contract document change is applied
- **THEN** it adds or updates documentation without adding runtime bootstrap implementation artifacts
