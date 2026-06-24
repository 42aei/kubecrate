## ADDED Requirements

### Requirement: Helm-driven Flux bootstrap installation
Kubecrate SHALL use a Helm-driven bootstrap installation path for Flux in this first slice. Bootstrap installation SHALL install Flux controllers from the selected chart path, prepare the first Flux desired-state path, and hand off to GitOps-managed operation without introducing a duplicate independent source of truth for Flux configuration.

#### Scenario: Bootstrap execution installs Flux from the chart path and prepares the first desired-state path
- **WHEN** an operator runs bootstrap installation against a prepared kind cluster
- **THEN** bootstrap installation installs Flux controllers from the selected Flux chart path
- **AND** bootstrap installation prepares the same cluster entrypoint path that Flux later reconciles
- **AND** the bootstrap execution path does not embed a duplicate independent copy of Flux manifests

#### Scenario: Helm-driven bootstrap requires local Helm tooling
- **WHEN** the bootstrap installation interface is defined for a Flux chart path
- **THEN** local `helm` is required for that bootstrap installation path
- **AND** the operator does not need a separate platform service credential projection controller to complete the first slice bootstrap contract

### Requirement: Flux SSH deploy-key generation and registration
Kubecrate SHALL use `flux2-sync` SSH deploy-key generation for the first Git source contract in this slice. Bootstrap installation SHALL create `Secret/flux-system` in namespace `flux-system`, keep the generated private key material in-cluster, and expose operator retrieval of the generated public key from `identity.pub` for deploy-key registration with the Git provider.

#### Scenario: Flux sync secret is created during bootstrap
- **WHEN** bootstrap installation executes the `flux2-sync` contract in SSH mode
- **THEN** `Secret/flux-system` exists in namespace `flux-system`
- **AND** the Secret contains generated SSH identity material for the Flux Git source contract

#### Scenario: Operator retrieves the generated public key from identity.pub
- **WHEN** the operator needs to register repository access for Flux
- **THEN** the generated public key is retrievable from `Secret/flux-system` field `identity.pub`
- **AND** bootstrap output or operator guidance identifies that field as the source of truth for deploy-key registration

#### Scenario: Deploy-key registration happens before Flux source readiness
- **WHEN** the generated public key has not yet been registered with the Git provider as a deploy key
- **THEN** `GitRepository/flux-system` SHALL NOT be considered ready for GitOps-managed operation
- **AND** operator registration of that deploy key is required before Flux source readiness is expected

### Requirement: Platform services namespaces use the core prefix
Kubecrate SHALL name dedicated Kubernetes namespaces for platform services with the `core-<service-name>` pattern. This first slice SHALL keep Flux in `flux-system` as an explicit tool-specific exception for the GitOps controller bootstrap or self-management path and SHALL NOT introduce `core-flux` for Flux in this slice.

#### Scenario: Dedicated platform services keep the core namespace rule
- **WHEN** a future platform service in this model needs a dedicated namespace
- **THEN** that namespace uses the `core-<service-name>` pattern

#### Scenario: Flux keeps the explicit namespace exception
- **WHEN** the first installable slice installs or reconciles Flux
- **THEN** Flux controller, sync, and self-management resources use namespace `flux-system`
- **AND** the first slice does not use `core-flux` for Flux

### Requirement: External-Secrets Operator is deferred outside this first slice
Kubecrate SHALL NOT require External-Secrets Operator for bootstrap installation or GitOps-managed operation acceptance in this first slice. External-Secrets Operator remains deferred platform services work outside this slice rather than a rejected long-term option.

#### Scenario: First-slice acceptance does not depend on External-Secrets Operator
- **WHEN** the first installable slice scope is evaluated
- **THEN** bootstrap installation and GitOps-managed operation acceptance do not require External-Secrets Operator
- **AND** any later External-Secrets Operator work is treated as deferred follow-up scope

### Requirement: Flux self-management handoff
Bootstrap installation SHALL hand off Flux to self-management after bootstrap installation. Bootstrap installation SHALL apply or reference the same Flux desired-state path that Flux later reconciles. There SHALL NOT be duplicate independent Flux definitions under bootstrap installation and the GitOps desired-state path. Bootstrap installation is a loader or reference, not a second source of truth for Flux configuration.

#### Scenario: Bootstrap applies the same path Flux reconciles
- **WHEN** bootstrap installation applies the Flux desired-state path
- **THEN** the applied path is the same path Flux later reconciles from the cluster entrypoint
- **AND** no separate Flux definition exists exclusively under bootstrap installation

