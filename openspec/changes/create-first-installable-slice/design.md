## Context

Backlog 0008 is the forcing implementation change for Kubecrate. Prior OpenSpec changes `define-install-flow` and `define-gitops-component-management` established contracts, boundaries, and deferred decisions that 0008 now resolves with concrete runtime files. The project has no runtime files yet, and the AGENTS.md phase guardrails reflect a planning-only pass that 0008 overrides for its own implementation scope.

The accepted 0008 direction establishes Flux as the first GitOps controller, Kustomize-first bootstrap, Seed Secrets/ESO ordering, Flux self-management, a concrete runtime layout, kind plumbing, and a tracer bullet validation requirement. This design defines how those accepted inputs come together as a coherent, minimal vertical slice.

## Goals / Non-Goals

**Goals:**

- Define the smallest concrete tracer bullet: prepared kind cluster → Kustomize-first bootstrap → ESO Seed Secrets projection → Flux handoff/self-management → Flux-managed update evidence.
- Define exact lifecycle boundaries for what bootstrap installation owns versus what kind plumbing owns versus what GitOps-managed operation owns.
- Define the file model, source-of-truth rules, Seed Secrets/ESO ordering constraints, and Flux self-management handoff mechanics.
- Define the kind validation boundary: what plumbing the repository owns, what commands operators run, and where bootstrap installation starts.
- Define the validation/evidence plan for the tracer bullet, including the update-proving step.
- Minimize horizontal enabling work: all enabling setup serves the tracer bullet, not broad layout-first phases.

**Non-Goals:**

- Ingress, certificate management, observability, policy, wave-like promotion policy/gating.
- Template/example repository indirection or multi-repository source models.
- Provider-specific clusters beyond the kind-first local path.
- Helm-based bootstrap packaging.
- ESO Fake provider configuration.
- Full platform service catalog or application service definitions beyond the tracer bullet need.

## Decisions

### Tracer bullet is the first implementation task

The first implementation task is the tracer bullet: prepared kind cluster → Kustomize-first bootstrap installation → ESO Seed Secrets projection → Flux handoff/self-management → Flux-managed update evidence. All other tasks are minimum enabling steps nested inside the tracer bullet task, not standalone horizontal phases.

The tracer bullet deploys a concrete minimal platform service named `tracer-echo` whose sole purpose is to prove GitOps reconciliation: bootstrap installs it at version X, then a Git-managed change (image tag or config value) bumps it to version Y, and Flux reconciles the update. `tracer-echo` does not provide ingress, certificate management, observability, or policy—it exists only to demonstrate the reconciliation loop works end-to-end.

This ensures the first reviewable increment proves the entire vertical slice works end-to-end. Horizontal setup (kind plumbing, directory layout, bootstrap manifests) is scoped to what the tracer bullet needs, not a broad foundation.

Alternatives considered:
- Lay out all directories, manifests, and plumbing before the tracer bullet. Rejected because it delays the first working proof and risks building scaffolding the tracer bullet never exercises.
- Start with kind plumbing alone. Rejected because kind plumbing is enabling infrastructure, not the product experience.

### Lifecycle boundaries: kind plumbing, bootstrap installation, GitOps-managed operation

Three distinct lifecycle boundaries exist in 0008:

1. **Kind plumbing** (outside bootstrap installation): repository-owned kind config, prerequisite docs/checks, setup commands (Make targets or equivalent), teardown/recreate expectations, and evidence commands. Kind cluster creation and preparation validates the local environment but does not install Kubecrate. The kubernetes API is reachable and the operator has usable credentials at the end of kind plumbing.

2. **Bootstrap installation** starts when kind plumbing completes and the operator runs `point at a cluster and install` against a reachable Kubernetes API with usable credentials. Bootstrap installs ESO (bootstrap-critical, before Flux), creates the `seed-secrets` Secret in the ESO namespace, applies the Kustomize-first Flux desired-state path (which Flux will later reconcile), and hands off to GitOps-managed operation once Flux is running and self-managing.

3. **GitOps-managed operation** begins after Flux handoff. Flux reconciles the same desired-state path bootstrap applied. Flux self-manages its own configuration. Platform services (beyond ESO, which is bootstrap-critical) are GitOps-managed.

Bootstrap is a lifecycle phase, not a service category. ESO is bootstrap-critical for 0008, installed during bootstrap, and is not a GitOps-managed management unit in this slice.

Alternatives considered:
- Collapse kind plumbing into bootstrap installation. Rejected because it conflates environment preparation with lifecycle management.
- Install ESO as GitOps-managed after Flux handoff. Rejected because Flux needs projected Git credentials from ESO to reconcile. ESO must be running before Flux.

### Kustomize-first bootstrap path

Bootstrap installation uses `kubectl apply -k` (or a very thin wrapper) against a Kustomize overlay directory. The bootstrap Kustomization references Flux's desired-state Kustomization path so that what bootstrap applies is the same path Flux later reconciles.

