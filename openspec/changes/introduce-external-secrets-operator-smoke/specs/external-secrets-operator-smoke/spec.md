## ADDED Requirements

### Requirement: ESO is introduced as a GitOps-managed platform service
Kubecrate SHALL introduce External-Secrets Operator as a platform service for the kind-first local path. ESO SHALL be reconciled through GitOps-managed operation after bootstrap installation has handed off to the GitOps controller, and ESO SHALL NOT become a prerequisite for bootstrap installation acceptance in this slice.

#### Scenario: ESO follows platform service placement
- **WHEN** ESO runtime files are introduced
- **THEN** the reusable platform service base lives under `platform-services/external-secrets-operator/base/`
- **AND** the `kind-dev-misc-local` cluster binding lives under `clusters/kind-dev-misc-local/platform-services/external-secrets-operator/`
- **AND** the existing cluster entrypoint includes Flux `Kustomization` resources that reconcile the ESO controller before the smoke SecretStore and ExternalSecret resources
- **AND** no unrelated empty platform services or application services skeleton directories are created

#### Scenario: ESO smoke resources wait for controller CRDs
- **WHEN** the `kind-dev-misc-local` entrypoint is reconciled through GitOps-managed operation
- **THEN** the ESO smoke SecretStore and ExternalSecret resources are in a Flux `Kustomization` that depends on the ESO controller `Kustomization`
- **AND** a cluster that has not yet installed ESO CRDs can reconcile the entrypoint without requiring SecretStore or ExternalSecret mappings in the root entrypoint render

#### Scenario: ESO stays outside bootstrap installation acceptance
- **WHEN** bootstrap installation acceptance is evaluated for the kind-first local path
- **THEN** bootstrap installation remains responsible for reaching GitOps-managed operation handoff
- **AND** ESO installation or readiness is not required for that bootstrap installation handoff
- **AND** ESO is installed and updated through GitOps-managed operation after handoff

### Requirement: ESO uses the core platform service namespace pattern
Kubecrate SHALL use `core-external-secrets-operator` as the dedicated Kubernetes namespace for External-Secrets Operator. This namespace SHALL follow the `core-<service-name>` rule for platform services and SHALL NOT reuse Flux's `flux-system` namespace exception.

#### Scenario: ESO namespace follows platform service naming
- **WHEN** ESO is installed on the kind-first local path
- **THEN** ESO controller resources are placed in namespace `core-external-secrets-operator`
- **AND** Flux controller, source, and sync resources remain in `flux-system`
- **AND** `flux-system` is not treated as a general namespace pattern for future platform services

### Requirement: Local smoke projection uses real source material flow
Kubecrate SHALL provide a local ESO smoke projection path that proves projection from locally seeded Kubernetes Secret material into a narrower service-specific target Secret. The proof SHALL use the ESO Kubernetes provider.

#### Scenario: Local provider projects a narrow target Secret
- **WHEN** the local smoke source material exists in the cluster
- **AND** ESO reconciles the configured SecretStore and ExternalSecret
- **THEN** ESO creates or updates a target Secret in the `kubecrate-system` namespace
- **AND** the target Secret contains only the intended narrow smoke key

#### Scenario: Smoke source material avoids committed sensitive credentials
- **WHEN** source material is needed for the smoke path
- **THEN** committed repository files use non-sensitive fixture data
- **AND** raw sensitive credential material is not committed

### Requirement: CrateCheck validates the ESO secret projection path
Kubecrate SHALL extend CrateCheck with ESO validation checks. CrateCheck SHALL validate ESO controller health (HelmRelease readiness), SecretStore readiness, ExternalSecret readiness, and projected Secret existence. CrateCheck SHALL NOT be replaced by an ESO-specific status app.

#### Scenario: ESO checks report green when the full path is healthy
- **WHEN** ESO controller is healthy
- **AND** the smoke SecretStore is ready
- **AND** the smoke ExternalSecret is synced and ready
- **AND** the projected Secret exists
- **THEN** CrateCheck reports all ESO checks as green through its standard check output

#### Scenario: CrateCheck ClusterRole allows ESO resource reads
- **WHEN** CrateCheck is configured with ESO checks
- **THEN** its ClusterRole includes read access to helm.toolkit.fluxcd.io HelmRelease resources
- **AND** includes read access to external-secrets.io SecretStore and ExternalSecret resources
- **AND** includes read access to core Secret resources for projected Secret verification

#### Scenario: Non-green ESO output is diagnostic
- **WHEN** any ESO check reports non-green
- **THEN** the check output identifies which resource is unhealthy (HelmRelease, SecretStore, ExternalSecret, or projected Secret)
- **AND** the failure message indicates the expected condition that is not met

### Requirement: ESO smoke validation includes operational end-to-end evidence and red testing
Kubecrate SHALL provide AI-runnable validation for the ESO smoke slice. Validation SHALL include static rendering plus operational evidence after GitOps-managed operation reconciles the resources, plus a controlled red test. Static rendering, schema validation, and target Secret existence alone SHALL NOT be treated as sufficient success evidence.

#### Scenario: Static and OpenSpec validation pass before runtime success is claimed
- **WHEN** this OpenSpec change is evaluated
- **THEN** `openspec validate introduce-external-secrets-operator-smoke --type change --strict --json --no-interactive` succeeds
- **AND** `openspec status --change introduce-external-secrets-operator-smoke --json` reports the change artifacts
- **AND** static rendering for the `kind-dev-misc-local` entrypoint succeeds after runtime files are added

#### Scenario: Runtime evidence proves ESO and CrateCheck validation health
- **WHEN** the ESO smoke slice is validated on the kind-first local path
- **THEN** evidence confirms the intended cluster context
- **AND** evidence confirms ESO namespace, CRDs, controller resources, controller readiness, SecretStore readiness, ExternalSecret readiness, and target Secret creation
- **AND** evidence confirms CrateCheck reports ESO checks as green
- **AND** recent relevant events or logs do not show blocking ESO reconciliation errors

#### Scenario: Red test proves ESO failure detection
- **WHEN** the ESO smoke slice has first been validated green
- **AND** the ESO projection path is intentionally broken in a controlled, reversible, non-sensitive way
- **THEN** CrateCheck reports the affected ESO checks as non-green
- **AND** after the expected configuration is restored, CrateCheck returns ESO checks to green

### Requirement: ESO smoke scope remains bounded
Kubecrate SHALL keep this ESO smoke slice limited to the minimum platform-service implementation and CrateCheck validation proof needed for the kind-first local path.

#### Scenario: Provider-specific production backends remain deferred
- **WHEN** the ESO smoke slice is evaluated for completion
- **THEN** AWS Secrets Manager, GCP Secret Manager, Vault, and other production backends are not required
- **AND** production credential onboarding, rotation, and multi-environment secret policy remain deferred to later changes

#### Scenario: Other platform services remain deferred
- **WHEN** the ESO smoke slice is evaluated for completion
- **THEN** an ESO-specific status app, ingress, certificate management, observability, Kyverno, and wave-like promotion mechanics are not installed, configured, or required by this change
