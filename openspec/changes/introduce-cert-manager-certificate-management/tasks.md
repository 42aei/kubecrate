## 1. Repository authority and backlog hygiene

- [x] 1.1 Keep this change scoped to backlog 0017 and the cert-manager certificate management vertical slice.
- [x] 1.2 Update `docs/backlog/0017-introduce-cert-manager-certificate-management.md` status to `started` and reference `openspec/changes/introduce-cert-manager-certificate-management/` as the active OpenSpec change.
- [x] 1.3 Confirm this change preserves the required project language: platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install.
- [x] 1.4 Confirm cert-manager remains platform services scope and CrateCheck remains application services scope.

Acceptance checks:
- Backlog 0017 frontmatter reflects that OpenSpec work has started.
- This change uses `core-cert-manager` for the dedicated cert-manager platform service namespace.
- Bootstrap installation is described as a lifecycle phase and not as a service category.

## 2. Minimum cert-manager platform service implementation

- [x] 2.1 Add the reusable cert-manager platform service base under `platform-services/cert-manager/base/`.
- [x] 2.2 Add the `kind-dev-misc-local` cluster binding under `clusters/kind-dev-misc-local/platform-services/cert-manager/`.
- [x] 2.3 Wire the cert-manager binding into the existing `clusters/kind-dev-misc-local/entrypoint` so Flux reconciles it through GitOps-managed operation.
- [x] 2.4 Create namespace `core-cert-manager` for cert-manager and keep Flux's `flux-system` namespace exception limited to Flux.
- [x] 2.5 Keep cert-manager independent from bootstrap installation acceptance; do not install or own cert-manager from the bootstrap installation path.

Acceptance checks:
- cert-manager manifests render from the cluster entrypoint.
- cert-manager is installed and reconciled as platform services scope through GitOps-managed operation.
- No unrelated platform service or application service skeleton directories are added.

## 3. Local issuer and TLS certificate path

- [x] 3.1 Define a self-signed ClusterIssuer as the trust anchor.
- [x] 3.2 Create a CA Certificate issued by the self-signed ClusterIssuer.
- [x] 3.3 Create a CA-based ClusterIssuer backed by the CA Certificate Secret.
- [x] 3.4 Create a smoke TLS Certificate for CrateCheck issued by the CA ClusterIssuer.
- [x] 3.5 Avoid committing sensitive certificate material; rely on cert-manager to generate keys and certificates at runtime.

Acceptance checks:
- Self-signed ClusterIssuer readiness can be checked by an AI-runnable command.
- CA Certificate readiness can be checked by an AI-runnable command.
- CA ClusterIssuer readiness can be checked by an AI-runnable command.
- TLS Certificate readiness can be checked by an AI-runnable command.
- TLS Secret is created and contains cert-manager-managed TLS material.

## 4. CrateCheck cert-manager integration

- [x] 4.1 Extend CrateCheck check config (ConfigMap) with cert-manager checks: HelmRelease readiness, self-signed ClusterIssuer readiness, CA Certificate readiness, CA ClusterIssuer readiness, TLS Certificate readiness, TLS Secret existence.
- [x] 4.2 Extend CrateCheck ClusterRole with read access to cert-manager resources (HelmRelease, ClusterIssuer, Certificate, Secrets).
- [x] 4.3 Extend CrateCheck validation tests with cert-manager check ID presence and CEL dot-notation contract assertions.
- [x] 4.4 Use CrateCheck as the single validation surface; do not create a cert-manager-specific status app.

Acceptance checks:
- CrateCheck check config includes cert-manager checks with valid severity, resource, and expression fields.
- CrateCheck ClusterRole grants read access to cert-manager resource types.
- cert-manager checks report green only when the full certificate path is healthy.
- validate-cratecheck.py passes all cert-manager contract checks.

## 5. AI-runnable validation and evidence

- [x] 5.1 Run `openspec validate introduce-cert-manager-certificate-management --type change --strict --json --no-interactive` and resolve any errors.
- [x] 5.2 Run static rendering for the current kind-first local path entrypoint.
- [x] 5.3 Run kustomize build and kubeconform against the entrypoint.
- [x] 5.4 Run validate-cratecheck.py to confirm all checks pass.
- [ ] 5.5 Validate cert-manager namespace, CRDs, controller resources, controller readiness, ClusterIssuer readiness, Certificate readiness, TLS Secret creation, and CrateCheck cert-manager check output.
- [ ] 5.6 Check recent relevant events or logs for blocking cert-manager reconciliation errors.
- [ ] 5.7 Run a controlled red test by intentionally breaking the cert-manager path in a reversible way; verify CrateCheck reports cert-manager checks as non-green with useful diagnostics.
- [ ] 5.8 Restore the cert-manager path after the red test and verify CrateCheck returns cert-manager checks to green.

Acceptance checks:
- OpenSpec validation succeeds.
- Static rendering succeeds.
- Runtime validation proves real cert-manager certificate issuance through CrateCheck.
- Red-test evidence proves CrateCheck detects cert-manager failure and recovers to green after restoration.
