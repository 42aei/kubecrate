# kind Envoy Gateway ingress validation guide

Envoy Gateway runs as a GitOps-managed platform service in `core-envoy-gateway`, reconciled
through the reusable Vanilla composition at `compositions/vanilla/entrypoint/`. The kind-first
local path no longer owns a separate kind-local Envoy Gateway service binding.

The ingress vertical-slice proof — the smoke `EnvoyProxy` NodePort patch, GatewayClass,
Gateway, HTTPRoute, ReferenceGrant, and the CrateCheck status surface evaluated through the
ingress path — is consumer-side validation. It lives in the smoke suite at
[42aei/kubecrate-kind-smoke](https://github.com/42aei/kubecrate-kind-smoke):

- `platform-services/envoy-gateway/` holds the smoke fixtures. The `EnvoyProxy` resource pins
  NodePorts `30080` (HTTP) and `30443` (HTTPS) so host-mapped kind ports reach the smoke
  Gateway.
- `scripts/kind-smoke-e2e.sh` and the invokable `kind-smoke` workflow prove ingress end to end
  on a disposable kind cluster against a pinned kubecrate commit, including the
  controlled-red phase through CrateCheck `/status.json`.

## Static validation

```sh
python3 scripts/validate-kubernetes-manifests.py
python3 tests/validate-vanilla-composition.py
```

## Runtime validation

Validate a kubecrate substrate change against the smoke suite, locally or via its
`workflow_dispatch` kind CI:

```sh
git clone https://github.com/42aei/kubecrate-kind-smoke.git
cd kubecrate-kind-smoke
KUBECRATE_REF=<full-kubecrate-commit-sha> ./scripts/kind-smoke-e2e.sh
```

The smoke flow reconciles the pinned kubecrate Vanilla entrypoint plus the smoke fixtures and
requires every Envoy CrateCheck check (`envoy-helmrelease-ready`,
`envoy-gatewayclass-accepted`, `envoy-gateway-ready`, `envoy-httproute-ready`) to be green
before and after its controlled-red scenario. See the smoke repository README for the full
contract, including host-port mapping and direct port-forward inspection of `/status.json`.
