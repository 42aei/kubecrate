## Context

The first installable slice established Flux bootstrap installation and GitOps-managed operation without ESO. The validation status app change defines an application service fixture with a secret-loading check that later platform service slices can enable. Backlog 0015 is the first concrete secret-handling platform service follow-up: prove that a consumer receives a narrowed Secret through External-Secrets Operator rather than reading broad bootstrap input material directly.

This change intentionally stays kind-first and production-inspired but not production-ready. It proves the platform capability with local Kubernetes source material and a real application service read path. Provider-specific external backends, production credential onboarding, rotation policy, and multi-environment promotion are deferred until there is a concrete operational need.

## Goals / Non-Goals

**Goals:**

- Add ESO as the next real GitOps-managed platform service for `kind-dev-misc-local`.
- Keep ESO independent from bootstrap installation acceptance while preserving handoff into GitOps-managed operation.
- Use `core-external-secrets-operator` as the dedicated ESO namespace.
- Prove projection from local operator-supplied or locally seeded Kubernetes Secret material into a narrow service-specific Secret.
- Wire the existing generic kubecrate validation status application service to consume the projected Secret and report a green secret-loading check in the status UI and status JSON. Do not create a separate ESO-specific status app.
- Provide AI-runnable validation evidence that distinguishes ESO controller health, SecretStore or ClusterSecretStore readiness, ExternalSecret readiness, target Secret creation, application environment or volume wiring, and application read behavior.
- Include a red test that intentionally breaks the ESO secret-loading path and proves the existing generic status app reports the check as non-green with useful diagnostics, then restore and verify green again.

**Non-Goals:**

- Making ESO bootstrap-critical for the first GitOps handoff.
- Installing or validating cloud secret providers, Vault, production credential stores, or real production secret material.
- Defining a complete secret-management policy, rotation model, multi-tenant tenancy model, or application developer self-service API beyond the smoke projection path.
- Replacing the Flux SSH deploy-key bootstrap contract from the first installable slice.
- Introducing ingress, certificate management, observability, Kyverno, or wave-like promotion mechanics.

## Decisions

### ESO is a GitOps-managed platform service

ESO is operator-owned secret projection infrastructure and is therefore platform services scope. It is installed after the GitOps handoff through the existing `kind-dev-misc-local` entrypoint, not as a prerequisite for bootstrap installation.

The reusable service definition lives at `platform-services/external-secrets-operator/base/`. The concrete cluster binding lives at `clusters/kind-dev-misc-local/platform-services/external-secrets-operator/`. The cluster entrypoint includes Flux `Kustomization` objects for the ESO controller, the ESO smoke resources, and the kubecrate status application service so Flux reconciles ESO through GitOps-managed operation with explicit ordering.

The ESO controller `Kustomization` reconciles only the ESO namespace, HelmRepository, HelmRelease, and values. The smoke `Kustomization` depends on the controller `Kustomization` before applying the SecretStore and ExternalSecret custom resources. The kubecrate status application service `Kustomization` then depends on the smoke `Kustomization` before rolling the consumer that reads the projected Secret. This keeps the GitOps-managed operation path normal for Flux while avoiding a single reconciliation root that requires SecretStore or ExternalSecret mappings before ESO CRDs and the controller have been installed.

Bootstrap installation may document any prerequisite seed input expected after handoff, but bootstrap installation does not install ESO or own its lifecycle in this slice. That keeps lifecycle phase separate from workload category and preserves the point at a cluster and install contract from the first slice.

### Namespace follows the core service rule

ESO uses namespace `core-external-secrets-operator`. This is the first non-Flux dedicated platform service namespace and follows the `core-<service-name>` rule. The Flux `flux-system` exception remains limited to the GitOps controller bootstrap or self-management path and does not extend to ESO.

### Local provider proves real projection

The acceptance proof uses the ESO Kubernetes provider, or an equivalent local provider with the same capability, to read source material from Kubernetes Secret state and project a narrower Secret for the validation app. This proves the local trust-material flow without requiring cloud credentials or a production backend.

The source Secret is local smoke material only. It must be non-sensitive fixture data, clearly named as validation material, and scoped so it does not look like a reusable production credential store. If a setup command creates or refreshes that source material, it must avoid printing or committing raw private credential material.

