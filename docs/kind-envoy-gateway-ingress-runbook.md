# kind Envoy Gateway ingress validation guide

This guide validates the Envoy Gateway HTTP ingress slice for `kind-dev-misc-local`.

## Local access model

The repository-owned kind config maps host port `10080` to node port `30080` on the control-plane node. Envoy Gateway creates a managed Envoy proxy Service for the smoke Gateway. The `EnvoyProxy` resource configures the Service as `NodePort` so ingress traffic reaches the cluster through this mapping.

Existing kind clusters created before this mapping was added must be recreated before the host port works:

```sh
make kind-dev-misc-local-recreate
```

The EnvoyProxy resource declaratively pins NodePort 30080 via `envoyService.patch`. The patch includes `port: 80` as the Kubernetes Service strategic merge key so the patch is valid and unambiguous. After Envoy Gateway reconciles, verify the Envoy proxy Service is running on the expected port:

```sh
kubectl --context kind-kind-dev-misc-local -n core-envoy-gateway get svc -l gateway.envoyproxy.io/owning-gateway-name=kubecrate-envoy-smoke -o jsonpath='{.items[0].spec.ports[0].nodePort}'
```

Verify host-side ingress is reachable:

```sh
curl -fsS http://127.0.0.1:10080/
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

## Validate CrateCheck status through Envoy Gateway ingress

Access CrateCheck `/status.json` through the Envoy Gateway ingress path (host port 10080 → kind node → Envoy proxy → CrateCheck Service):

```sh
curl -fsS http://127.0.0.1:10080/status.json | python3 -c '
import json,sys
data=json.load(sys.stdin)
print("overall:", data.get("overallStatus", data.get("overall_status", "UNKNOWN")))
for c in data.get("checks", data.get("items", [])):
    print(f"  {c.get(\"id\", \"?\")}: {c.get(\"state\", c.get(\"status\", \"?\"))}")
'
```

All Envoy CrateCheck checks (`envoy-helmrelease-ready`, `envoy-gatewayclass-accepted`, `envoy-gateway-ready`, `envoy-httproute-ready`) must report green before this slice can pass live validation.

## Validate CrateCheck status directly (port-forward)

As a fallback or for debugging when ingress is not working, access CrateCheck directly:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
sleep 2
curl -fsS http://127.0.0.1:8080/status.json | python3 -c '
import json,sys
data=json.load(sys.stdin)
print("overall:", data.get("overallStatus", data.get("overall_status", "UNKNOWN")))
for c in data.get("checks", data.get("items", [])):
    print(f"  {c.get(\"id\", \"?\")}: {c.get(\"state\", c.get(\"status\", \"?\"))}")
'
kill %1 2>/dev/null
```

Or inspect from inside the pod:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck exec deploy/cratecheck -- wget -qO- http://localhost:8080/status.json 2>/dev/null || \
kubectl --context kind-kind-dev-misc-local -n cratecheck exec deploy/cratecheck -- cat /status.json 2>/dev/null
```

## Controlled red test

After proving all Envoy checks green:

### Phase 1: Verify green baseline

```sh
# All Envoy checks must be green
curl -fsS http://127.0.0.1:10080/status.json | python3 -c '
import json,sys
data=json.load(sys.stdin)
checks = {c["id"]: c for c in data.get("checks", data.get("items", []))}
route = checks.get("envoy-httproute-ready", {})
print(f"envoy-httproute-ready: {route.get(\"state\", route.get(\"status\", \"?\"))}")
assert route.get("state") == "green" or route.get("status") == "green", "expected green"
print("GREEN baseline confirmed")
'
```

### Phase 2: Break the route (controlled red)

Patch the HTTPRoute backend port to a non-existent port. This breaks `ResolvedRefs` because the backend port 9999 does not exist on the CrateCheck Service:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":9999}]'
```

Wait for the route status to update (typically within 30 seconds), then verify the red condition:

```sh
sleep 10
curl -fsS http://127.0.0.1:10080/status.json | python3 -c '
import json,sys
data=json.load(sys.stdin)
checks = {c["id"]: c for c in data.get("checks", data.get("items", []))}
route = checks.get("envoy-httproute-ready", {})
state = route.get("state", route.get("status", "?"))
print(f"envoy-httproute-ready: {state}")
assert state != "green", f"expected non-green after red test, got {state}"
print("RED test: envoy-httproute-ready is NOT green (expected)")
'
```

Alternatively, inspect the HTTPRoute parent status directly:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck get httproute envoy-smoke-cratecheck \
  -o jsonpath='{range .status.parents[*]}{.conditions}{"\n"}{end}' | python3 -m json.tool
```

`ResolvedRefs` should be `False` with a reason like `BackendNotFound` or `ServicePortNotFound`.

### Phase 3: Restore green

Restore the correct backend port:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":8080}]'
```

Verify `envoy-httproute-ready` returns to green:

```sh
sleep 10
curl -fsS http://127.0.0.1:10080/status.json | python3 -c '
import json,sys
data=json.load(sys.stdin)
checks = {c["id"]: c for c in data.get("checks", data.get("items", []))}
route = checks.get("envoy-httproute-ready", {})
state = route.get("state", route.get("status", "?"))
print(f"envoy-httproute-ready: {state}")
assert state == "green", f"expected green after restore, got {state}"
print("RESTORE: envoy-httproute-ready is green (expected)")
'
```

Do not use this red-test step against shared or production-like clusters.

## Disposable-cluster QA

Use `scripts/direct-kind-flux-e2e.sh` for automated live QA. It requires a dedicated remote QA branch and exact expected commit, creates and verifies a disposable kind context, renders that branch into the in-memory HTTPS Flux source before the initial apply, checks the reconciled artifact revision, and always cleans up its cluster. The committed Flux source remains `main`.

The runner proves the baseline and final all-green JSON contract through host ingress. During its bounded red scenario it suspends the Envoy smoke Kustomization, changes only the HTTPRoute backend port to `9999`, and uses the direct CrateCheck port-forward to prove only `envoy-httproute-ready` turns red. It then restores port `8080`, resumes and reconciles Flux, and proves host ingress and all checks return green.
