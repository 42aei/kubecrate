# Kubecrate status app on kind-dev-misc-local

This cluster binding enables the `kubecrate-status` application service through GitOps-managed operation on the kind-first local path.

AI-runnable validation after reconciliation:

```sh
kubectl --context kind-kind-dev-misc-local -n kubecrate-status wait --for=condition=Available deployment/kubecrate-status --timeout=180s
kubectl --context kind-kind-dev-misc-local -n kubecrate-status port-forward svc/kubecrate-status 18080:80 >/tmp/kubecrate-status-port-forward.log 2>&1 &
PF_PID=$!
trap 'kill ${PF_PID}' EXIT
curl -fsS http://127.0.0.1:18080/status.json | python3 -m json.tool
curl -fsS http://127.0.0.1:18080/ >/tmp/kubecrate-status.html
```

The app intentionally uses port-forwarding until a later ingress slice enables an ingress reachability check.
