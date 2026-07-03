## Context

Kubecrate has a Flux-first kind-first local path and a growing set of planned platform services. The project now needs a reusable proof surface so each future platform service can demonstrate real application consumption without creating a bespoke demo workload every time.

Backlog 0014 defines the fixture: a deliberately small but polished status panel app with both human-readable and machine-readable status output. The app should make failures easier for AI agents and humans to localize by explaining what each check validates and which layer is likely broken when the check is not green.

## Goals / Non-Goals

**Goals:**

- Create a reusable application service fixture for platform service validation.
- Provide a polished status panel UI instead of a blank nginx page or single-purpose curl target.
- Provide a stable status JSON endpoint suitable for AI-runnable checks.
- Include structured check metadata: status, capability, exercised area, observed value, expected value, and troubleshooting guidance.
- Start with base app health as the only required green platform-independent check.
- Include disabled or not-configured check definitions for future capabilities so later slices can turn them on without changing the conceptual model.
- Place the fixture using the application services layout: reusable base plus `kind-dev-misc-local` cluster binding.
- Keep implementation minimal and kind-first.

**Non-Goals:**

- Do not introduce ESO, Envoy Gateway, cert-manager, observability, Kyverno, or other platform services in this change.
- Do not require ingress, TLS, projected Secrets, observability backends, or policy engines for this app to be initially healthy.
- Do not make the validation app part of bootstrap installation.
- Do not create generic empty application service skeleton directories beyond the files required for this concrete fixture.
- Do not solve multi-environment promotion or external production hosting.

## Decisions

### Implement a small application service rather than static nginx

The validation fixture should be a small application service with explicit status logic rather than a static nginx page. A minimal Go or Node app is acceptable; the implementation change should choose the smallest maintainable option available in the repo context.

Static nginx is rejected as the default because the fixture needs a structured JSON contract, per-check explanations, and future capability checks that would become awkward as static content.

### Status model uses explicit check states

Each check should expose a stable shape in JSON and corresponding UI display. The first states should be:

- `green`: capability check is enabled and passing;
- `red`: capability check is enabled and failing;
- `yellow`: capability check is enabled but inconclusive or partially degraded;
- `not_configured`: capability is known to the app but not enabled in the current slice.

This lets the initial app be useful before ESO, ingress, cert-manager, observability, or policy exist. Future slices can change specific checks from `not_configured` to live checks when the relevant platform service is introduced.

### Initial required check is base app health

The first implementation should only require the base app health check to be green. It may expose future check categories as `not_configured`, but those categories must not fail the first slice just because the platform service does not exist yet.

This avoids coupling 0014 to the platform service tasks that depend on it.

### Placement follows application service layout

The validation app is an application service because it consumes platform services. Its reusable definition should live under `application-services/<service>/base/`, and its kind-first cluster binding should live under `clusters/kind-dev-misc-local/application-services/<service>/`.

This change is allowed to introduce those concrete paths only for the validation app. It should not create broad empty application-services skeletons.

### GitOps-managed operation owns runtime reconciliation

The validation app should be reconciled through the existing `clusters/kind-dev-misc-local/entrypoint` path after Flux is ready. It should not be installed by bootstrap installation. The cluster entrypoint may reference the app's cluster binding as part of GitOps-managed operation.

### AI-runnable validation targets status JSON first

The primary AI-runnable validation path should fetch and parse the status JSON endpoint, because JSON gives deterministic output for agents and scripts. The UI should also be fetchable or viewable for humans, but the JSON endpoint is the validation contract.

If the app is not yet exposed by ingress, validation may use a local `kubectl port-forward` or equivalent bounded command. Later ingress and certificate tasks can replace or augment that path with externally reachable checks.

## Risks / Trade-offs

- [Risk] The validation app becomes a platform product instead of a test fixture. → Mitigation: keep it explicitly scoped as an application service fixture and avoid unrelated features.
- [Risk] Future checks are over-designed before their platform services exist. → Mitigation: define check categories and metadata now, but only require live behavior for capabilities enabled by the current slice.
- [Risk] Runtime files expand the repo too much. → Mitigation: create only the concrete validation app paths authorized by this change.
- [Risk] JSON schema churn breaks future AI validation. → Mitigation: define a stable minimum status JSON contract in the spec and require additive evolution where possible.
