# kind cert-manager TLS validation runbook

This runbook validates the cert-manager certificate management slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled.

## Scope

The slice proves TLS certificate issuance through a local self-signed CA chain: a self-signed ClusterIssuer issues a CA Certificate in `core-cert-manager`, which backs a CA ClusterIssuer that issues an end-entity TLS Certificate for CrateCheck. The CA Certificate Secret is created in `core-cert-manager` so the CA ClusterIssuer can read it through cert-manager's `--cluster-resource-namespace` setting. It does not install public ACME, DNS-01, production issuer policy, multi-environment certificate strategy, TLS termination on a Gateway/Route, or a service-specific status app.

## Local access model

The kind config defines a minimal single-control-plane cluster with no pre-provisioned port mappings. Certificate validation uses `kubectl` inspection and CrateCheck `/status.json`; HTTPS termination through an ingress Gateway is deferred.

## QA source / branch override

To reconcile a disposable QA cluster against this exact candidate branch instead of the shared default branch, pass `FLUX_GIT_BRANCH_OVERRIDE` at bootstrap time:

```sh
make kind-dev-misc-local-bootstrap FLUX_GIT_BRANCH_OVERRIDE=kubecrate/cratecheck-restack-cert-manager
```

The bootstrap target writes the override branch into a committed `helm-values-sync-override.yaml` file before `kubectl apply -k` creates the entrypoint resources. The Flux sync HelmRelease (`flux-system-sync`) reads its `GitRepository` branch from two `valuesFrom` ConfigMaps: the committed default (`flux-sync-values`, `helm-values-sync.yaml`) and an override (`flux-sync-values-override`, `helm-values-sync-override.yaml`). The override is marked `optional: true` so the HelmRelease works without it, and the bootstrap target restores the override file to `{}` after the entrypoint is applied. The committed default branch remains `pivot/flux-sync-ssh-bootstrap`.

This is not Makefile-only orchestration — the authoritative override mechanism lives in the committed manifest layer (the `flux-sync-values-override` ConfigMap generator in the flux kustomization and the second `valuesFrom` on the sync HelmRelease). The Makefile is a shortcut that writes a single file.

### Render/dry-run evidence

Before reconciling, render the entrypoint and verify the generated sync GitRepository branch:

```sh
# Default (no override) — expect the committed default branch pivot/flux-sync-ssh-bootstrap
kustomize build clusters/kind-dev-misc-local/entrypoint | yq 'select(.kind == "ConfigMap" and .metadata.name == "flux-sync-values") | .data["values.yaml"]' -oy

# With override — verify the override ConfigMap carries the candidate branch
printf 'gitRepository:\n  spec:\n    ref:\n      branch: kubecrate/cratecheck-restack-cert-manager\n' > clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync-override.yaml
kustomize build clusters/kind-dev-misc-local/entrypoint | yq 'select(.kind == "ConfigMap" and .metadata.name == "flux-sync-values-override") | .data["values.yaml"]' -oy
printf '{}\n' > clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync-override.yaml
```

After bootstrap, confirm the GitRepository reconciled the exact candidate branch:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n flux-system get gitrepository flux-system -o jsonpath='{.spec.ref.branch}' && echo
```

Confirm the exact commit revision:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n flux-system get gitrepository flux-system -o jsonpath='{.status.artifact.revision}' && echo
```

## Evidence commands

Confirm the intended context before inspecting or mutating anything:

```sh
QA_CLUSTER="${QA_CLUSTER:-kind-dev-misc-local}"
kubectl config current-context
kubectl --context "kind-${QA_CLUSTER}" get nodes
```

After GitOps-managed operation reconciles this branch, inspect cert-manager and the local issuer path:

```sh
flux --context "kind-${QA_CLUSTER}" get kustomizations -n flux-system
kubectl --context "kind-${QA_CLUSTER}" -n core-cert-manager get deployments,pods
kubectl --context "kind-${QA_CLUSTER}" get clusterissuers.cert-manager.io
kubectl --context "kind-${QA_CLUSTER}" -n core-cert-manager get certificates.cert-manager.io cratecheck-local-ca
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck get certificates.cert-manager.io,secrets cratecheck-tls
```

Verify the CA Certificate has issued:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n core-cert-manager get secret cratecheck-local-ca -o jsonpath='{.data.tls\\.crt}' | base64 -d | openssl x509 -text -noout | head -20
```

Verify the TLS Certificate has issued:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck get secret cratecheck-tls -o jsonpath='{.data.tls\\.crt}' | base64 -d | openssl x509 -text -noout | head -20
```

For CrateCheck status validation (pre-red baseline, controlled red, and restore green), use the full runbook script in the Controlled Red Test section below, which includes port-forward, trap-based cleanup, bounded polling, and exact state assertions.

## Controlled red test

Only run this on an authorized disposable QA cluster or with explicit approval for the exact target.