The Fake provider may be included only as supplemental demo or developer convenience. It does not satisfy acceptance by itself because it does not prove projection from operator-supplied or locally seeded trust material.

### Generic kubecrate status app is the consumer proof

The kubecrate validation status app remains the generic application services fixture for platform-service validation. This change enables its existing secret-loading check by wiring the app to read the ESO-projected target Secret. The app must not read the broad source Secret directly. This change must not create an ESO-specific status app or service-specific dashboard; ESO success is reflected as one check in the generic kubecrate status app.

The status UI and status JSON show a green secret-loading check only when the application has actually loaded the projected target Secret through its documented application wiring. Non-green output should guide the operator toward the likely layer: ESO controller health, provider readiness, ExternalSecret status, target Secret creation, app environment or volume wiring, or app read behavior.

### Acceptance evidence is operational and end-to-end

Static rendering and OpenSpec validation are required but not sufficient. Before running live ESO validation, the operator must ensure `GitRepository/flux-system` is reconciling the repository URL and implementation branch declared in `clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync.yaml`, and that this revision actually contains the ESO controller Kustomization, ESO smoke Kustomization, and updated kubecrate status app. For this pass, the expected repository URL is `ssh://git@github.com/42aei/kubecrate.git` and the expected branch is `wt/t_afaafb28`, the review/QA-visible implementation branch for this fix pass; a cluster still pinned to an older branch, a different repository, or a branch that has not been pushed to that repository cannot prove this ESO slice through GitOps-managed operation until that Git-managed source has been reconciled or otherwise updated by an authorized operator action.

The safe validation path is therefore explicit: render the local entrypoint first, verify the live `GitRepository/flux-system` `spec.url` and `spec.ref.branch` match `helm-values-sync.yaml`, verify the live applied revision contains the rendered child Flux Kustomizations (`external-secrets-operator`, `external-secrets-operator-smoke`, and `kubecrate-status`), and only then claim live ESO validation. If any of those source/revision checks fail, the validation result is blocked on publishing or reconciling the reviewed implementation branch rather than on ESO behavior itself.

Runtime success requires kind-first operational evidence after reconciliation:

1. intended Kubernetes context targets `kind-dev-misc-local`;
2. ESO namespace, controller resources, and CRDs exist;
3. ESO controller workload is ready;
4. SecretStore or ClusterSecretStore is ready;
5. ExternalSecret is ready and has reconciled;
6. target Secret exists in the validation app namespace and contains only the intended narrow smoke key or keys;
7. validation app workload has rolled out after secret wiring changes;
8. status JSON reports the secret-loading check as `green`;
9. status UI shows the same operator-visible secret-loading outcome;
10. recent events or logs do not show blocking reconciliation or application read errors;
11. a red test intentionally breaks the ESO secret-loading path, verifies the generic status app reports `secret-loading` as non-green with diagnostic output, then restores the path and verifies green again.

Deeper diagnosis stays symptom-driven. For example, RBAC checks are useful when provider readiness or ESO logs point to authorization, but they are not required as a universal per-ServiceAccount checklist.

## Risks / Trade-offs

- [Risk] Local Kubernetes source material can be mistaken for a production secret source. → Mitigation: keep it explicitly smoke-only, use non-sensitive fixture data, and defer production provider contracts.
- [Risk] Secret projection could be claimed by target Secret existence alone. → Mitigation: require the generic kubecrate status app to read the projected Secret, report the enabled secret-loading check as green, and prove failure detection with a red test.
- [Risk] ESO install may become tangled with bootstrap installation. → Mitigation: keep ESO reconciled through GitOps-managed operation and state explicitly that bootstrap installation acceptance remains Flux handoff only.
- [Risk] The Kubernetes provider needs RBAC that is easy to over-broaden. → Mitigation: scope RBAC to the smoke source namespace and document any broader permission as out of scope unless a later change justifies it.


### Red test requirement

The implementation must include a controlled red test for the generic kubecrate status app. The red test should break the ESO secret-loading path in a reversible way, such as pointing the validation app check at a missing projected Secret, disabling or misnaming the ExternalSecret target, or otherwise removing the expected projected key without exposing sensitive data. During the red test, `/status.json` must report `secret-loading` as `red`, `yellow`, or another non-green state with diagnostics that identify the likely layer. After the test, the implementation must restore the expected configuration and verify the status app returns to green.
