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
- **AND** the generic kubecrate status application service depends on the ESO smoke `Kustomization`
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
Kubecrate SHALL provide a local ESO smoke projection path that proves projection from operator-supplied or locally seeded Kubernetes Secret material into a narrower service-specific target Secret. The proof SHALL use the ESO Kubernetes provider, or an equivalent local provider with the same capability. The Fake provider MAY be present for supplemental demo behavior, but it SHALL NOT be the only acceptance proof.

#### Scenario: Local provider projects a narrow target Secret
- **WHEN** the local smoke source material exists in the cluster
- **AND** ESO reconciles the configured SecretStore or ClusterSecretStore and ExternalSecret
- **THEN** ESO creates or updates a target Secret in the validation app namespace
- **AND** the target Secret contains only the intended narrow smoke key or keys needed by the validation app
- **AND** the validation app does not need access to the broader source Secret

#### Scenario: Fake provider is not sufficient by itself
- **WHEN** the ESO smoke slice is validated
- **THEN** a Fake provider-only projection does not satisfy acceptance
- **AND** acceptance requires evidence that local operator-supplied or locally seeded Kubernetes Secret material was projected through ESO or an equivalent real local provider path

#### Scenario: Smoke source material avoids committed sensitive credentials
- **WHEN** source material is needed for the smoke path
- **THEN** committed repository files use non-sensitive fixture data or document a local seed command
- **AND** raw sensitive credential material is not committed
- **AND** validation commands do not print private or sensitive Secret values

### Requirement: Generic kubecrate status app consumes the ESO-projected Secret
Kubecrate SHALL integrate the ESO smoke path with the existing generic kubecrate status application service. The status app SHALL consume the ESO-projected target Secret, not the broad source Secret, and SHALL report the secret-loading check through both the status UI and status JSON. Kubecrate SHALL NOT create an ESO-specific status app or separate service-specific dashboard for this slice.

#### Scenario: Secret-loading check turns green only after app read
- **WHEN** ESO has created the target Secret
- **AND** the validation app has been wired to consume that target Secret
- **AND** the validation app has actually loaded the expected projected value
- **THEN** the status JSON secret-loading check reports `green`
- **AND** the human status UI shows the secret-loading check as green
- **AND** the check explains that it validates projected Secret consumption by an application service
- **AND** the check appears as part of the generic kubecrate status app rather than an ESO-specific status app

#### Scenario: Target Secret existence alone is not enough
- **WHEN** the target Secret exists but the validation app cannot read or load it
- **THEN** the secret-loading check does not report `green`
- **AND** the status output identifies application environment or volume wiring and application read behavior as likely areas to inspect

#### Scenario: Non-green secret-loading output is diagnostic
- **WHEN** the secret-loading check reports `yellow`, `red`, or `not_configured`
- **THEN** the status UI or status JSON distinguishes likely failure areas, including ESO controller health, SecretStore or ClusterSecretStore readiness, ExternalSecret readiness, target Secret creation, application environment or volume wiring, and application read behavior
- **AND** the output keeps the same stable status check fields defined by the validation app contract

### Requirement: ESO smoke validation includes operational end-to-end evidence and red testing
Kubecrate SHALL provide AI-runnable validation for the ESO smoke slice. Validation SHALL include static rendering plus operational evidence after GitOps-managed operation reconciles the resources, plus a controlled red test that proves the generic kubecrate status app detects ESO secret-loading failure. Static rendering, schema validation, and target Secret existence alone SHALL NOT be treated as sufficient success evidence.

#### Scenario: Static and OpenSpec validation pass before runtime success is claimed
- **WHEN** this OpenSpec change is evaluated
- **THEN** `openspec validate introduce-external-secrets-operator-smoke --type change --strict --json --no-interactive` succeeds
- **AND** `openspec status --change introduce-external-secrets-operator-smoke --json` reports the change artifacts
- **AND** static rendering for the `kind-dev-misc-local` entrypoint succeeds after runtime files are added

#### Scenario: Runtime evidence proves ESO and consumer health
- **WHEN** the ESO smoke slice is validated on the kind-first local path
- **THEN** evidence confirms the intended cluster context
- **AND** evidence confirms ESO namespace, CRDs, controller resources, controller readiness, SecretStore or ClusterSecretStore readiness, ExternalSecret readiness, and target Secret creation
- **AND** evidence confirms the validation app workload has rolled out with the secret wiring
- **AND** evidence confirms the validation app status JSON reports the enabled secret-loading check as `green`
- **AND** evidence confirms the human status UI shows the same operator-visible secret-loading outcome
- **AND** recent relevant events or logs do not show blocking ESO reconciliation or application secret-loading errors

#### Scenario: Red test proves secret-loading failure detection
- **WHEN** the ESO smoke slice has first been validated green
- **AND** the ESO secret-loading path is intentionally broken in a controlled, reversible, non-sensitive way
- **THEN** the generic kubecrate status app status JSON reports the `secret-loading` check as non-green
- **AND** the status UI shows the same non-green secret-loading outcome
- **AND** the diagnostic output identifies the likely failing layer, such as SecretStore or ClusterSecretStore readiness, ExternalSecret status, target Secret creation, application environment or volume wiring, or application read behavior
- **AND** after the expected configuration is restored, the status JSON and UI return the `secret-loading` check to `green`

#### Scenario: Deeper diagnosis remains symptom-driven
- **WHEN** ESO smoke validation fails or remains unclear
- **THEN** investigation focuses on the layer indicated by evidence, such as reconciliation status, events, logs, networking, RBAC, or application wiring
- **AND** authorization checks such as `kubectl auth can-i` are used when evidence points to authorization rather than as a mandatory per-ServiceAccount checklist

### Requirement: ESO smoke scope remains bounded
Kubecrate SHALL keep this ESO smoke slice limited to the minimum platform-service implementation and application-service consumption proof needed for the kind-first local path. The slice SHALL NOT introduce production credential providers, broad secret-management policy, an ESO-specific status app, ingress, certificate management, observability, Kyverno, or wave-like promotion mechanics.

#### Scenario: Provider-specific production backends remain deferred
- **WHEN** the ESO smoke slice is evaluated for completion
- **THEN** AWS Secrets Manager, GCP Secret Manager, Vault, and other production backends are not required
- **AND** production credential onboarding, rotation, and multi-environment secret policy remain deferred to later changes

#### Scenario: Other platform services remain deferred
- **WHEN** the ESO smoke slice is evaluated for completion
- **THEN** an ESO-specific status app, ingress, certificate management, observability, Kyverno, and wave-like promotion mechanics are not installed, configured, or required by this change