The bootstrap entrypoint is a single Kustomize overlay that:
- Installs ESO via a Kustomize resource or inline manifest reference
- Creates the `seed-secrets` Secret in the ESO namespace
- References the Flux desired-state path (which includes Flux's own installation manifests and the cluster entrypoint)
- Does not embed a separate copy of Flux manifests

Helm is not the bootstrap package for this slice. HelmRelease remains appropriate inside GitOps-managed operation for Helm-native platform services.

Alternatives considered:
- Use Helm for bootstrap. Rejected per accepted 0008 direction: Kustomize is the bootstrap interface, HelmRelease is for GitOps-managed services.
- Use `kubectl apply -f` with raw manifests. Rejected because Kustomize overlays provide environment-specific binding without duplicating base definitions.

### Seed Secrets and ESO ordering

Seed Secrets are the operator-provided local input path. No real `.env` file is committed. Only an example env file (`seed-secrets.env.example`) is committed, with placeholder values and usage documentation. The real env file (`seed-secrets.env`) is in `.gitignore`. Bootstrap installation materializes one Secret named `seed-secrets` in the ESO namespace via a thin wrapper or documented command such as `kubectl create secret generic seed-secrets -n eso --from-env-file=seed-secrets.env --dry-run=client -o yaml | kubectl apply -f -`. The secret contains credentials that ESO projects, including Git credentials Flux needs to reconcile.

ESO is bootstrap-critical and installed before Flux. The ESO ClusterSecretStore or SecretStore definition references the bootstrap-created `seed-secrets` Secret using the Kubernetes provider (or equivalent local provider that can read a bootstrap-created Kubernetes Secret). The Fake provider does not validate this path because it does not read `seed-secrets`.

The ordering is:
1. Bootstrap applies ESO manifests (Kustomize overlay or inline reference)
2. Bootstrap creates the `seed-secrets` Secret in the ESO namespace
3. Bootstrap applies the ESO ClusterSecretStore referencing `seed-secrets`
4. Bootstrap applies the Flux desired-state path (Flux manifests reference ESO-projected credentials)
5. Flux starts, reads projected credentials from ESO, reconciles

Services and controllers consume narrow ESO-projected Secrets, not the raw `seed-secrets` Secret. The `seed-secrets` Secret is the single operator-provided input; all other secrets are derived via ESO projection.

Alternatives considered:
- Use ESO Fake provider. Rejected because Fake does not read the bootstrap-created `seed-secrets` Secret and therefore does not validate the Seed Secrets projection path.
- Commit a real `.env` file. Rejected because it violates the security boundary: operator-provided credentials must not be committed.

### Flux self-management handoff

Flux self-management means Flux reconciles its own installation from the same desired-state path that bootstrap applied. The bootstrap Kustomize overlay does not embed a separate Flux definition. It references the same Flux manifests in the cluster's platform services path that Flux will later reconcile.

The handoff sequence:
1. Bootstrap applies the Flux desired-state path via `kubectl apply -k <bootstrap-overlay>`
2. The bootstrap overlay includes or references Flux manifests (controller, CRDs, RBAC)
3. Flux starts, finds itself in the desired-state path, and becomes self-managing
4. Subsequent changes to Flux configuration in the desired-state path are reconciled by Flux itself

There is one source of truth for Flux configuration: the cluster's platform services path under `clusters/<cluster>/platform-services/flux.yaml` (or equivalent). Bootstrap does not maintain a duplicate.

Alternatives considered:
- Bootstrap installs Flux independently, then Flux reconciles a different path. Rejected because it creates two sources of truth for Flux configuration.
- Bootstrap installs a "boot" Flux that installs a "real" Flux. Rejected as unnecessary indirection for the kind-first local path.

### Flux Git source contract for kind

Flux reconciles this repository's HTTPS remote and the current implementation branch. The Flux `GitRepository` resource points to the repository's HTTPS URL (e.g., `https://github.com/<org>/kubecrate.git`) with the branch set to the implementation branch for this change. Git credentials (HTTPS username/token or equivalent) are supplied through `seed-secrets` and projected via ESO ExternalSecret into a Secret referenced by the Flux `GitRepository`. Validation requires a commit and push to the implementation branch; Flux detects the change and reconciles.

Local Git server alternatives (e.g., `git daemon` or Gitea running in kind) are secondary and explicitly out of the default path for this slice. The HTTPS remote path is the recommended default because it validates the real credential projection model without additional infrastructure.

### Runtime layout

The concrete runtime layout for 0008 is:

```
platform-services/
  tracer-echo/                 # Minimal tracer-only GitOps-managed platform service
    base/
      kustomization.yaml
      deployment.yaml
  ...

clusters/
  <cluster>/
    entrypoint/
      kustomization.yaml       # First GitOps reconciliation root
    platform-services/
      <service>.yaml           # Cluster binding: enablement, config, version
```

- `platform-services/<service>/base/` holds reusable, cluster-agnostic service definitions. `tracer-echo` is the first concrete service under this layout.
- `clusters/<cluster>/platform-services/<service>.yaml` holds cluster-specific enablement, configuration, and version binding for each service.
- `clusters/<cluster>/entrypoint/` is the first GitOps reconciliation root for that cluster. Flux reconciles from this path.

The first concrete cluster is `kind-dev-misc-local`, following the `<provider>-<environment>-<workload>-<location>` naming convention.

Do not make `platform-services/<service>/kind` the default pattern. Introduce reusable variants only if later duplication justifies them.

Alternatives considered:
- `platform-services/<service>/kind/` as default. Rejected per accepted 0008 direction: concrete cluster binding under `clusters/` avoids coupling service definitions to a provider.
- Single flat directory. Rejected because it does not separate reusable definitions from cluster-specific binding.

### Kind validation plumbing

Kind cluster creation and preparation are repository-owned local validation setup, not bootstrap installation. The plumbing includes:

- **kind config**: A kind cluster configuration file defining the `kind-dev-misc-local` cluster with sufficient resources for the tracer bullet.
- **Prerequisite checks**: Documentation or automated checks verifying kind, kubectl, and other prerequisites are installed and at compatible versions.
- **Setup commands**: Make targets or equivalent scripts that create the kind cluster from the config.
- **Teardown/recreate expectations**: Commands to delete and recreate the cluster for clean-slate validation.
- **Evidence commands**: Commands that capture cluster state for validation evidence (e.g., `kubectl get` output, Flux status, ESO status).

Bootstrap installation still starts only from a cluster with a reachable Kubernetes API and usable credentials. Kind plumbing delivers that starting point.

Alternatives considered:
- Embed kind creation in bootstrap scripts. Rejected because it conflates environment preparation with lifecycle management.
- Omit kind plumbing and rely on operator ad-hoc setup. Rejected because reproducible local validation requires a defined starting point.

### Tracer bullet validation

The tracer bullet proves GitOps-managed operation performs an update using `tracer-echo`, a minimal GitOps-managed platform service whose sole purpose is to demonstrate reconciliation:

1. **Baseline reconcile**: Bootstrap installs the full stack. Flux reconciles the desired state. Evidence confirms Flux is running, ESO is projecting secrets, and `tracer-echo` is deployed at version X (image tag `v0.1.0` or equivalent config value tracked in `clusters/kind-dev-misc-local/platform-services/tracer-echo.yaml`).
2. **Git-managed change**: The operator commits a version bump (e.g., `tracer-echo` image tag from `v0.1.0` to `v0.2.0`) in the cluster binding file and pushes to the implementation branch.
3. **Flux update evidence**: Flux detects the change, reconciles, and `tracer-echo` is upgraded to version Y. Evidence captures the before/after image tag, Flux reconciliation logs or status, and the updated pod running the new image.

Version X→Y is defined via a Git-managed image tag or config value with evidence commands: `kubectl get deployment tracer-echo -n <ns> -o jsonpath='{.spec.template.spec.containers[0].image}'` before and after the change.

The validation is operational/evidence-command based. Tests and checks focus on observable install/reconcile behavior rather than unit-test coverage.

Alternatives considered:
- TDD with unit/integration tests. Rejected as the primary method: validation is operational, proving the kind-first local path works end-to-end through evidence commands and observable behavior.

## Risks / Trade-offs

- [Risk] The Kustomize-first bootstrap path may become unwieldy as the number of bootstrap resources grows. → Mitigation: Kustomize overlays support composition. If complexity exceeds Kustomize's sweet spot, a later change can introduce a thin wrapper while preserving the overlay structure.
- [Risk] ESO Kubernetes provider reads Secrets from the same cluster, which some operators consider a security concern for production credential material binding. → Mitigation: this is production-inspired, not production-ready. The Kubernetes provider validates the Seed Secrets projection path for the kind-first local path. A real external provider can be introduced later without changing the projection model.
- [Risk] The tracer bullet may reveal unexpected Flux/ESO compatibility issues or version constraints. → Mitigation: use well-known compatible versions. Document the tested version matrix. If issues arise, they are resolved in the implementation task, not deferred.
- [Risk] Kind plumbing (Make targets, prerequisite checks) may drift from the actual operator workflow. → Mitigation: the tracer bullet exercises the plumbing end-to-end, keeping it honest. Evidence commands capture actual output.
- [Risk] The concrete runtime layout (`platform-services/<service>/base/`, `clusters/<cluster>/`) may need restructuring once multi-cluster or multi-provider scenarios appear. → Mitigation: this is a pragmatic first convention, not an immutable taxonomy. The layout is designed to accommodate growth, and restructuring is expected as the project matures.
