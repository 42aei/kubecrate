## Why

Backlog 0017 is ready for OpenSpec because it names a concrete platform service (cert-manager), a clear operator-visible outcome (TLS certificate issuance validated through CrateCheck), and an established validation consumer (CrateCheck). The kind-first local path already has Flux bootstrap installation and CrateCheck; this change brings cert-manager as the next platform service slice to prove TLS certificate management.

Kubecrate needs to prove that application services can consume TLS certificates issued through cert-manager and that CrateCheck can validate the full certificate lifecycle: controller health, Issuer readiness, Certificate issuance, and TLS Secret creation.

## What Changes

- Introduce cert-manager as a real platform service for the kind-first local path.
- Place the reusable cert-manager platform service base under `platform-services/cert-manager/base/` and the `kind-dev-misc-local` binding under `clusters/kind-dev-misc-local/platform-services/cert-manager/`.
- Use namespace `core-cert-manager` for cert-manager because it is a dedicated platform service namespace and follows the `core-<service-name>` rule.
- Keep cert-manager under GitOps-managed operation. Bootstrap installation remains responsible only for reaching the GitOps handoff.
- Add a local issuer path: a self-signed ClusterIssuer, a local CA Certificate, a CA-based ClusterIssuer, and a smoke TLS Certificate consumed by the existing Envoy Gateway path for CrateCheck HTTPS.
- Integrate with CrateCheck so that cert-manager checks (HelmRelease readiness, ClusterIssuer readiness, Certificate readiness, TLS Secret existence) are validated through CrateCheck's standard check framework.
- Define AI-runnable acceptance evidence that proves installation, controller health, issuer readiness, certificate issuance, TLS Secret creation, and a red test where intentional breakage makes CrateCheck report cert-manager checks as non-green, then restored green.

## Capabilities

### New Capabilities

- `cert-manager-certificate-management`: Defines the bounded cert-manager TLS certificate management vertical slice for certificate issuance on the kind-first local path.

### Modified Capabilities

- `cratecheck`: Extends CrateCheck check configuration, RBAC, and test validation to cover cert-manager platform service health and TLS certificate lifecycle.

## Impact

- Adds one GitOps-managed platform service and one end-to-end platform service consumption proof through CrateCheck.
- Adds runtime manifests, configuration, and validation for cert-manager certificate management on `kind-dev-misc-local`.
- Does not introduce ACME, Let's Encrypt, DNS-01 challenges, public DNS, production issuer policy, multi-environment certificate strategy, or external PKI backends.
- Does not make cert-manager part of bootstrap installation acceptance or change the Flux bootstrap contract.
- Preserves Kubecrate's two-axis model (lifecycle phase and workload category).