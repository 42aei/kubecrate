# kind Kyverno policy guardrails validation runbook

This runbook validates the Kyverno policy guardrails slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled and Kyverno is installed through GitOps-managed operation.

## Scope

The slice proves admission control enforcement through a `require-ns-label` ClusterPolicy that requires namespaces named `kyverno-smoke-*` to carry `kubecrate.io/validated: "true"`. The policy is scoped to smoke-test namespace names only and does not affect unrelated platform or application namespaces. It includes an allowed fixture namespace (`kyverno-smoke-allowed`) that satisfies the policy after the ClusterPolicy has been reconciled through Flux. It does not install production compliance profiles, multi-tenant governance, background scanning, or exception management.

## Quick reference: candidate branch override for disposable QA clusters

This is required when the live Flux `GitRepository` must reconcile a candidate branch different from the default. The bootstrap target writes a `helm-values-sync-override.yaml` file with the candidate branch reference before applying the entrypoint Kustomization, and restores it to an empty override after the apply — creating a durable GitRepository reference before its first reconciliation with no post-bootstrap `kubectl patch` needed.

```sh
# Bootstrap with a candidate branch override
make kind-dev-misc-local-bootstrap FLUX_GIT_BRANCH_OVERRIDE="kubecrate/cratecheck-restack-kyverno"

# Verify the GitRepository references the expected candidate branch
kubectl --context kind-kind-dev-misc-local get gitrepository flux-system -n flux-system \
  -o jsonpath='{.spec.ref.branch}{"\n"}'
# Expected: kubecrate/cratecheck-restack-kyverno

# After GitOps reconciliation, verify the exact reconciled revision
kubectl --context kind-kind-dev-misc-local get gitrepository flux-system -n flux-system \
  -o jsonpath='{.status.artifact.revision}{"\n"}'
# Expected: kubecrate/cratecheck-restack-kyverno@sha1:<commit-hash>
```

The repository default remains `pivot/flux-sync-ssh-bootstrap` (set by `FLUX_GIT_BRANCH` in the Makefile). The override only affects the QA cluster bootstrap.

## Evidence commands

### 1. Confirm the intended context

```sh
kubectl config current-context
kubectl --context kind-kind-dev-misc-local get nodes
```

### 2. Verify Flux GitOps status

```sh
flux --context kind-kind-dev-misc-local get kustomizations -n flux-system
flux --context kind-kind-dev-misc-local get sources git -n flux-system

# Verify GitRepository is reconciling the expected branch AND exact revision
kubectl --context kind-kind-dev-misc-local get gitrepository flux-system -n flux-system \
  -o jsonpath='{.spec.ref.branch}{"\n"}{.status.artifact.revision}{"\n"}'
```

### 3. Verify Kyverno controller and smoke resources

```sh
kubectl --context kind-kind-dev-misc-local -n core-kyverno get deployments,pods
kubectl --context kind-kind-dev-misc-local get clusterpolicies.kyverno.io require-ns-label -o yaml | head -30
kubectl --context kind-kind-dev-misc-local get namespace kyverno-smoke-allowed
```

### 4. CrateCheck green evidence (JSON + UI)

Start a port-forward, poll CrateCheck for all three Kyverno checks to be green, capture both /status.json and UI output, then clean up.

