## ADDED Requirements

### Requirement: Validation app is an application service fixture
Kubecrate SHALL provide a reusable validation application service fixture for the kind-first local path. The fixture SHALL be classified as application services scope because it consumes platform services through their documented interfaces, and it SHALL NOT be classified as a platform service.

#### Scenario: Validation app follows application service placement
- **WHEN** the validation app runtime files are introduced
- **THEN** its reusable definition lives under `application-services/<service>/base/`
- **AND** its `kind-dev-misc-local` cluster binding lives under `clusters/kind-dev-misc-local/application-services/<service>/`
- **AND** no unrelated empty application service skeleton directories are created

#### Scenario: Validation app is reconciled through GitOps-managed operation
- **WHEN** the validation app is installed on the kind-first local path
- **THEN** it is reconciled through the existing GitOps-managed operation entrypoint
- **AND** bootstrap installation does not install or own the validation app

### Requirement: Validation app exposes status UI and status JSON
The validation app SHALL expose both a human-readable status UI and a machine-readable status JSON endpoint. The status UI SHALL present a polished status panel suitable for human inspection. The status JSON endpoint SHALL be the stable AI-runnable validation contract.

#### Scenario: Human can inspect status UI
- **WHEN** an operator opens the validation app status UI
- **THEN** the UI shows an overall status and individual checks
- **AND** each check includes a human-readable explanation of what it validates
- **AND** non-green checks include troubleshooting guidance for likely failing layers

#### Scenario: Agent can inspect status JSON
- **WHEN** an AI agent or validation script fetches the status JSON endpoint
- **THEN** the response includes an overall status
- **AND** the response includes a list of individual checks with stable machine-readable fields
- **AND** the response can be parsed without scraping the human UI

### Requirement: Status checks explain validation scope and failure areas
Each status check SHALL report what capability it validates, what platform or Kubernetes area it exercises, its current state, and troubleshooting guidance that helps pinpoint the likely failing layer when the check is not green.

#### Scenario: Check includes required diagnostic metadata
- **WHEN** the status JSON reports a check
- **THEN** the check includes an identifier, display name, state, capability, exercised area, summary, and troubleshooting guidance
- **AND** the check identifies whether the capability is enabled for the current slice

#### Scenario: Non-green check is actionable
- **WHEN** a check reports `red`, `yellow`, or `not_configured`
- **THEN** the status output explains the likely area to inspect next
- **AND** the explanation distinguishes application wiring from platform service availability where that distinction is known

### Requirement: Status JSON has stable minimum fields
The validation app status JSON SHALL include a stable minimum contract so future agents can validate it mechanically. The response SHALL include app identity, version or build information, overall status, timestamp or generation time when available, and checks.

#### Scenario: Status JSON includes required top-level fields
- **WHEN** the status JSON endpoint is fetched
- **THEN** the response includes `app`, `version`, `overallStatus`, and `checks`
- **AND** `checks` is an array of check objects

#### Scenario: Status JSON check object includes required fields
- **WHEN** a check object appears in the status JSON response
- **THEN** it includes `id`, `name`, `state`, `capability`, `area`, `enabled`, `summary`, and `troubleshooting`
- **AND** `state` is one of `green`, `yellow`, `red`, or `not_configured`

### Requirement: Initial check categories support future platform services
The validation app SHALL define initial check categories for base app health, secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior. The first slice SHALL only require base app health to be green. Future platform service slices MAY enable and validate additional categories.

#### Scenario: Initial slice passes without future platform services
- **WHEN** only the validation app slice is installed
- **THEN** the base app health check reports `green`
- **AND** checks for secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior may report `not_configured`
- **AND** `not_configured` future checks do not make the initial validation app slice fail

#### Scenario: Future platform service slices can enable checks
- **WHEN** a later platform service slice enables a related validation check
- **THEN** that check can report `green`, `yellow`, or `red` based on live evidence from the app or its environment
- **AND** the check continues to use the same status JSON contract

### Requirement: AI-runnable validation proves the fixture works
Kubecrate SHALL provide AI-runnable validation commands for the validation app. These commands SHALL prove the app is reconciled, reachable through the slice-appropriate access path, and returns status JSON with the expected enabled checks green.

#### Scenario: Validation command verifies status JSON
- **WHEN** the validation app has reconciled on the kind-first local path
- **THEN** an AI-runnable command fetches the status JSON endpoint
- **AND** the command verifies that the base app health check is `green`
- **AND** the command verifies that future platform service checks do not fail the initial slice when they are `not_configured`

#### Scenario: Operational evidence is collected before success is claimed
- **WHEN** the validation app slice is validated
- **THEN** validation includes the intended cluster context, expected application service resources, workload health, readiness, recent blocking events or logs when relevant, and the operator-visible status output
- **AND** static rendering alone is not treated as sufficient evidence after resources are reconciled

### Requirement: Scope excludes platform service implementations
This validation app slice SHALL NOT install or configure ESO, Envoy Gateway, cert-manager, observability backends, Kyverno, or other platform services. It SHALL preserve future integration points for those services without making them required for this slice.

#### Scenario: Platform services remain follow-up work
- **WHEN** this slice is evaluated for completion
- **THEN** ESO, ingress, certificate management, observability, and policy platform services are not required
- **AND** their related validation checks are either absent from live validation requirements or reported as `not_configured`
