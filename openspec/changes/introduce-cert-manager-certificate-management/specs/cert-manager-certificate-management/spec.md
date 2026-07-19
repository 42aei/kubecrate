## ADDED Requirements

### Requirement: cert-manager is introduced as a GitOps-managed platform service
Kubecrate SHALL introduce cert-manager as a platform service for the kind-first local path. cert-manager SHALL be reconciled through GitOps-managed operation after bootstrap installation has handed off to the GitOps controller, and cert-manager SHALL NOT become a prerequisite for bootstrap installation acceptance in this slice.

#### Scenario: cert-manager follows platform service placement
- **WHEN** cert-manager runtime files are introduced
- **THEN** the reusable platform service base lives under `platform-services/cert-manager/base/`
- **AND** the `kind-dev-misc-local` cluster binding lives under `clusters/kind-dev-misc-local/platform-services/cert-manager/`
- **AND** the existing cluster entrypoint includes Flux `Kustomization` resources that reconcile the cert-manager controller before the local issuer resources
- **AND** no unrelated empty platform services or application services skeleton directories are created

#### Scenario: cert-manager local issuer waits for controller CRDs
- **WHEN** the `kind-dev-misc-local` entrypoint is reconciled through GitOps-managed operation
- **THEN** the cert-manager local issuer resources are in a Flux `Kustomization` that depends on the cert-manager controller `Kustomization`
- **AND** a cluster that has not yet installed cert-manager CRDs can reconcile the entrypoint without requiring ClusterIssuer or Certificate mappings in the root entrypoint render

#### Scenario: cert-manager stays outside bootstrap installation acceptance
- **WHEN** bootstrap installation acceptance is evaluated for the kind-first local path
- **THEN** bootstrap installation remains responsible for reaching GitOps-managed operation handoff
- **AND** cert-manager installation or readiness is not required for that bootstrap installation handoff
- **AND** cert-manager is installed and updated through GitOps-managed operation after handoff

### Requirement: cert-manager uses the core platform service namespace pattern
Kubecrate SHALL use `core-cert-manager` as the dedicated Kubernetes namespace for cert-manager. This namespace SHALL follow the `core-<service-name>` rule for platform services and SHALL NOT reuse Flux's `flux-system` namespace exception.

#### Scenario: cert-manager namespace follows platform service naming
- **WHEN** cert-manager is installed on the kind-first local path
- **THEN** cert-manager controller resources are placed in namespace `core-cert-manager`
- **AND** Flux controller, source, and sync resources remain in `flux-system`
- **AND** `flux-system` is not treated as a general namespace pattern for future platform services

### Requirement: Local issuer path proves real certificate issuance
Kubecrate SHALL provide a local cert-manager issuer path that proves certificate issuance from a self-signed CA through a ClusterIssuer chain. The proof SHALL issue a TLS Certificate for CrateCheck that generates a Kubernetes TLS Secret.

#### Scenario: Self-signed ClusterIssuer serves as trust anchor
- **WHEN** cert-manager controller is healthy
- **AND** the self-signed ClusterIssuer `kubecrate-local-selfsigned` is created
- **THEN** cert-manager marks the ClusterIssuer as Ready

#### Scenario: CA Certificate is issued and creates a CA Secret
- **WHEN** the self-signed ClusterIssuer is ready
- **AND** the CA Certificate `cratecheck-local-ca` (isCA: true) is created in namespace `core-cert-manager`
- **THEN** cert-manager issues the CA Certificate
- **AND** a Kubernetes Secret `cratecheck-local-ca` is created in namespace `core-cert-manager` containing the CA key material

#### Scenario: CA-based ClusterIssuer is ready
- **WHEN** the CA Certificate Secret exists
- **AND** the ClusterIssuer `kubecrate-local-ca` (ca type) is created referencing `cratecheck-local-ca`
- **THEN** cert-manager marks the CA ClusterIssuer as Ready

#### Scenario: TLS Certificate is issued for CrateCheck
- **WHEN** the CA ClusterIssuer is ready
- **AND** the TLS Certificate `cratecheck-tls` is created in namespace `cratecheck`
- **THEN** cert-manager issues the TLS Certificate
- **AND** a Kubernetes Secret `cratecheck-tls` is created containing TLS key and certificate material

#### Scenario: Envoy Gateway consumes the issued certificate
- **WHEN** the TLS Certificate and Secret are ready
- **THEN** the existing Envoy Gateway HTTPS listener references `Secret/cratecheck-tls`
- **AND** a narrow ReferenceGrant in namespace `cratecheck` permits that reference
- **AND** the existing CrateCheck route attaches to the HTTPS listener
- **AND** a client that trusts the issued local CA can fetch CrateCheck `/status.json` as `https://cratecheck.local`