```sh
# Start port-forward with explicit PID tracking
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
PF_PID=$!
# Ensure cleanup on exit
trap "kill $PF_PID 2>/dev/null; wait $PF_PID 2>/dev/null" EXIT
sleep 2

# Poll CrateCheck /status.json with timeout (up to 60s for Kyverno checks to go green)
python3 << 'PYEOF'
import json, subprocess, sys, time

deadline = time.time() + 60
target_ids = {"kyverno-helmrelease-ready", "kyverno-clusterpolicy-ready", "kyverno-smoke-namespace-exists"}
all_green = False

while time.time() < deadline:
    result = subprocess.run(
        ["curl", "-s", "--max-time", "5", "http://localhost:8080/status.json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        time.sleep(2)
        continue

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        time.sleep(2)
        continue

    checks = {c["id"]: c for c in payload.get("checks", [])}

    all_ok = True
    for cid in sorted(target_ids):
        c = checks.get(cid)
        state = c["state"] if c else "MISSING"
        summary = c.get("summary", "") if c else ""
        print(f"  {state:>8} {cid}: {summary}")
        if state != "green":
            all_ok = False

    if all_ok:
        print("\nAll Kyverno CrateCheck checks are green.")
        all_green = True
        break

    time.sleep(5)

if not all_green:
    print("\nFAIL: Kyverno CrateCheck checks did not reach green within 60s.")
    sys.exit(1)
PYEOF
# Store exit code
GREEN_EXIT=$?

# Capture human-readable UI snapshot (text-based)
echo ""
echo "=== CrateCheck HTML UI snippet (green state evidence) ==="
curl -s --max-time 5 http://localhost:8080/ | python3 -c "
import sys, re
body = sys.stdin.read()
m = re.search(r'<body[^>]*>(.*?)</body>', body, re.DOTALL)
if m:
    text = re.sub(r'<[^>]+>', ' ', m.group(1))
    text = re.sub(r'\s+', ' ', text).strip()
    print(text[:2000])
else:
    print('(no body content found in UI)')
"
echo ""

# Clean up port-forward
kill $PF_PID 2>/dev/null
wait $PF_PID 2>/dev/null
trap - EXIT

test $GREEN_EXIT -eq 0 || { echo "FAIL: CrateCheck Kyverno checks not green. Aborting."; exit 1; }
```

### 5. Deny test: prove Kyverno denies an unlabeled smoke namespace

```sh
# Try to create a namespace without the required label — must be denied
DENY_OUTPUT=$(kubectl --context kind-kind-dev-misc-local create namespace kyverno-smoke-deny-test 2>&1) || true
echo "$DENY_OUTPUT"

# Assert the deny reason is the expected policy message
echo "$DENY_OUTPUT" | grep -q "kubecrate.io/validated" || {
    echo "FAIL: Expected deny message containing 'kubecrate.io/validated' but got: $DENY_OUTPUT"
    exit 1
}
echo "PASS: deny test — namespace creation was denied with expected policy message."

# Clean up if somehow created (should not happen with proper Enforce)
kubectl --context kind-kind-dev-misc-local delete namespace kyverno-smoke-deny-test --ignore-not-found
```

### 6. Allowed test: prove Kyverno admits a properly labeled smoke namespace

This test submits a Namespace manifest with the required label in the initial admission request — the label must be present at creation time, not added afterward, because the ClusterPolicy is in Enforce mode.

```sh
# Create a labeled namespace via manifest (label present at admission time)
kubectl --context kind-kind-dev-misc-local apply -f - << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: kyverno-smoke-allowed-test
  labels:
    kubecrate.io/validated: "true"
EOF

# Verify it exists
kubectl --context kind-kind-dev-misc-local get namespace kyverno-smoke-allowed-test && \
  echo "PASS: allowed test — labeled namespace created successfully (label set at admission time)."

# Clean up
kubectl --context kind-kind-dev-misc-local delete namespace kyverno-smoke-allowed-test --ignore-not-found
```

### 7. Controlled red test with fail-closed restoration

This test temporarily breaks the Kyverno path by deleting the ClusterPolicy, verifies CrateCheck detects exactly the red state (with other Kyverno checks remaining green), then restores through Flux reconciliation. The test is fail-closed: a trap ensures the ClusterPolicy is restored on errors or interruption.

> Only run this on an authorized disposable QA cluster or with explicit approval for the exact target.

