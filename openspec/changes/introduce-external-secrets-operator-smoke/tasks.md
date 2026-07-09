## 1. Repository authority and backlog hygiene

- [x] 1.1 Keep this change scoped to backlog 0015 and the External-Secrets Operator smoke-test vertical slice.
- [x] 1.2 Update `docs/backlog/0015-introduce-external-secrets-operator-secret-projection.md` status to `started` and reference `openspec/changes/introduce-external-secrets-operator-smoke/` as the active OpenSpec change.
- [x] 1.3 Confirm this change preserves the required project language: platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install.
- [x] 1.4 Confirm ESO remains platform services scope and CrateCheck remains application services scope.

Acceptance checks:
- Backlog 0015 frontmatter reflects that OpenSpec work has started.
- This change uses `core-external-secrets-operator` for the dedicated ESO platform service namespace.
- Bootstrap installation is described as a lifecycle phase and not as a service category.

## 2. Minimum ESO platform service implementation

- [x] 2.1 Add the reusable ESO platform service base under `platform-services/external-secrets-operator/base/`.
- [x] 2.2 Add the `kind-dev-misc-local` cluster binding under `clusters/kind-dev-misc-local/platform-services/external-secrets-operator/`.
- [x] 2.3 Wire the ESO binding into the existing `clusters/kind-dev-misc-local/entrypoint` so Flux reconciles it through GitOps-managed operation.
- [x] 2.4 Create namespace `core-external-secrets-operator` for ESO and keep Flux's `flux-system` namespace exception limited to Flux.
- [x] 2.5 Keep ESO independent from bootstrap installation acceptance; do not install or own ESO from the bootstrap installation path in this slice.

Acceptance checks:
- ESO manifests render from the cluster entrypoint.
- ESO is installed and reconciled as platform services scope through GitOps-managed operation.
- No unrelated platform service or application service skeleton directories are added.

## 3. Local secret projection smoke path

- [x] 3.1 Define smoke-only local source material for ESO using the Kubernetes provider.
- [x] 3.2 Add the minimum SecretStore needed for the smoke path, with RBAC scoped to the smoke source material.
- [x] 3.3 Add an ExternalSecret that projects the smoke key into the `kubecrate-system` namespace.
- [x] 3.4 Avoid committing raw sensitive credential material; use non-sensitive fixture data for the smoke proof.

Acceptance checks:
- SecretStore readiness can be checked by an AI-runnable command.
- ExternalSecret readiness can be checked by an AI-runnable command.
- The target Secret is created and contains only the intended narrow smoke data.

## 4. CrateCheck ESO integration

- [x] 4.1 Extend CrateCheck check config (ConfigMap) with ESO checks: HelmRelease readiness, SecretStore readiness, ExternalSecret readiness, projected Secret existence.
- [x] 4.2 Extend CrateCheck ClusterRole with read access to ESO-related resources (HelmRelease, SecretStore, ExternalSecret, Secrets).
- [x] 4.3 Use CrateCheck as the single validation surface; do not create an ESO-specific status app.

Acceptance checks:
- CrateCheck check config includes ESO checks with valid severity, resource, and expression fields.
- CrateCheck ClusterRole grants read access to ESO resource types.
- ESO checks report green only when the full ESO path is healthy.

## 5. AI-runnable validation and evidence

- [x] 5.1 Run `openspec validate introduce-external-secrets-operator-smoke --type change --strict --json --no-interactive` and resolve any errors.
- [x] 5.2 Run `openspec status --change introduce-external-secrets-operator-smoke --json` and confirm required artifacts are present.
- [x] 5.3 Run static rendering for the current kind-first local path entrypoint after runtime files are added.
- [x] 5.4 Run kustomize build and kubeconform against the entrypoint.
- [ ] 5.5 Validate ESO namespace, CRDs, controller resources, controller readiness, SecretStore readiness, ExternalSecret readiness, target Secret creation, and CrateCheck ESO check output.
- [ ] 5.6 Check recent relevant events or logs for blocking ESO reconciliation errors.
- [ ] 5.7 Run a controlled red test by intentionally breaking the ESO projection path in a reversible, non-sensitive way; verify CrateCheck reports ESO checks as non-green with useful diagnostics.
- [ ] 5.8 Restore the ESO projection path after the red test and verify CrateCheck returns ESO checks to green.

Acceptance checks:
- OpenSpec validation succeeds.
- OpenSpec status reports proposal, design, spec, and tasks artifacts.
- Static rendering succeeds after runtime files exist.
- Runtime validation proves real ESO secret projection through CrateCheck, not only ESO installation or target Secret existence.
- Red-test evidence proves CrateCheck detects ESO failure and recovers to green after restoration.
