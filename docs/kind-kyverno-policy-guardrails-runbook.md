# kind Kyverno policy guardrails validation runbook

This runbook validates the Kyverno policy guardrails slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled.

## Scope

The slice proves admission control enforcement through a single `require-ns-label` ClusterPolicy that requires namespaces to carry `kubecrate.io/validated: "true"`. It includes an allowed fixture namespace that satisfies the policy. It does not install production compliance profiles, multi-tenant governance, background scanning, or exception management.

## Evidence commands

Confirm the intended context before inspecting or mutating anything:

```sh
kubectl config current-context
kubectl --context kind-kind-dev-misc-local get nodes
```

After GitOps-managed operation reconciles this branch, inspect Kyverno and the smoke policy:

```sh
flux --context kind-kind-dev-misc-local get kustomizations -n flux-system
kubectl --context kind-kind-dev-misc-local -n core-kyverno get deployments,pods
kubectl --context kind-kind-dev-misc-local get clusterpolicies.kyverno.io require-ns-label -o yaml | head -30
```

## Allowed fixture (green)

Verify the allowed fixture namespace exists:

```sh
kubectl --context kind-kind-dev-misc-local get namespace kyverno-smoke-allowed
```

## Deny test (real evidence)

Prove Kyverno denies a namespace without the required label:

```sh
kubectl --context kind-kind-dev-misc-local create namespace kyverno-smoke-deny-test 2>&1
# Should be denied: "admission webhook ... denied the request: Namespace must have label kubecrate.io/validated: 'true'"
```

Clean up after the deny test if the namespace was somehow not created (it should be denied):

```sh
kubectl --context kind-kind-dev-misc-local delete namespace kyverno-smoke-deny-test --ignore-not-found
```

## CrateCheck evidence

Assert CrateCheck Kyverno checks are green:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
sleep 2
curl -s http://localhost:8080/status.json | python3 -c '
import json,sys
payload = json.load(sys.stdin)
checks = {c["id"]: c for c in payload["checks"]}
kv_ids = ["kyverno-helmrelease-ready", "kyverno-clusterpolicy-ready",
          "kyverno-smoke-namespace-exists"]
for cid in kv_ids:
    if cid in checks:
        c = checks[cid]
        print(f"{c['state']:>6} {cid}: {c.get('summary', '')}")
'
kill %1 2>/dev/null
```

## Controlled red test

Only run this on an authorized disposable QA cluster or with explicit approval for the exact target.

A reversible red test is to temporarily delete the ClusterPolicy, verify CrateCheck reports `kyverno-clusterpolicy-ready` as non-green, then restore the ClusterPolicy resource and verify green again.

```sh
# Break: delete the ClusterPolicy
kubectl --context kind-kind-dev-misc-local delete clusterpolicy require-ns-label
sleep 10
# Verify CrateCheck reports kyverno-clusterpolicy-ready as non-green
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
sleep 2
curl -s http://localhost:8080/status.json | python3 -c '
import json,sys
payload = json.load(sys.stdin)
for c in payload["checks"]:
    if c["id"] == "kyverno-clusterpolicy-ready":
        print(f"{c['state']:>6} {c['id']}: {c.get('summary', '')}")
'
kill %1 2>/dev/null
```

Then restore by re-reconciling through Flux:

```sh
flux --context kind-kind-dev-misc-local reconcile kustomization kyverno-smoke -n flux-system
sleep 15
# Verify green again
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
sleep 2
curl -s http://localhost:8080/status.json | python3 -c '
import json,sys
payload = json.load(sys.stdin)
for c in payload["checks"]:
    if c["id"] == "kyverno-clusterpolicy-ready":
        print(f"{c['state']:>6} {c['id']}: {c.get('summary', '')}")
'
kill %1 2>/dev/null
```

Do not claim final success from static rendering alone. Capture context, Flux status, Kyverno resources, ClusterPolicy readiness, allowed fixture namespace existence, deny evidence, CrateCheck `/status.json`, and red-test evidence.