```sh
# Fail-closed wrapper: trap to restore ClusterPolicy on error/interruption
cleanup_and_restore() {
    echo ""
    echo "=== TRAP: killing port-forward and restoring ClusterPolicy via Flux reconciliation ==="
    kill $PF_PID 2>/dev/null || true
    wait $PF_PID 2>/dev/null || true
    flux --context kind-kind-dev-misc-local reconcile kustomization kyverno-smoke-policy -n flux-system --timeout 120s 2>/dev/null || true
    kubectl --context kind-kind-dev-misc-local get clusterpolicy require-ns-label --no-headers 2>/dev/null || \
      echo "WARN: ClusterPolicy still missing after trap restore attempt"
    echo "=== TRAP: cleanup complete ==="
}
trap cleanup_and_restore EXIT INT TERM

# Start port-forward for the entire red-test phase
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
PF_PID=$!
sleep 2

# ===== BREAK: delete the ClusterPolicy =====
echo "=== Breaking: deleting require-ns-label ClusterPolicy ==="
kubectl --context kind-kind-dev-misc-local delete clusterpolicy require-ns-label
echo ""

# ===== RED: poll CrateCheck for non-green kyverno-clusterpolicy-ready =====
# Must confirm: clusterpolicy is red AND helmrelease/smoke-ns remain green
echo "=== Polling CrateCheck for red kyverno-clusterpolicy-ready (up to 60s) ==="
python3 << 'PYEOF'
import json, subprocess, sys, time

deadline = time.time() + 60
found_red = False
unaffected_green = False

while time.time() < deadline:
    result = subprocess.run(
        ["curl", "-s", "--max-time", "5", "http://localhost:8080/status.json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        time.sleep(2)
        continue

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        time.sleep(2)
        continue

    checks = {c["id"]: c for c in payload.get("checks", [])}

    # Require all expected checks are present (missing checks = fail)
    cp_check = checks.get("kyverno-clusterpolicy-ready")
    hr_check = checks.get("kyverno-helmrelease-ready")
    ns_check = checks.get("kyverno-smoke-namespace-exists")

    if cp_check is None or hr_check is None or ns_check is None:
        print("  MISSING one or more Kyverno checks — will retry")
        time.sleep(5)
        continue

    cp_state = cp_check["state"]
    hr_state = hr_check["state"]
    ns_state = ns_check["state"]

    print(f"  {cp_state:>8} kyverno-clusterpolicy-ready: {cp_check.get('summary', '')}")
    print(f"  {hr_state:>8} kyverno-helmrelease-ready: {hr_check.get('summary', '')}")
    print(f"  {ns_state:>8} kyverno-smoke-namespace-exists: {ns_check.get('summary', '')}")

    # ClusterPolicy must be red (exact state match, not any non-green)
    cp_is_red = cp_state == "red"

    # HelmRelease and smoke namespace must remain green (unaffected)
    unaffected_ok = hr_state == "green" and ns_state == "green"

    if cp_is_red and unaffected_ok:
        found_red = True
        unaffected_green = True
        break

    time.sleep(5)

if not found_red:
    print("\nFAIL: kyverno-clusterpolicy-ready did not turn red within 60s.")
    sys.exit(1)
if not unaffected_green:
    print("\nFAIL: unaffected Kyverno checks (helmrelease-ready, smoke-namespace-exists) are not green.")
    sys.exit(1)
print("\nPASS: red test — ClusterPolicy red, HelmRelease+smoke namespace unaffected green.")
PYEOF
RED_EXIT=$?

# Capture red-state JSON evidence
echo ""
echo "=== CrateCheck /status.json (red state evidence) ==="
curl -s --max-time 5 http://localhost:8080/status.json | python3 -c "
import json, sys
payload = json.load(sys.stdin)
for c in payload.get('checks', []):
    if c['id'].startswith('kyverno-'):
        print(f\"  {c['state']:>8} {c['id']}: {c.get('summary', '')}\")
print()
"

# Capture red-state UI evidence
echo "=== CrateCheck HTML UI snippet (red state evidence) ==="
curl -s --max-time 5 http://localhost:8080/ | python3 -c "
import sys, re
body = sys.stdin.read()
m = re.search(r'<body[^>]*>(.*?)</body>', body, re.DOTALL)
if m:
    text = re.sub(r'<[^>]+>', ' ', m.group(1))
    text = re.sub(r'\s+', ' ', text).strip()
    print(text[:2000])
else:
    print('(no body content found in UI)')
"
echo ""

# ===== RESTORE: reconcile the smoke-policy Kustomization =====
echo "=== Restoring: reconciling kyverno-smoke-policy Kustomization ==="
flux --context kind-kind-dev-misc-local reconcile kustomization kyverno-smoke-policy -n flux-system --timeout 120s
# Poll for ClusterPolicy to be Ready (not a fixed sleep)
python3 << 'PYEOF'
import subprocess, sys, time

deadline = time.time() + 60
while time.time() < deadline:
    result = subprocess.run(
        ["kubectl", "--context", "kind-kind-dev-misc-local",
         "get", "clusterpolicy", "require-ns-label",
         "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip() == "True":
        print("ClusterPolicy require-ns-label is Ready after restore.")
        break
    time.sleep(3)
else:
    print("FAIL: ClusterPolicy did not reach Ready within 60s after restore.")
    sys.exit(1)
PYEOF

# ===== GREEN AFTER RESTORE =====
echo ""
echo "=== Polling CrateCheck for restored green (all three Kyverno checks, up to 60s) ==="
python3 << 'PYEOF'
import json, subprocess, sys, time

deadline = time.time() + 60
all_green = False

while time.time() < deadline:
    result = subprocess.run(
        ["curl", "-s", "--max-time", "5", "http://localhost:8080/status.json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        time.sleep(2)
        continue

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        time.sleep(2)
        continue

    checks = {c["id"]: c for c in payload.get("checks", [])}
    target_ids = {"kyverno-helmrelease-ready", "kyverno-clusterpolicy-ready", "kyverno-smoke-namespace-exists"}

    # Require all checks present — missing checks = fail
    if not target_ids.issubset(checks.keys()):
        missing = target_ids - set(checks.keys())
        print(f"  MISSING checks: {missing} — retrying")
        time.sleep(5)
        continue

    all_ok = True
    for cid in sorted(target_ids):
        c = checks[cid]
        state = c["state"]
        summary = c.get("summary", "")
        print(f"  {state:>8} {cid}: {summary}")
        if state != "green":
            all_ok = False

    if all_ok:
        all_green = True
        break
    time.sleep(5)

if not all_green:
    print("\nFAIL: Kyverno checks did not return to green after restoration.")
    sys.exit(1)
print("\nPASS: restoration — all three Kyverno checks returned to green.")
PYEOF
RESTORE_EXIT=$?

# Capture restored-green UI evidence
echo ""
echo "=== CrateCheck HTML UI snippet (post-restoration green evidence) ==="
curl -s --max-time 5 http://localhost:8080/ | python3 -c "
import sys, re
body = sys.stdin.read()
m = re.search(r'<body[^>]*>(.*?)</body>', body, re.DOTALL)
if m:
    text = re.sub(r'<[^>]+>', ' ', m.group(1))
    text = re.sub(r'\s+', ' ', text).strip()
    print(text[:2000])
else:
    print('(no body content found in UI)')
"
echo ""

# Clean up port-forward
kill $PF_PID 2>/dev/null
wait $PF_PID 2>/dev/null
# Disarm the fail-closed trap (restore already done above)
trap - EXIT INT TERM

# Final verdict
if [ $RED_EXIT -ne 0 ]; then
    echo "FAIL: red test did not detect non-green ClusterPolicy or unaffected checks were not green."
    exit 1
fi
if [ $RESTORE_EXIT -ne 0 ]; then
    echo "FAIL: Kyverno checks did not return to green after restoration."
    exit 1
fi
echo "PASS: green -> controlled red -> restored green — all phases validated (fail-closed)."
```

