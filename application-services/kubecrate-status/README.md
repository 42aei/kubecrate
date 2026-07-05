# kubecrate status check modules

The kubecrate status app is the generic application service fixture used by
platform service slices. It must stay generic: new platform services extend the
same `/status.json` and UI instead of creating service-specific status apps.

## Check module pattern

Status checks are configured in `application-services/kubecrate-status/base/status-config.yaml`.
Shared app/server behavior lives in `application-services/kubecrate-status/base/app-config.yaml`,
while check and diagnostic-layer implementations live in separate module files in
`application-services/kubecrate-status/base/check-modules-config.yaml`. The app
loads every `*.py` file from `/app/check-modules` in sorted order and exposes two
small registries:

- `@register_check("<type>")` registers a top-level check handler.
- `@register_layer("<type>")` registers a diagnostic layer handler that can be
  reused by layered capability checks.

The stable `/status.json` fields for every check are:

- `id`
- `name`
- `capability`
- `area`
- `enabled`
- `troubleshooting`
- `state`
- `summary`
- optional `observed`

Use `not_configured` with `enabled: false` for reserved future checks. Unknown
enabled check types intentionally return a yellow check with the registered type
list in `observed` so misconfigured slices are visible without crashing the whole
status payload.

## Where future slice changes should live

Prefer these minimal additions for each platform service slice:

1. Reuse before adding: enable a reserved check by composing existing
   `condition`, `target_secret`, `volume_mount`, `file`, `service_endpoints`,
   `http_probe`, `gateway_listener`, or `httproute_attachment` layers in the
   slice-owned cluster binding. This path does not edit app code.
2. New app code: if a new evidence type is unavoidable, add one focused module
   key such as `<capability>_layers.py` to
   `application-services/kubecrate-status/base/check-modules-config.yaml`; do
   not add broad conditionals to `app-config.yaml`.
3. Base placeholders: keep the reserved check id in
   `application-services/kubecrate-status/base/status-config.yaml` as
   `not_configured` until a slice enables it.
4. Slice config: enable the reserved check from the platform-service slice by
   patching or replacing the kubecrate status config in the cluster binding,
   rather than editing unrelated checks.
5. App wiring: if a check needs files, env, volumes, or a Service route, patch
   the generic `kubecrate-status` Deployment or Service from the slice-specific
   cluster binding.
6. RBAC: add the narrowest required RBAC as a small slice-owned manifest or
   patch next to the cluster binding; avoid expanding the base reader role for
   resources that are only needed by one service slice.
7. Tests: add a focused `tests/status_app_<capability>_test.py` covering the
   registered handler/layers and `/status.json` contract impact.

Keep check ids stable so UI/browser QA and automation can track the same
capability across branches:

- `secret-loading`
- `ingress-reachability`
- `certificate-tls-status`
- `policy-behavior`
- `observability-signal-path`

## Migration notes for active/follow-up branches

- ESO secret projection should keep the `secret-loading` check id and can be
  implemented config/RBAC/wiring-only by enabling the existing `secret_loading`
  handler plus `condition`, `target_secret`, `volume_mount`, and `file` layers.
  Move ESO-specific config, volume wiring, and Secret RBAC into the ESO slice
  binding rather than the base generic status app.
- Envoy Gateway should keep the `ingress-reachability` check id and can be
  implemented config/RBAC/wiring-only by enabling the existing
  `ingress_reachability` handler plus `gateway_listener`,
  `httproute_attachment`, `service_endpoints`, and `http_probe` layers. Keep
  Gateway/HTTPRoute config in the Envoy slice binding.
- cert-manager should keep the `certificate-tls-status` check id. Use the
  generic `layered` check with `condition`, `target_secret`, and `http_probe`
  first. If real TLS parsing becomes necessary, add only a focused
  `certificate_layers.py` module in `check-modules-config.yaml` and a matching
  focused test.
- Kyverno should keep the `policy-behavior` check id. Use `condition` and
  Kubernetes API evidence first. If policy report/admission evidence needs a
  custom reader, add only a focused `policy_layers.py` module and keep policy
  fixture resources in the Kyverno slice binding.
- Observability should keep the `observability-signal-path` check id. Use
  `condition`, `service_endpoints`, and `http_probe` first. If backend queries
  are required, add only a focused `observability_layers.py` signal/query module.
