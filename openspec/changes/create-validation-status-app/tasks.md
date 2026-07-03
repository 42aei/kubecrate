## 1. Repository authority and backlog hygiene

- [ ] 1.1 Keep this change scoped to the validation application service fixture from backlog 0014, preserving the two-axis model and required project language.
- [ ] 1.2 Update `docs/backlog/0014-create-application-service-validation-status-app.md` status to `started` and reference `openspec/changes/create-validation-status-app/` as the active OpenSpec change.
- [ ] 1.3 Confirm this change does not add ESO, Envoy Gateway, cert-manager, observability, Kyverno, or other platform service implementations.

Acceptance checks:
- Backlog 0014 frontmatter reflects that OpenSpec work has started.
- Runtime additions are limited to the concrete validation app fixture and its required binding.
- The validation app is described as application services scope, not platform services scope.

## 2. Application service fixture implementation

- [ ] 2.1 Choose the smallest maintainable implementation approach for the validation app, such as a minimal Go or Node app, and document the choice in implementation notes or code comments where useful.
- [ ] 2.2 Implement the status UI as a polished status panel page with overall status, individual checks, descriptions, and troubleshooting guidance.
- [ ] 2.3 Implement the status JSON endpoint with stable top-level fields and per-check fields required by the spec.
- [ ] 2.4 Implement initial check categories for base app health, secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior.
- [ ] 2.5 Ensure the base app health check reports `green` when the app is healthy and future platform service checks report `not_configured` unless explicitly enabled by a later slice.

Acceptance checks:
- The UI can be fetched and shows a useful status panel rather than a blank or placeholder page.
- The JSON endpoint returns `app`, `version`, `overallStatus`, and `checks`.
- Each check includes `id`, `name`, `state`, `capability`, `area`, `enabled`, `summary`, and `troubleshooting`.
- `state` values are limited to `green`, `yellow`, `red`, or `not_configured`.

## 3. Runtime layout and GitOps-managed operation

- [ ] 3.1 Add the reusable validation app definition under `application-services/<service>/base/` without creating unrelated empty application service skeletons.
- [ ] 3.2 Add the `kind-dev-misc-local` cluster binding under `clusters/kind-dev-misc-local/application-services/<service>/`.
- [ ] 3.3 Wire the validation app into the existing `clusters/kind-dev-misc-local/entrypoint` so Flux reconciles it through GitOps-managed operation.
- [ ] 3.4 Keep bootstrap installation unchanged; do not install or manage the validation app from bootstrap installation.

Acceptance checks:
- `kustomize build clusters/kind-dev-misc-local/entrypoint` renders the validation app resources successfully.
- The app resources are included through the cluster entrypoint and not through bootstrap installation.
- No unrelated application service directories or platform service directories are added.

## 4. AI-runnable validation and evidence

- [ ] 4.1 Add or document commands to validate the app on the kind-first local path, including how to reach the status JSON before ingress exists, such as with a bounded `kubectl port-forward` flow.
- [ ] 4.2 Add a JSON validation command or script that asserts the base app health check is `green` and future platform service checks do not fail the slice when `not_configured`.
- [ ] 4.3 Capture operational evidence categories for validation: intended cluster context, expected application service resources, workload health, readiness, recent blocking events/logs when relevant, and status output.
- [ ] 4.4 Keep deeper troubleshooting symptom-driven and avoid requiring unrelated checks for platform services that this slice does not install.

Acceptance checks:
- An AI agent can run the documented commands to fetch and validate the status JSON.
- The validation commands fail clearly if the app is not reconciled, not reachable, or returns invalid status JSON.
- Operational evidence is collected before success is claimed.

## 5. OpenSpec and repository validation

- [ ] 5.1 Run `openspec validate create-validation-status-app --type change --strict --json --no-interactive` and resolve any errors.
- [ ] 5.2 Run `openspec status --change create-validation-status-app --json` and confirm required artifacts are present.
- [ ] 5.3 Run static rendering for the current kind-first local path entrypoint after runtime files are added.
- [ ] 5.4 Run the AI-runnable validation app checks against a reconciled kind-first local path before marking implementation complete.

Acceptance checks:
- OpenSpec validation succeeds.
- OpenSpec status reports the proposal, design, spec, and tasks artifacts.
- Static rendering succeeds.
- Runtime validation proves the status UI and JSON work on the kind-first local path.
