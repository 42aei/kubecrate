## ADDED Requirements

### Requirement: Kustomize-first bootstrap installation
Kubecrate SHALL use a Kustomize-first bootstrap installation path, applying bootstrap resources via `kubectl apply -k` or a thin equivalent wrapper. Bootstrap installation SHALL NOT require Helm as the bootstrap packaging interface.

#### Scenario: Bootstrap entrypoint is a Kustomize overlay
- **WHEN** an operator runs bootstrap installation against a prepared kind cluster
- **THEN** bootstrap installation applies a Kustomize overlay directory that references ESO, Seed Secrets, and the Flux desired-state path
- **AND** the bootstrap overlay does not embed a duplicate independent copy of Flux manifests

#### Scenario: Helm is not required for bootstrap
- **WHEN** the bootstrap installation interface is defined
- **THEN** Helm is not the bootstrap packaging interface, and the operator is not required to install Helm or run `helm install` to complete bootstrap installation

### Requirement: ESO is bootstrap-critical and installed before Flux
Kubecrate SHALL install External-Secrets Operator during bootstrap installation, before Flux, so Flux can consume ESO-projected Git credentials. ESO SHALL be bootstrap-critical for this slice and SHALL NOT be a GitOps-managed management unit.

#### Scenario: ESO runs before Flux
- **WHEN** bootstrap installation executes
- **THEN** ESO is installed and running before Flux controller starts
- **AND** Flux can reference ESO-projected credentials for Git source access

#### Scenario: ESO is not GitOps-managed in this slice
- **WHEN** the platform services model is evaluated
- **THEN** ESO is classified as bootstrap-critical for this slice, not as a GitOps-managed management unit

### Requirement: Seed Secrets projection via ESO Kubernetes provider
Kubecrate SHALL use Seed Secrets as the operator-provided local input path. Only `.env.example` with placeholder values and usage documentation SHALL be committed. The real `.env` file SHALL be in `.gitignore`. Bootstrap installation SHALL materialize one Secret named `seed-secrets` in the ESO namespace via a thin wrapper that reads the current supported keys from `.env` and ignores legacy local keys. ESO SHALL project secrets from `seed-secrets` using the Kubernetes provider or an equivalent local provider that can read a bootstrap-created Kubernetes Secret. The Fake provider SHALL NOT be used for Seed Secrets projection because it does not read the `seed-secrets` Secret.

#### Scenario: Seed Secrets Secret is created during bootstrap
- **WHEN** bootstrap installation executes
- **THEN** a Kubernetes Secret named `seed-secrets` is created in the ESO namespace containing the current supported operator-provided credential keys via the documented wrapper
- **AND** no real `.env` file containing credentials is committed to the repository; only `.env.example` with placeholder values is committed

#### Scenario: Seed Secrets example file is committed, real env is ignored
- **WHEN** the repository is examined
- **THEN** `.env.example` is present with placeholder values and usage documentation
- **AND** `.env` is listed in `.gitignore`
- **AND** no real credential material appears in committed files

#### Scenario: ESO projects from seed-secrets
- **WHEN** ESO is running with a ClusterSecretStore or SecretStore referencing the `seed-secrets` Secret
- **THEN** ESO uses the Kubernetes provider or equivalent local provider to read the `seed-secrets` Secret
- **AND** the Fake provider is not used for this projection path

#### Scenario: Services consume narrow projected secrets
- **WHEN** a service or controller needs secret material
- **THEN** it consumes an ESO-projected ExternalSecret or SecretStore reference, not the raw `seed-secrets` Secret

#### Scenario: Minimal Seed Secret contract documents Flux operator input
- **WHEN** `.env.example` documents the first installable slice input contract
- **THEN** it includes the minimal Flux Git credential keys for username and PAT
- **AND** it explains that the PAT is used as the projected Flux HTTPS basic-auth password
- **AND** it explains that the Flux GitRepository URL and branch are Git-managed in the Flux desired-state manifest, not Seed Secret inputs

### Requirement: Flux self-management handoff
Kubecrate SHALL hand off Flux to self-management after bootstrap installation. Bootstrap installation SHALL apply or reference the same Flux desired-state path that Flux later reconciles. There SHALL NOT be duplicate independent Flux definitions under bootstrap installation and the GitOps desired-state path. Bootstrap installation is a loader or reference, not a second source of truth for Flux configuration.

#### Scenario: Bootstrap applies the same path Flux reconciles
- **WHEN** bootstrap installation applies the Flux desired-state path
- **THEN** the applied path is the same path Flux later reconciles from the cluster entrypoint
- **AND** no separate Flux definition exists exclusively under bootstrap installation

