## ADDED Requirements

### Requirement: Kyverno is introduced as a GitOps-managed platform service
Kubecrate SHALL introduce Kyverno as a platform service for the kind-first local path. Kyverno SHALL be reconciled through GitOps-managed operation after bootstrap installation has handed off to the GitOps controller, and Kyverno SHALL NOT become a prerequisite for bootstrap installation acceptance in this slice.

#### Scenario: Kyverno follows platform service placement
- **WHEN** Kyverno runtime files are introduced
- **THEN** the reusable platform service base lives under `platform-services/kyverno/base/`
- **AND** the `kind-dev-misc-local` cluster binding lives under `clusters/kind-dev-misc-local/platform-services/kyverno/`
- **AND** the existing cluster entrypoint includes Flux `Kustomization` resources that reconcile the Kyverno controller, then the smoke policy, then its consumer fixture
- **AND** no unrelated empty platform services or application services skeleton directories are created

#### Scenario: Kyverno smoke resources wait for controller CRDs
- **WHEN** the `kind-dev-misc-local` entrypoint is reconciled through GitOps-managed operation
- **THEN** the Kyverno smoke policy resources are in a Flux `Kustomization` that depends on the Kyverno controller `Kustomization`
- **AND** a cluster that has not yet installed Kyverno CRDs can reconcile the entrypoint without requiring ClusterPolicy mappings in the root entrypoint render

#### Scenario: Kyverno stays outside bootstrap installation acceptance
- **WHEN** bootstrap installation acceptance is evaluated for the kind-first local path
- **THEN** bootstrap installation remains responsible for reaching GitOps-managed operation handoff
- **AND** Kyverno installation or readiness is not required for that bootstrap installation handoff
- **AND** Kyverno is installed and updated through GitOps-managed operation after handoff

### Requirement: Kyverno uses the core platform service namespace pattern
Kubecrate SHALL use `core-kyverno` as the dedicated Kubernetes namespace for Kyverno. This namespace SHALL follow the `core-<service-name>` rule for platform services and SHALL NOT reuse Flux's `flux-system` namespace exception.

#### Scenario: Kyverno namespace follows platform service naming
- **WHEN** Kyverno is installed on the kind-first local path
- **THEN** Kyverno controller resources are placed in namespace `core-kyverno`
- **AND** Flux controller, source, and sync resources remain in `flux-system`
- **AND** `flux-system` is not treated as a general namespace pattern for future platform services

### Requirement: Smoke policy proves real admission control
Kubecrate SHALL provide a minimal Kyverno smoke policy that proves admission control enforcement. The proof SHALL include a `require-ns-label` ClusterPolicy in Enforce mode scoped to `kyverno-smoke-*` namespaces and an allowed fixture namespace that satisfies the policy.

#### Scenario: ClusterPolicy enforces namespace labeling
- **WHEN** Kyverno controller is healthy
- **AND** the `require-ns-label` ClusterPolicy is created in Enforce mode
- **THEN** Kyverno marks the ClusterPolicy as Ready
- **AND** the rule matches only namespaces named `kyverno-smoke-*`
- **AND** namespaces carrying the label `kubecrate.io/validated: "true"` can be created
- **AND** namespaces without the label are denied on creation
- **AND** the denied admission reports `Namespace requires kubecrate.io/validated=true`

#### Scenario: Allowed fixture namespace exists
- **WHEN** the ClusterPolicy is Ready
- **AND** the `kyverno-smoke-allowed` namespace resource is applied
- **THEN** the namespace is created because it carries the required label
- **AND** the namespace is visible as a Kubernetes resource

#### Scenario: Smoke policy material avoids committed secrets
- **WHEN** policy resources are committed to the repository
- **THEN** committed files contain only Kubernetes resource definitions (ClusterPolicy, Namespace)
- **AND** no private keys, certificates, or sensitive material are committed

### Requirement: CrateCheck validates the Kyverno policy path
Kubecrate SHALL extend CrateCheck with Kyverno validation checks. CrateCheck SHALL validate Kyverno controller health (HelmRelease readiness), ClusterPolicy readiness, and allowed fixture namespace existence. CrateCheck SHALL NOT be replaced by a Kyverno-specific status app.

#### Scenario: Kyverno checks report green when the full path is healthy
- **WHEN** Kyverno controller is healthy
- **AND** the ClusterPolicy is Ready
- **AND** the allowed fixture namespace exists
- **THEN** CrateCheck reports all Kyverno checks as green through its standard check output

#### Scenario: CrateCheck ClusterRole allows Kyverno resource reads
- **WHEN** CrateCheck is configured with Kyverno checks
- **THEN** its ClusterRole includes read access to helm.toolkit.fluxcd.io HelmRelease resources
- **AND** includes read access to kyverno.io ClusterPolicy resources

#### Scenario: Non-green Kyverno output is diagnostic
- **WHEN** any Kyverno check reports non-green
- **THEN** the check output identifies which resource is unhealthy (HelmRelease, ClusterPolicy, or allowed fixture namespace)
- **AND** the failure message indicates the expected condition that is not met

### Requirement: Kyverno policy validation includes operational end-to-end evidence and red testing
Kubecrate SHALL provide AI-runnable validation for the Kyverno policy guardrails slice. Validation SHALL include static rendering plus operational evidence after GitOps-managed operation reconciles the resources, plus a controlled red test. Static rendering, schema validation, and resource existence alone SHALL NOT be treated as sufficient success evidence.

#### Scenario: Static and OpenSpec validation pass before runtime success is claimed
- **WHEN** this OpenSpec change is evaluated
- **THEN** `openspec validate introduce-kyverno-policy-guardrails --type change --strict --json --no-interactive` succeeds
- **AND** static rendering for the `kind-dev-misc-local` entrypoint succeeds after runtime files are added

#### Scenario: Runtime evidence proves Kyverno and CrateCheck validation health
- **WHEN** the Kyverno policy guardrails slice is validated on the kind-first local path
- **THEN** evidence confirms the intended cluster context
- **AND** evidence confirms Kyverno namespace, CRDs, controller resources, controller readiness, ClusterPolicy readiness, and allowed fixture namespace existence
- **AND** evidence confirms CrateCheck reports Kyverno checks as green
- **AND** evidence confirms an allowed scoped namespace is admitted and an unlabeled scoped namespace is denied for the exact policy reason
- **AND** recent relevant events or logs do not show blocking Kyverno reconciliation errors

#### Scenario: Red test proves Kyverno failure detection
- **WHEN** the Kyverno policy guardrails slice has first been validated green
- **AND** the Kyverno path is intentionally broken in a controlled, reversible, non-sensitive way
- **THEN** CrateCheck reports exactly `kyverno-clusterpolicy-ready` as red and all unrelated checks remain green
- **AND** after the expected configuration is restored, CrateCheck returns Kyverno checks to green

### Requirement: Kyverno policy scope remains bounded
Kubecrate SHALL keep this Kyverno policy guardrails slice limited to the minimum platform-service implementation and CrateCheck validation proof needed for the kind-first local path.

#### Scenario: Production policy frameworks remain deferred
- **WHEN** the Kyverno policy guardrails slice is evaluated for completion
- **THEN** production compliance profiles, multi-tenant governance, background scanning, exception management, and environment-specific policy promotion are not required

#### Scenario: Other platform services remain deferred
- **WHEN** the Kyverno policy guardrails slice is evaluated for completion
- **THEN** a Kyverno-specific status app, observability, cert-manager, and wave-like promotion mechanics are not installed, configured, or required by this change