The red test verifies that CrateCheck detects cert-manager path breakage and recovers after restoration. Because Flux GitOps reconciliation will immediately restore deleted resources, the test suspends the local issuer Kustomization first.

The red mutation deletes both the TLS Certificate and its Secret so that BOTH the certificate-readiness check and the secret-existence check go red. Deleting only the Certificate leaves the Secret behind (cert-manager does not garbage-collect the Secret on Certificate deletion), which would falsely keep the secret-existence check green.

Cleanup is guaranteed through a shell trap. The port-forward is started in step 1 and stopped automatically on script exit, interrupt, or error. The Kustomization is resumed on trap if suspended.

### Step 1: Start port-forward and verify all cert-manager checks are green (pre-red baseline)

```sh
#!/bin/bash
set -euo pipefail

QA_CLUSTER="${QA_CLUSTER:-kind-dev-misc-local}"
CTX="kind-${QA_CLUSTER}"
ALL_CM_IDS=("cert-manager-helmrelease-ready" "cert-manager-selfsigned-issuer-ready"
            "cert-manager-ca-certificate-ready" "cert-manager-ca-issuer-ready"
            "cert-manager-tls-certificate-ready" "cert-manager-tls-secret-exists")
UNAFFECTED_IDS=("cert-manager-helmrelease-ready" "cert-manager-selfsigned-issuer-ready"
                 "cert-manager-ca-certificate-ready" "cert-manager-ca-issuer-ready")
RED_IDS=("cert-manager-tls-certificate-ready" "cert-manager-tls-secret-exists")

# Cleanup: resume Kustomization if suspended, stop port-forward
KUSTOMIZATION_WAS_SUSPENDED=false
cleanup() {
  echo "--- cleanup ---"
  if [ "${PF_PID:-}" ] && kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
    echo "stopped port-forward (pid $PF_PID)"
  fi
  if [ "$KUSTOMIZATION_WAS_SUSPENDED" = true ]; then
    echo "resuming cert-manager-local-issuer Kustomization..."
    flux --context "$CTX" resume kustomization cert-manager-local-issuer -n flux-system 2>/dev/null || true
    flux --context "$CTX" reconcile kustomization cert-manager-local-issuer -n flux-system --timeout 180s 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Start port-forward
kubectl --context "$CTX" -n cratecheck port-forward svc/cratecheck 8080:8080 &
PF_PID=$!
sleep 2

# --- Helper: fetch status.json ---
fetch_status() {
  python3 -c "
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c['id']: c for c in payload['checks']}
print(json.dumps(checks))
"
}

# --- Polling helper: wait up to MAX_WAIT seconds for predicate to be true ---
poll_until() {
  local desc="$1" max_wait="$2" interval="${3:-5}"
  local elapsed=0
  while [ $elapsed -lt "$max_wait" ]; do
    if eval "$desc"; then
      echo "  condition met after ${elapsed}s"
      return 0
    fi
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done
  echo "  TIMEOUT after ${max_wait}s: $desc" >&2
  return 1
}

# --- Pre-red baseline: all six checks green ---
echo "=== Pre-red baseline ==="
poll_until '
  python3 -c "
import json, sys, urllib.request
p = json.loads(urllib.request.urlopen(\"http://localhost:8080/status.json\").read())
checks = {c[\"id\"]: c[\"state\"] for c in p[\"checks\"]}
for cid in [\"cert-manager-helmrelease-ready\",\"cert-manager-selfsigned-issuer-ready\",\"cert-manager-ca-certificate-ready\",\"cert-manager-ca-issuer-ready\",\"cert-manager-tls-certificate-ready\",\"cert-manager-tls-secret-exists\"]:
    s = checks.get(cid)
    if s is None: sys.exit(1)
    if s != \"green\": sys.exit(1)
sys.exit(0)
" 2>/dev/null
' 120 "all six cert-manager checks green"

echo ""
python3 << 'PYEOF'
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c["id"]: c for c in payload["checks"]}
cm_ids = ["cert-manager-helmrelease-ready", "cert-manager-selfsigned-issuer-ready",
          "cert-manager-ca-certificate-ready", "cert-manager-ca-issuer-ready",
          "cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
for cid in cm_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  PRE-RED FAIL: {cid} is MISSING from payload")
        sys.exit(1)
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')}")
    if c["state"] != "green":
        print(f"  PRE-RED FAIL: {cid} is {c['state']} (expected green)")
        sys.exit(1)
print("PRE-RED BASELINE OK: all six cert-manager checks are green")
PYEOF
```

### Step 2: Suspend the cert-manager-local-issuer Flux Kustomization

```sh
echo "=== Suspend Kustomization ==="
flux --context "$CTX" suspend kustomization cert-manager-local-issuer -n flux-system
KUSTOMIZATION_WAS_SUSPENDED=true
```