#### Scenario: Flux becomes self-managing after handoff
- **WHEN** Flux starts and reconciles the desired-state path
- **THEN** Flux manages its own configuration, including any future changes to Flux resources in the desired-state path
- **AND** the operator does not need to re-run bootstrap installation to update Flux configuration

#### Scenario: Flux Git source uses HTTPS remote and current branch
- **WHEN** Flux is configured to reconcile this repository
- **THEN** the Flux `GitRepository` resource points to this repository's HTTPS remote URL and the current implementation branch
- **AND** Git credentials are supplied through `seed-secrets` and projected via ESO ExternalSecret into a Secret using `username` and `password` keys for Flux HTTPS basic auth
- **AND** validation requires a commit and push to the implementation branch for Flux to detect and reconcile changes
- **AND** local Git server alternatives are secondary and out of the default path for this slice

#### Scenario: Flux seed credentials are suitable for read now and write-back soon
- **WHEN** the default Flux Git authentication contract is defined for the kind-first local path
- **THEN** it uses a fine-grained PAT as the HTTPS basic-auth password value
- **AND** the PAT is suitable for repository read access immediately and write access before `ImageUpdateAutomation` is enabled

#### Scenario: GitHub App remains a later reconsideration point
- **WHEN** the repository's Git authentication choice is documented for this slice
- **THEN** the default path is HTTPS plus fine-grained PAT for simplicity now
- **AND** GitHub App authentication is explicitly listed for reconsideration when bot or app identity, shorter-lived installation tokens, cleaner audit or rotation, stronger org or repo permission boundaries, or multi-repo or multi-org scale matters

### Requirement: Concrete runtime layout
Kubecrate SHALL place the first concrete runtime files under a layout that preserves the two-axis model while allowing cluster-owned validation material to live directly in a concrete cluster path. Each concrete cluster SHALL have an entrypoint at `clusters/<cluster>/entrypoint/` as the first GitOps reconciliation root. The first concrete cluster SHALL be `kind-dev-misc-local`. The first validation proof under this layout SHALL be `kubecrate-reconciliation-marker`, and it SHALL live in a concrete cluster path because it is not a platform service or application service. When real platform services or application services are introduced, their reusable base definitions SHALL live under `platform-services/<service>/base/` or `application-services/<service>/base/`, with cluster-specific binding under `clusters/<cluster>/platform-services/` or `clusters/<cluster>/application-services/`.

#### Scenario: Reusable service definitions are separate from cluster binding
- **WHEN** a platform service or application service is defined
- **THEN** its reusable base definition lives under the workload-category path for that service
- **AND** cluster-specific enablement, configuration, and version binding live under the corresponding cluster workload-category path

#### Scenario: Reconciliation marker lives directly under the concrete cluster path
- **WHEN** the runtime layout is populated for the first installable slice
- **THEN** `clusters/kind-dev-misc-local/entrypoint/` contains the first GitOps reconciliation root
- **AND** `clusters/kind-dev-misc-local/entrypoint/bootstrap-loader/kubecrate-reconciliation-marker.yaml` contains the validation marker/config proof with version X
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
Kubecrate SHALL include a tracer bullet that proves GitOps-managed operation performs an update using `kubecrate-reconciliation-marker`, a Flux-managed validation marker/config proof rather than a platform service or application service. The validation SHALL demonstrate: baseline reconciliation of `kubecrate-reconciliation-marker` at version X (`v0.1.0` or equivalent Git-tracked config value), a Git-managed version bump to version Y (`v0.2.0`), and Flux reconciliation evidence confirming the update. Version X→Y SHALL be defined via a Git-managed config value with evidence commands such as `kubectl get configmap kubecrate-reconciliation-marker -n <ns> -o jsonpath='{.data.version}'` before and after the change. Validation SHALL be operational and evidence-command based.

#### Scenario: Baseline reconcile succeeds with kubecrate-reconciliation-marker at version X
- **WHEN** bootstrap installation completes and Flux has reconciled
- **THEN** evidence confirms Flux is running, ESO is projecting secrets, and `kubecrate-reconciliation-marker` is present at version X (`v0.1.0`)
- **AND** the evidence command `kubectl get configmap kubecrate-reconciliation-marker -n <ns> -o jsonpath='{.data.version}'` returns the expected value for version X

#### Scenario: Git-managed change triggers Flux update of kubecrate-reconciliation-marker
- **WHEN** the operator commits a version bump for `kubecrate-reconciliation-marker` from `v0.1.0` to `v0.2.0` in `clusters/kind-dev-misc-local/entrypoint/bootstrap-loader/kubecrate-reconciliation-marker.yaml` and pushes to the implementation branch
- **THEN** Flux detects the change, reconciles, and `kubecrate-reconciliation-marker` reports version Y
- **AND** evidence captures the before/after version value via the evidence command and Flux reconciliation status confirming the update

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