## Evidence summary checklist

Capture all of the following:

- [ ] Cluster context and node list
- [ ] Flux Kustomizations and Git source status with exact branch AND revision
- [ ] Kyverno controller deployment and pods (core-kyverno namespace)
- [ ] ClusterPolicy require-ns-label (exists, Ready)
- [ ] Allowed fixture namespace kyverno-smoke-allowed (exists)
- [ ] CrateCheck /status.json — all Kyverno checks green
- [ ] CrateCheck human-readable UI snippet — green state
- [ ] Deny test output: unlabeled namespace creation denied with expected policy message
- [ ] Allowed test output: labeled namespace created at admission time (label in manifest, not post-create)
- [ ] Red test: kyverno-clusterpolicy-ready detected as red after ClusterPolicy deletion
- [ ] Red test: kyverno-helmrelease-ready and kyverno-smoke-namespace-exists confirmed green (unaffected)
- [ ] CrateCheck /status.json — red state and unaffected-green evidence
- [ ] CrateCheck HTML UI snippet — red state
- [ ] Restore: kyverno-smoke-policy Flux Kustomization reconciled
- [ ] ClusterPolicy Ready=True confirmed via polling (not fixed sleep)
- [ ] CrateCheck /status.json — all three Kyverno checks green after restoration
- [ ] CrateCheck HTML UI snippet — restored green state
- [ ] Fail-closed trap: ClusterPolicy restored even on error/interruption

Do not claim final success from static rendering alone. Capture runtime evidence for each phase.
