## ADDED Requirements

### Requirement: Define AI-facing source-of-truth map
Kubecrate SHALL provide concise AI-facing guidance that identifies the authoritative source for project language, architecture framing, bootstrap installation, GitOps-managed operation, the kind-first local path, backlog usage, OpenSpec changes, and existing runtime layout.

#### Scenario: Agent identifies the correct authority before changing docs or runtime files
- **WHEN** an AI agent or contributor needs to change repository content
- **THEN** the guidance identifies which document or OpenSpec change owns the relevant decision area
- **AND** the guidance points to existing concrete runtime paths without inventing new runtime structure

#### Scenario: Source-of-truth map avoids duplicating full documents
- **WHEN** the AI-facing guidance references an existing document
- **THEN** it links or points to that source instead of duplicating the full content of that source

### Requirement: Preserve lightweight backlog-to-OpenSpec classification
Kubecrate SHALL document how AI agents classify backlog items before creating OpenSpec changes while preserving lightweight backlog entries and the required readiness verdicts. This classification SHALL NOT force a separate backlog grooming process when the next action is already clear.

#### Scenario: Proposed backlog item is evaluated before OpenSpec creation
- **WHEN** a backlog item has status `proposed`
- **THEN** the guidance treats it as a candidate for evaluation, not permission to create an OpenSpec change
- **AND** the agent first returns one of: `ready for OpenSpec`, `not ready`, or `unclear`
- **AND** a `ready for OpenSpec` verdict may be followed by creating or expanding the OpenSpec change in the same work when the user asked the agent to proceed

#### Scenario: Underspecified backlog item defaults to unclear
- **WHEN** a backlog item lacks concrete scope or acceptance criteria
- **THEN** the guidance says to return `unclear` and identify the next decision or outcome that needs clarification

### Requirement: Define layered validation guidance for agents
Kubecrate SHALL document validation expectations for AI-assisted changes in layers: docs/planning validation, static manifest rendering, and operational Kubernetes validation for bootstrap installation or GitOps-managed operation.

#### Scenario: OpenSpec changes are validated
- **WHEN** an OpenSpec change is created or updated
- **THEN** the guidance includes running strict OpenSpec validation for that change

#### Scenario: Static rendering is not enough for runtime success claims
- **WHEN** a change applies or reconciles Kubernetes resources through bootstrap installation or GitOps-managed operation
- **THEN** static rendering, schema, or build validation is treated as necessary but not sufficient
- **AND** success requires operational evidence such as intended cluster context, expected resources, controller or workload health, readiness or sync conditions, recent events or logs for blocking errors, and the operator-visible outcome

### Requirement: Keep AI enablement documentation-only
Kubecrate SHALL keep this AI repository enablement change limited to documentation, backlog, and OpenSpec artifacts. It SHALL NOT add Kubernetes manifests, installation scripts, runtime configuration, `.opencode` files, Hermes profiles, kanban setup, skills, MCP configuration, external automation, or empty technical skeleton directories.

#### Scenario: AI enablement avoids runtime and agent-tool configuration changes
- **WHEN** this change is applied
- **THEN** the resulting file changes are limited to documentation, backlog, and OpenSpec artifacts
- **AND** no runtime manifests, install scripts, external automation, or agent-tool configuration files are added or changed

### Requirement: Preserve project vocabulary and two-axis model
Kubecrate SHALL preserve the required project vocabulary and the two-axis model in all AI-facing repository enablement artifacts.

#### Scenario: Required terms stay consistent
- **WHEN** the AI-facing guidance references the project model
- **THEN** it uses the terms platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install without introducing competing terminology

#### Scenario: Lifecycle phase and workload category remain distinct
- **WHEN** the AI-facing guidance describes repository structure or validation expectations
- **THEN** lifecycle phase (`bootstrap installation` or `GitOps-managed operation`) remains distinct from workload category (`platform services` or `application services`)
