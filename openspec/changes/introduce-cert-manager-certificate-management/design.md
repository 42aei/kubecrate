## Context

The kind-first local path has Flux bootstrap installation and CrateCheck as the validation application service. Backlog 0017 introduces cert-manager as the TLS certificate management platform service. This change adds cert-manager with a local issuer path that proves real certificate issuance and TLS Secret creation, validated end-to-end through CrateCheck.

This change intentionally stays kind-first and production-inspired but not production-ready. It proves the platform capability with a local self-signed CA path and CrateCheck validation. ACME, public DNS, production issuer policies, and multi-environment certificate strategy are deferred.

## Goals / Non-Goals

**Goals:**

- Add cert-manager as the next real GitOps-managed platform service for `kind-dev-misc-local`.
- Keep cert-manager independent from bootstrap installation acceptance while preserving handoff into GitOps-managed operation.
- Use `core-cert-manager` as the dedicated cert-manager namespace.
- Prove local TLS certificate issuance from a self-signed CA through a ClusterIssuer chain.
- Extend CrateCheck with cert-manager validation checks: HelmRelease readiness, ClusterIssuer readiness, Certificate readiness, and TLS Secret existence.
- Provide AI-runnable validation evidence covering controller health, issuer readiness, certificate issuance, and TLS Secret creation.
- Include a red test that intentionally breaks the cert-manager path and proves CrateCheck reports cert-manager checks as non-green, then restores green.

**Non-Goals:**

- Making cert-manager bootstrap-critical for the first GitOps handoff.
- Installing or validating ACME, Let's Encrypt, DNS-01 challenges, public DNS, or production PKI backends.
- Defining a complete certificate policy, rotation strategy, multi-tenant model, or per-application issuer automation.
- Introducing observability, Kyverno, or wave-like promotion mechanics through this slice.
- Creating a separate cert-manager-specific status app — CrateCheck is the single validation surface.
- Requiring Envoy Gateway ingress as a dependency for certificate validation — the local issuer path and TLS Secret creation are independently testable.

## Decisions

### cert-manager is a GitOps-managed platform service

cert-manager is operator-owned TLS infrastructure and is therefore platform services scope. It is installed after the GitOps handoff through the existing `kind-dev-misc-local` entrypoint. The reusable service definition lives at `platform-services/cert-manager/base/`. The concrete cluster binding lives at `clusters/kind-dev-misc-local/platform-services/cert-manager/`.

Two Flux `Kustomization` objects are introduced: one for the cert-manager controller (HelmRelease), and one for the local issuer path (ClusterIssuers and Certificates). The local issuer `Kustomization` depends on the controller `Kustomization`.

### Namespace follows the core service rule

cert-manager uses namespace `core-cert-manager`. This follows the `core-<service-name>` rule.

### Local self-signed CA proves real issuance

The acceptance proof uses a self-signed ClusterIssuer to issue a local CA Certificate (isCA: true), which then backs a CA-based ClusterIssuer that issues an end-entity TLS Certificate for CrateCheck. The TLS Certificate generates a Kubernetes Secret (`cratecheck-tls`) that consumers can reference for TLS termination.

This chain proves that cert-manager can issue and renew certificates through its standard controller, without requiring external PKI or public DNS.

### CrateCheck is the validation surface

CrateCheck validates the cert-manager path through its standard check framework. Checks cover: HelmRelease controller health, self-signed ClusterIssuer readiness, CA Certificate readiness, CA ClusterIssuer readiness, TLS Certificate readiness, and TLS Secret existence. CrateCheck's ClusterRole is extended to read cert-manager resources (HelmRelease, ClusterIssuer, Certificate, Secrets).

### Acceptance evidence is operational and end-to-end

Static rendering and OpenSpec validation are required but not sufficient. Runtime success requires kind-first operational evidence:

1. intended Kubernetes context targets `kind-dev-misc-local`;
2. cert-manager namespace, controller resources, and CRDs exist;
3. cert-manager controller workload is ready;
4. self-signed ClusterIssuer is ready;
5. CA Certificate is issued and ready;
6. CA ClusterIssuer is ready;
7. TLS Certificate is issued and ready;
8. TLS Secret exists;
9. CrateCheck reports cert-manager checks as green;
10. a red test intentionally breaks the cert-manager path, verifies CrateCheck reports cert-manager checks as non-green, then restores green.

## Risks / Trade-offs

- [Risk] Local self-signed CA is not suitable for production → Mitigation: explicitly scope this as kind-first smoke only; production issuer policy is deferred.
- [Risk] Certificate issuance could be claimed by resource existence alone → Mitigation: require CrateCheck to validate the full chain and prove failure detection with a red test.
- [Risk] cert-manager install may become tangled with bootstrap installation → Mitigation: keep cert-manager reconciled through GitOps-managed operation only.
- [Risk] TLS Secret in `cratecheck` namespace could confuse consumers → Mitigation: document it as smoke evidence only; production TLS binding is deferred.
