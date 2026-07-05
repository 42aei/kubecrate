## 1. Repository authority and backlog hygiene

- [ ] 1.1 Keep this change scoped to backlog 0015 and the External-Secrets Operator smoke-test vertical slice.
- [ ] 1.2 Update `docs/backlog/0015-introduce-external-secrets-operator-secret-projection.md` status to `started` and reference `openspec/changes/introduce-external-secrets-operator-smoke/` as the active OpenSpec change.
- [ ] 1.3 Confirm this change preserves the required project language: platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install.
- [ ] 1.4 Confirm ESO remains platform services scope and the kubecrate validation status app remains application services scope.

Acceptance checks:
- Backlog 0015 frontmatter reflects that OpenSpec work has started.
- This change uses `core-external-secrets-operator` for the dedicated ESO platform service namespace.
- Bootstrap installation is described as a lifecycle phase and not as a service category.

## 2. Minimum ESO platform service implementation

- [ ] 2.1 Add the reusable ESO platform service base under `platform-services/external-secrets-operator/base/`.
- [ ] 2.2 Add the `kind-dev-misc-local` cluster binding under `clusters/kind-dev-misc-local/platform-services/external-secrets-operator/`.
- [ ] 2.3 Wire the ESO binding into the existing `clusters/kind-dev-misc-local/entrypoint` so Flux reconciles it through GitOps-managed operation.
- [ ] 2.4 Create namespace `core-external-secrets-operator` for ESO and keep Flux's `flux-system` namespace exception limited to Flux.
- [ ] 2.5 Keep ESO independent from bootstrap installation acceptance; do not install or own ESO from the bootstrap installation path in this slice.

Acceptance checks:
- ESO manifests render from the cluster entrypoint.
- ESO is installed and reconciled as platform services scope through GitOps-managed operation.
- No unrelated platform service or application service skeleton directories are added.

## 3. Local secret projection smoke path

- [x] 3.1 Define smoke-only local source material for ESO using the Kubernetes provider, or an equivalent local provider that proves projection from operator-supplied or locally seeded Kubernetes Secret material.
- [x] 3.2 Add the minimum SecretStore or ClusterSecretStore needed for the smoke path, with RBAC scoped to the smoke source material unless a broader permission is explicitly justified.
- [x] 3.3 Add an ExternalSecret that projects only the intended narrow smoke key or keys into the kubecrate validation status app namespace.
- [x] 3.4 Ensure the Fake provider is not the only acceptance proof if it is included for supplemental demo behavior.
- [x] 3.5 Avoid committing raw sensitive credential material; use non-sensitive fixture data for the smoke proof or a documented local seed command that keeps real material out of Git.

Acceptance checks:
- SecretStore or ClusterSecretStore readiness can be checked by an AI-runnable command.
- ExternalSecret readiness can be checked by an AI-runnable command.
- The target Secret is created in the validation app namespace and contains only the intended narrow smoke data.
- The validation app does not read the broad source Secret directly.

## 4. Generic kubecrate status app integration

- [x] 4.1 Enable the existing generic kubecrate status app secret-loading check for this slice; do not create an ESO-specific status app or service-specific dashboard.
- [x] 4.2 Wire the validation app to consume the ESO-projected target Secret through environment variables or a mounted volume, matching the smallest maintainable app implementation.
- [x] 4.3 Ensure app configuration changes trigger a pod rollout when the app reads secret wiring at process startup.
- [x] 4.4 Update the status JSON so the secret-loading check reports `green` only after the app actually loaded the projected Secret.
- [x] 4.5 Update the human status UI so the secret-loading check explains the validated path and distinguishes likely failure areas.
- [x] 4.6 Confirm the status app remains a generic platform-validation dashboard with checks for platform capabilities, not a dedicated ESO-only app.

Acceptance checks:
- Status JSON includes the existing generic status app check contract fields for the secret-loading check.
- The secret-loading check reports `green` only when the projected Secret is readable by the app.
- Non-green secret-loading output identifies likely next layers: ESO controller health, SecretStore or ClusterSecretStore readiness, ExternalSecret readiness, target Secret creation, application environment or volume wiring, or application read behavior.

## 5. AI-runnable validation and evidence

- [x] 5.1 Run `openspec validate introduce-external-secrets-operator-smoke --type change --strict --json --no-interactive` and resolve any errors.
- [x] 5.2 Run `openspec status --change introduce-external-secrets-operator-smoke --json` and confirm required artifacts are present.
- [x] 5.3 Run static rendering for the current kind-first local path entrypoint after runtime files are added.
- [x] 5.4 Validate the intended cluster context before applying or claiming runtime success.
- [ ] 5.5 Validate ESO namespace, CRDs, controller resources, controller readiness, SecretStore or ClusterSecretStore readiness, ExternalSecret readiness, target Secret creation, validation app rollout, status JSON, and status UI.
- [ ] 5.6 Check recent relevant events or logs for blocking ESO reconciliation or validation app secret-loading errors.
- [ ] 5.7 Run a controlled red test by intentionally breaking the ESO secret-loading path in a reversible, non-sensitive way; verify `/status.json` and the UI show `secret-loading` as non-green with useful diagnostics.
- [ ] 5.8 Restore the ESO secret-loading path after the red test and verify `/status.json` and the UI return to green.

Acceptance checks:
- OpenSpec validation succeeds.
- OpenSpec status reports proposal, design, spec, and tasks artifacts.
- Static rendering succeeds after runtime files exist.
- Runtime validation proves real consumption through the generic kubecrate status app, not only ESO installation or target Secret existence.
- Red-test evidence proves the status app detects ESO/secret-loading failure and recovers to green after restoration.