#### Scenario: Smoke certificate material avoids committed secrets
- **WHEN** certificate resources are committed to the repository
- **THEN** committed files contain only Kubernetes resource definitions (ClusterIssuer, Certificate specs)
- **AND** no private keys, certificates, or sensitive material are committed — cert-manager generates all key material at runtime

### Requirement: CrateCheck validates the cert-manager certificate path
Kubecrate SHALL extend CrateCheck with cert-manager validation checks. CrateCheck SHALL validate cert-manager controller health (HelmRelease readiness), self-signed ClusterIssuer readiness, CA Certificate readiness, CA ClusterIssuer readiness, TLS Certificate readiness, and TLS Secret existence. CrateCheck SHALL NOT be replaced by a cert-manager-specific status app.

#### Scenario: cert-manager checks report green when the full path is healthy
- **WHEN** cert-manager controller is healthy
- **AND** the self-signed ClusterIssuer is ready
- **AND** the CA Certificate is issued and ready
- **AND** the CA ClusterIssuer is ready
- **AND** the TLS Certificate is issued and ready
- **AND** the TLS Secret exists
- **THEN** CrateCheck reports all cert-manager checks as green through its standard check output

#### Scenario: CrateCheck ClusterRole allows cert-manager resource reads
- **WHEN** CrateCheck is configured with cert-manager checks
- **THEN** its ClusterRole includes read access to helm.toolkit.fluxcd.io HelmRelease resources
- **AND** includes read access to cert-manager.io ClusterIssuer and Certificate resources
- **AND** includes read access to core Secret resources for TLS Secret verification

#### Scenario: Non-green cert-manager output is diagnostic
- **WHEN** any cert-manager check reports non-green
- **THEN** the check output identifies which resource is unhealthy (HelmRelease, ClusterIssuer, Certificate, or TLS Secret)
- **AND** the failure message indicates the expected condition that is not met

### Requirement: cert-manager TLS validation includes operational end-to-end evidence and red testing
Kubecrate SHALL provide AI-runnable validation for the cert-manager TLS slice. Validation SHALL include static rendering plus operational evidence after GitOps-managed operation reconciles the resources, plus a controlled red test. Static rendering, schema validation, and TLS Secret existence alone SHALL NOT be treated as sufficient success evidence.

#### Scenario: Static and OpenSpec validation pass before runtime success is claimed
- **WHEN** this OpenSpec change is evaluated
- **THEN** `openspec validate introduce-cert-manager-certificate-management --type change --strict --json --no-interactive` succeeds
- **AND** static rendering for the `kind-dev-misc-local` entrypoint succeeds after runtime files are added

#### Scenario: Runtime evidence proves cert-manager and CrateCheck validation health
- **WHEN** the cert-manager TLS slice is validated on the kind-first local path
- **THEN** evidence confirms the intended cluster context
- **AND** evidence confirms cert-manager namespace, CRDs, controller resources, controller readiness, ClusterIssuer readiness, Certificate readiness, and TLS Secret creation
- **AND** evidence confirms CrateCheck reports cert-manager checks as green
- **AND** evidence confirms trusted HTTPS reaches CrateCheck through Envoy Gateway using the issued certificate
- **AND** recent relevant events or logs do not show blocking cert-manager reconciliation errors

#### Scenario: Red test proves cert-manager failure detection
- **WHEN** the cert-manager TLS slice has first been validated green
- **AND** the cert-manager path is intentionally broken in a controlled, reversible, non-sensitive way
- **THEN** CrateCheck reports the affected cert-manager checks as non-green
- **AND** after the expected configuration is restored, CrateCheck returns cert-manager checks to green

### Requirement: cert-manager TLS scope remains bounded
Kubecrate SHALL keep this cert-manager TLS slice limited to the minimum platform-service implementation and CrateCheck validation proof needed for the kind-first local path.

#### Scenario: Production PKI backends remain deferred
- **WHEN** the cert-manager TLS slice is evaluated for completion
- **THEN** ACME, Let's Encrypt, DNS-01 challenges, public DNS, production issuer policies, multi-environment certificate strategy, and external PKI backends are not required

#### Scenario: Other platform services remain deferred
- **WHEN** the cert-manager TLS slice is evaluated for completion
- **THEN** a cert-manager-specific status app, observability, Kyverno, and wave-like promotion mechanics are not installed, configured, or required by this change