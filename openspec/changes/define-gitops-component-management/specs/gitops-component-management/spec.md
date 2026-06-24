## ADDED Requirements

### Requirement: Define management-unit contract
Kubecrate SHALL define each GitOps-managed platform service as a separately targetable management unit (or service unit) that supports independent installation, environment-specific configuration, and wave-like promotion across environments as a firm preserved capability.

#### Scenario: Management unit is independently targetable
- **WHEN** a platform service is defined as a management unit
- **THEN** it can be installed in a target environment without requiring all other platform services in that environment

#### Scenario: Management unit supports environment-specific configuration
- **WHEN** a management unit is deployed to an environment
- **THEN** it accepts environment-specific configuration (values, overlays, or equivalent binding data) without changing the shared definition of the service

#### Scenario: Management unit avoids umbrella bundle lock-in
- **WHEN** the platform services structure is defined
- **THEN** no management unit is locked inside a single umbrella bundle that blocks per-service or per-environment operations

#### Scenario: Management unit supports future wave-like promotion
- **WHEN** a management unit's rollout model is defined
- **THEN** the contract preserves wave-like promotion as a firm capability, allowing a management unit to be promoted across environments in a wave-like pattern (e.g., local → staging → production)
- **AND** per-environment targeting and configuration are supported as the foundation that enables wave-like promotion
- **AND** the specific promotion mechanism (environment sequencing, gating) is deferred to a later change, but the capability is a preserved design requirement

#### Scenario: Management unit ordering through source-structure conventions
- **WHEN** management units have dependencies on each other
- **THEN** ordering and dependencies are expressed through simple source-structure conventions (layer or name ordering, similar in spirit to systemd-style naming), not through custom dependency metadata files, unit descriptors, generated graphs, or bespoke dependency models
- **AND** the first implementation that needs ordering must show how the chosen GitOps controller makes dependency order clear and enforceable

### Requirement: Define minimal initial platform services set
Kubecrate SHALL define the minimal initial set of platform services for the first GitOps-managed installable slice.

#### Scenario: GitOps controller is bootstrap-installed, not a management unit
- **WHEN** the initial platform services set is described
- **THEN** the GitOps controller is identified as bootstrap-required for handoff into GitOps-managed operation
- **AND** the controller is not classified as a GitOps-managed management unit under this change's contract
- **AND** the bootstrap-installed controller and supporting resources are expected to come under GitOps-managed operation after handoff; only the concrete mechanics of how are deferred

#### Scenario: Bootstrap trust inputs are operator-provided
- **WHEN** bootstrap-required services need secret or trust material to start
- **THEN** bootstrap installation is responsible for receiving and collecting operator-provided secret and trust inputs
- **AND** this includes the GitOps controller, any platform service later classified as bootstrap-required, and any other bootstrap-required service
- **AND** bootstrap-required services may be installed during bootstrap and then handed off to GitOps-managed operation

#### Scenario: First GitOps-managed platform service selection is deferred from this planning change
- **WHEN** the initial platform services set is described
- **THEN** this planning change preserves the management-unit contract without requiring a specific first GitOps-managed platform service implementation
- **AND** any earlier External-Secrets Operator with Fake provider candidate is treated as superseded by the Flux-first first installable slice baseline and deferred to a separate future change with its own acceptance criteria

#### Scenario: Additional platform services are deferred
- **WHEN** the initial platform services set is documented
- **THEN** ingress, certificate management, observability, and policy platform services are deferred to later changes unless a clear operational reason requires them earlier

### Requirement: Define source-structure contract
Kubecrate SHALL define the conceptual roles a GitOps source structure must express to support the management-unit contract and environment-specific rollout.

#### Scenario: Source structure expresses platform services as separate management units
- **WHEN** the source structure is defined
- **THEN** it distinguishes one management unit per platform service, each carrying or referencing its own environment binding

#### Scenario: Environment binding is separable per management unit
- **WHEN** environment binding is expressed in the source structure
- **THEN** binding configuration is separable per management unit so a single service can be updated in one environment without affecting others

#### Scenario: Source-structure roles are conceptual, not final paths
- **WHEN** the source-structure contract is described
- **THEN** it defines roles (GitOps entrypoint, platform services, application services, environment binding, ordering and ownership boundaries) without mandating final directory paths or file names

#### Scenario: Repository boundary is deferred
- **WHEN** the source-structure contract is defined
- **THEN** the contract does not decide whether this repository is a one-stop shop or whether template or example repositories hold definitions
- **AND** the final repository boundary is deferred to the first installable slice or source-layout implementation change

### Requirement: Preserve packaging-agnostic stance
Kubecrate SHALL adopt a contract-first packaging posture where concrete packaging (Helm chart, Kustomize overlay, or controller wrapper) can be chosen later provided the choice satisfies the management-unit contract.

#### Scenario: Packaging choice is deferred
- **WHEN** the packaging posture is documented
- **THEN** Helm, Kustomize, and controller wrappers are identified as candidates that can satisfy the management-unit contract, but no single format is selected as final
- **AND** controller-specific objects (Argo CD Applications, Flux Kustomizations, etc.) are treated as replaceable adapters for the selected GitOps controller, not as the portable contract
- **AND** bootstrap installation must not depend on a GitOps provider to install the controller itself

#### Scenario: First implementation validates packaging
- **WHEN** a later change implements a management unit
- **THEN** that change MUST validate that the chosen packaging satisfies the management-unit contract defined in this change

### Requirement: Preserve project vocabulary and two-axis model
Kubecrate SHALL preserve the required project vocabulary and the two-axis architecture model in all artifacts of this change.

#### Scenario: Lifecycle phase and workload category remain distinct
- **WHEN** the management-unit contract and minimal component set are described
- **THEN** platform services and application services are described as workload categories, and bootstrap installation and GitOps-managed operation are described as lifecycle phases

#### Scenario: Required project terms are used consistently
- **WHEN** any artifact in this change references the project model
- **THEN** it uses the terms platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install without introducing competing terminology

### Requirement: Keep change non-runnable
Kubecrate SHALL NOT add Kubernetes manifests, installation scripts, Helm charts, Kustomize overlays, technical skeleton directories, or runtime platform component implementations in this change.

#### Scenario: Definition work avoids implementation artifacts
- **WHEN** this change is applied
- **THEN** it adds or updates planning artifacts and documentation without adding runtime bootstrap or platform service implementation artifacts
