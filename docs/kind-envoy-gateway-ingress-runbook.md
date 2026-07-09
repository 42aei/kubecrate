# kind Envoy Gateway ingress validation guide

This guide validates the Envoy Gateway HTTP ingress slice for `kind-dev-misc-local`.

## Local access model

The repository-owned kind config maps host port `10080` to node port `30080` on the control-plane node. Envoy Gateway creates a managed Envoy proxy Service for the smoke Gateway on the same node port.

Existing kind clusters created before this mapping was added must be recreated before the host port works:

```sh
make kind-dev-misc-local-recreate
```

## Reconcile and inspect

```sh
kubectl --context kind-kind-dev-misc-local get nodes
kubectl --context kind-kind-dev-misc-local -n flux-system get gitrepository,kustomization
kubectl --context kind-kind-dev-misc-local -n core-envoy-gateway get all,helmrelease
kubectl --context kind-kind-dev-misc-local get gatewayclass kubecrate-envoy-gateway -o yaml
kubectl --context kind-kind-dev-misc-local -n core-envoy-gateway get gateway kubecrate-envoy-smoke -o yaml
kubectl --context kind-kind-dev-misc-local -n cratecheck get httproute envoy-smoke-cratecheck -o yaml
kubectl --context kind-kind-dev-misc-local -n cratecheck get deploy,svc,endpoints cratecheck -o wide
```

## Validate CrateCheck status through ingress

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
curl -fsS http://127.0.0.1:8080/status.json | python3 -c '
import json,sys
data=json.load(sys.stdin)
print("overall:", data.get("overallStatus", data.get("overall_status", "UNKNOWN")))
for c in data.get("checks", data.get("items", [])):
    print(f"  {c.get(\"id\", \"?\")}: {c.get(\"state\", c.get(\"status\", \"?\"))}")
'
```

All Envoy CrateCheck checks (`envoy-helmrelease-ready`, `envoy-gatewayclass-accepted`, `envoy-gateway-ready`, `envoy-httproute-ready`) must report green before this slice can pass live validation.

## Validate CrateCheck status JSON directly

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck exec deploy/cratecheck -- wget -qO- http://localhost:8080/status.json 2>/dev/null || \
kubectl --context kind-kind-dev-misc-local -n cratecheck exec deploy/cratecheck -- cat /status.json 2>/dev/null
```

## Controlled red test

After proving all Envoy checks green:
1. Break the route by patching the HTTPRoute backend port to a non-existent port:
   ```sh
   kubectl --context kind-kind-dev-misc-local -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
     -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":9999}]'
   ```
2. Verify `envoy-httproute-ready` reports non-green in CrateCheck status.
3. Restore the expected backend port:
   ```sh
   kubectl --context kind-kind-dev-misc-local -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
     -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":8080}]'
   ```
4. Verify `envoy-httproute-ready` returns to green.

Do not use this red-test step against shared or production-like clusters.