#### Scenario: Flux becomes self-managing after handoff
- **WHEN** Flux starts and reconciles the desired-state path
- **THEN** Flux manages its own configuration, including any future changes to Flux resources in the desired-state path
- **AND** the operator does not need to re-run bootstrap installation to update Flux configuration

#### Scenario: Flux Git source uses SSH remote and current branch
- **WHEN** Flux is configured to reconcile this repository
- **THEN** the Flux `GitRepository` resource points to this repository's SSH remote URL and the current implementation branch
- **AND** Git credentials are provided by generated SSH identity material stored in `Secret/flux-system`
- **AND** validation requires a commit and push to the implementation branch for Flux to detect and reconcile changes
- **AND** local Git server alternatives are secondary and out of the default path for this slice

#### Scenario: Deploy-key contract is limited to generated SSH identity material
- **WHEN** the repository's Git authentication choice is documented for this slice
- **THEN** the default path is generated SSH deploy-key material for `flux2-sync`
- **AND** operator registration of the generated public key is part of the first-slice bootstrap contract

### Requirement: Concrete runtime layout
Kubecrate SHALL place the first concrete runtime files under a layout that preserves the two-axis model while allowing cluster-owned validation material to live directly in a concrete cluster path. Each concrete cluster SHALL have an entrypoint at `clusters/<cluster>/entrypoint/` as the first GitOps reconciliation root. The first concrete cluster SHALL be `kind-dev-misc-local`. The first validation proof under this layout SHALL be `kubecrate-reconciliation-marker`, and it SHALL live in a concrete cluster path because it is not a platform service or application service. Real platform services SHALL use `platform-services/<service>/base/` with cluster-specific binding under `clusters/<cluster>/platform-services/<service>/` immediately when introduced. Real application services SHALL use `application-services/<service>/base/` with cluster-specific binding under `clusters/<cluster>/application-services/<service>/` when introduced.

#### Scenario: Reusable service definitions are separate from cluster binding
- **WHEN** a platform service or application service is defined
- **THEN** its reusable base definition lives under the workload-category path for that service
- **AND** cluster-specific enablement, configuration, and version binding live under the corresponding cluster workload-category path

#### Scenario: Temporary cluster-local platform service implementations are forbidden
- **WHEN** a real platform service is introduced
- **THEN** it is not kept only in a cluster-local bootstrap directory
- **AND** any exception requires an approved change with an explicit removal plan

#### Scenario: Reconciliation marker and namespace manifest live directly under the concrete cluster path
- **WHEN** the runtime layout is populated for the first installable slice
- **THEN** `clusters/kind-dev-misc-local/entrypoint/` contains the first GitOps reconciliation root
- **AND** `clusters/kind-dev-misc-local/entrypoint/kubecrate-system-namespace.yaml` creates namespace `kubecrate-system` directly in the entrypoint
- **AND** `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml` contains `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` with version X
- **AND** no empty workload-category skeleton directories are required just to host the marker

#### Scenario: Concrete cluster follows naming convention
- **WHEN** the first concrete cluster is created
- **THEN** it follows the `<provider>-<environment>-<workload>-<location>` naming convention
- **AND** the first concrete cluster name is `kind-dev-misc-local`

#### Scenario: Cluster entrypoint is the GitOps reconciliation root
- **WHEN** Flux reconciles a cluster
- **THEN** it starts from `clusters/<cluster>/entrypoint/` as the first reconciliation root

### Requirement: Kind validation plumbing
Kubecrate SHALL provide repository-owned kind validation plumbing for the kind-first local path. This plumbing SHALL include a kind cluster configuration, prerequisite documentation or checks, setup commands such as Make targets or equivalents, teardown/recreate expectations, and evidence commands. Kind cluster creation and preparation SHALL remain outside bootstrap installation. Bootstrap installation SHALL start only after kind plumbing delivers a reachable Kubernetes API with usable credentials.

#### Scenario: Kind plumbing is repository-owned
- **WHEN** an operator prepares the kind-first local path
- **THEN** the repository provides kind config, prerequisite checks, setup commands, teardown/recreate expectations, and evidence commands
- **AND** the operator does not need to invent ad-hoc kind cluster preparation

#### Scenario: Kind cluster creation is not bootstrap installation
- **WHEN** kind plumbing creates a cluster
- **THEN** the cluster creation step is separate from bootstrap installation
- **AND** `point at a cluster and install` expects an already reachable Kubernetes API with usable credentials