### Step 3: Delete both the TLS Certificate and TLS Secret to trigger red state

```sh
echo "=== Delete TLS Certificate and Secret ==="
kubectl --context "$CTX" -n cratecheck delete certificate cratecheck-tls
kubectl --context "$CTX" -n cratecheck delete secret cratecheck-tls
```

### Step 4: Poll until red, then verify exact red state and unaffected checks green

```sh
echo "=== Wait for red state ==="
poll_until '
  python3 -c "
import json, sys, urllib.request
p = json.loads(urllib.request.urlopen(\"http://localhost:8080/status.json\").read())
checks = {c[\"id\"]: c[\"state\"] for c in p[\"checks\"]}
# Both red IDs must be present and non-green
for cid in [\"cert-manager-tls-certificate-ready\", \"cert-manager-tls-secret-exists\"]:
    s = checks.get(cid)
    if s is None: sys.exit(1)
    if s == \"green\": sys.exit(1)
sys.exit(0)
" 2>/dev/null
' 120 "both TLS checks non-green"

echo ""
python3 << 'PYEOF'
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c["id"]: c for c in payload["checks"]}

# Must find both red IDs present and non-green; missing = configuration failure
red_ids = ["cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
all_ok = True
for cid in red_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  RED TEST FAIL: {cid} is MISSING from payload — configuration/evaluation failure")
        all_ok = False
        continue
    is_red = c["state"] != "green"
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')} (expected non-green={is_red})")
    if not is_red:
        print(f"  RED TEST FAIL: {cid} is still green (expected red)")
        all_ok = False

# Assert all four unaffected checks remain green
unaffected_ids = ["cert-manager-helmrelease-ready", "cert-manager-selfsigned-issuer-ready",
                   "cert-manager-ca-certificate-ready", "cert-manager-ca-issuer-ready"]
for cid in unaffected_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  RED TEST FAIL: unaffected check {cid} is MISSING")
        all_ok = False
        continue
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')} (expected green)")
    if c["state"] != "green":
        print(f"  RED TEST FAIL: unaffected check {cid} is {c['state']} (expected green)")
        all_ok = False

if not all_ok:
    print("RED TEST FAILED")
    sys.exit(1)
else:
    print("RED TEST OK: both TLS checks red, all four unaffected checks green")
PYEOF
```

Capture UI evidence: open `http://localhost:8080/` in a browser while the port-forward is active and screenshot the red TLS rows and green issuer rows.

### Step 5: Resume the Kustomization to restore green state

```sh
echo "=== Resume and reconcile Kustomization ==="
flux --context "$CTX" resume kustomization cert-manager-local-issuer -n flux-system
KUSTOMIZATION_WAS_SUSPENDED=false
flux --context "$CTX" reconcile kustomization cert-manager-local-issuer -n flux-system --timeout 180s
```

### Step 6: Poll until green, then verify all six checks back to green

```sh
echo "=== Wait for restore green ==="
poll_until '
  python3 -c "
import json, sys, urllib.request
p = json.loads(urllib.request.urlopen(\"http://localhost:8080/status.json\").read())
checks = {c[\"id\"]: c[\"state\"] for c in p[\"checks\"]}
for cid in [\"cert-manager-helmrelease-ready\",\"cert-manager-selfsigned-issuer-ready\",\"cert-manager-ca-certificate-ready\",\"cert-manager-ca-issuer-ready\",\"cert-manager-tls-certificate-ready\",\"cert-manager-tls-secret-exists\"]:
    s = checks.get(cid)
    if s is None: sys.exit(1)
    if s != \"green\": sys.exit(1)
sys.exit(0)
" 2>/dev/null
' 180 "all six cert-manager checks green after restore"

echo ""
python3 << 'PYEOF'
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c["id"]: c for c in payload["checks"]}
cm_ids = ["cert-manager-helmrelease-ready", "cert-manager-selfsigned-issuer-ready",
          "cert-manager-ca-certificate-ready", "cert-manager-ca-issuer-ready",
          "cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
for cid in cm_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  RESTORE FAIL: {cid} is MISSING from payload")
        sys.exit(1)
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')}")
    if c["state"] != "green":
        print(f"  RESTORE FAIL: {cid} is {c['state']} (expected green)")
        sys.exit(1)
print("RESTORE GREEN OK: all six cert-manager checks returned to green")
PYEOF
```

Capture UI evidence: open `http://localhost:8080/` in a browser while the port-forward is active and screenshot the green cert-manager rows.

The trap at the top of the script handles cleanup: if the script exits before step 5 (e.g., red test assertion failure or Ctrl+C), `cleanup()` resumes the Kustomization and stops the port-forward.

Do not claim final success from static rendering alone. Capture context, Flux status, cert-manager resources, issuer/certificate readiness, TLS Secret existence, CrateCheck `/status.json`, UI screenshots, and the full green→red→restore-green evidence cycle.