### Requirement: Tracer bullet validation proves GitOps-managed update
Kubecrate SHALL include a tracer bullet that proves GitOps-managed operation performs an update using `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system`, a Flux-managed validation marker/config proof rather than a platform service or application service. The validation SHALL demonstrate: baseline reconciliation of `kubecrate-reconciliation-marker` at version X (`v0.1.0` or equivalent Git-tracked config value), a Git-managed version bump to version Y (`v0.2.0`), and Flux reconciliation evidence confirming the update. Version X→Y SHALL be defined via a Git-managed config value in `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml` with evidence commands such as `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` before and after the change. Validation SHALL be operational and evidence-command based. Static manifest rendering or build validation SHALL be treated as necessary but not sufficient after bootstrap installation applies resources and Flux reconciles them. Validation SHALL confirm the intended cluster context, expected resources, controller and workload health, readiness, or sync conditions, recent events or logs for blocking errors, and the operator-visible outcome. If health is failing or unclear, this slice SHALL NOT claim success until bounded, symptom-driven diagnosis identifies the blocking layer. Authorization or RBAC checks MAY be used when evidence points there, but SHALL NOT be a mandatory per-ServiceAccount validation step for every resource.

#### Scenario: Baseline reconcile succeeds with kubecrate-reconciliation-marker at version X
- **WHEN** bootstrap installation completes and Flux has reconciled
- **THEN** evidence confirms Flux is running, `Secret/flux-system` contains generated sync identity material, and `ConfigMap/kubecrate-reconciliation-marker` is present in namespace `kubecrate-system` at version X (`v0.1.0`)
- **AND** the evidence command `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` returns the expected value for version X
- **AND** validation confirms the intended cluster context, expected resources, relevant health, readiness, or sync conditions, and no blocking errors in recent events or logs

#### Scenario: Git-managed change triggers Flux update of kubecrate-reconciliation-marker
- **WHEN** the operator commits a version bump for `kubecrate-reconciliation-marker` from `v0.1.0` to `v0.2.0` in `clusters/kind-dev-misc-local/entrypoint/kubecrate-reconciliation-marker.yaml` and pushes to the implementation branch
- **THEN** Flux detects the change, reconciles, and `ConfigMap/kubecrate-reconciliation-marker` in namespace `kubecrate-system` reports version Y
- **AND** the evidence command `kubectl get configmap kubecrate-reconciliation-marker -n kubecrate-system -o jsonpath='{.data.version}'` returns the expected value for version Y
- **AND** evidence captures the before/after version value via the evidence command and Flux reconciliation status confirming the update
- **AND** validation checks deeper than render output remain symptom-driven, using layers such as events, logs, networking, or authorization only when the observed evidence points there

### Requirement: Preserve project vocabulary and two-axis model
Kubecrate SHALL preserve the required project vocabulary and the two-axis architecture model in all runtime files, documentation, and validation commands of this slice.

#### Scenario: Required terms are used consistently
- **WHEN** any artifact in this slice references the project model
- **THEN** it uses the terms `platform services`, `application services`, `bootstrap installation`, `GitOps-managed operation`, `kind-first local path`, and `point at a cluster and install` without introducing competing terminology

#### Scenario: Lifecycle and workload axes remain distinct
- **WHEN** the slice describes services and their management
- **THEN** lifecycle phase (`bootstrap installation` or `GitOps-managed operation`) is described separately from workload category (`platform services` or `application services`)

### Requirement: Explicit non-goals for this slice
Kubecrate SHALL exclude ingress, certificate management, observability, policy, and wave-like promotion policy/gating from this slice. Environment-specific configuration and the future capability of wave-like promotion SHALL be preserved as capabilities but SHALL NOT be implemented as policy or gating in this slice.

#### Scenario: Deferred services are excluded
- **WHEN** the slice scope is evaluated
- **THEN** ingress, certificate management, observability, and policy platform services are not installed, configured, or required
- **AND** the slice does not depend on any of these services to function

#### Scenario: Environment-specific configuration is preserved
- **WHEN** cluster binding is defined for `kind-dev-misc-local`
- **THEN** the binding model supports environment-specific configuration as a capability
- **AND** wave-like promotion policy and gating mechanics are not implemented

### Requirement: Backlog frontmatter hygiene
Kubecrate SHALL update the `docs/backlog/0008-create-first-installable-slice.md` frontmatter status from `proposed` to `started` with a note referencing this OpenSpec change.

#### Scenario: Backlog status reflects OpenSpec creation
- **WHEN** this change's proposal is accepted
- **THEN** the backlog item `0008-create-first-installable-slice.md` frontmatter status is `started`
- **AND** the backlog item references `openspec/changes/create-first-installable-slice/` as the active planning artifact
