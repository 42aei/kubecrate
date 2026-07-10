# kind Kyverno policy guardrails validation runbook

This runbook validates the Kyverno policy guardrails slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled and Kyverno is installed through GitOps-managed operation.

## Scope

The slice proves admission control enforcement through a `require-ns-label` ClusterPolicy that requires namespaces named `kyverno-smoke-*` to carry `kubecrate.io/validated: "true"`. The policy is scoped to smoke-test namespace names only and does not affect unrelated platform or application namespaces. It includes an allowed fixture namespace (`kyverno-smoke-allowed`) that satisfies the policy after the ClusterPolicy has been reconciled through Flux. It does not install production compliance profiles, multi-tenant governance, background scanning, or exception management.

## Quick reference: candidate branch override for disposable QA clusters

This is required when the live Flux `GitRepository` is pinned to a shared branch (e.g. `pivot/flux-sync-ssh-bootstrap`) and a disposable QA cluster must reconcile the exact candidate branch under test.

```sh
# After bootstrap, before Flux reconciliation — set the candidate branch
QA_BRANCH="kubecrate/cratecheck-restack-kyverno"
kubectl --context kind-<qa-cluster> patch gitrepository flux-system -n flux-system \
  --type merge -p '{"spec":{"ref":{"branch":"'"${QA_BRANCH}"'"}}}'

# Verify the GitRepository now points at the candidate
kubectl --context kind-<qa-cluster> get gitrepository flux-system -n flux-system \
  -o jsonpath='{.spec.ref.branch}'
# Expected: kubecrate/cratecheck-restack-kyverno

# After GitOps reconciliation, verify the exact reconciled revision
kubectl --context kind-<qa-cluster> get gitrepository flux-system -n flux-system \
  -o jsonpath='{.status.artifact.revision}'
# Expected: main@sha1:<commit-hash> for the candidate commit
```

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

# Verify GitRepository is reconciling the expected branch
kubectl --context kind-kind-dev-misc-local get gitrepository flux-system -n flux-system \
  -o jsonpath='{.spec.ref.branch}{"\n"}{.status.artifact.revision}{"\n"}'
```

### 3. Verify Kyverno controller and smoke resources

```sh
kubectl --context kind-kind-dev-misc-local -n core-kyverno get deployments,pods
kubectl --context kind-kind-dev-misc-local get clusterpolicies.kyverno.io require-ns-label -o yaml | head -30
kubectl --context kind-kind-dev-misc-local get namespace kyverno-smoke-allowed
```

### 4. CrateCheck green evidence (JSON)

Start a port-forward in a controlled way, poll CrateCheck for results, capture both /status.json and UI output, then clean up.

```sh
# Start port-forward in background with explicit PID tracking
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
echo "=== CrateCheck HTML UI snippet (human-readable evidence) ==="
curl -s --max-time 5 http://localhost:8080/ | python3 -c "
import sys
body = sys.stdin.read()
# Extract text between <body> and </body>
import re
m = re.search(r'<body[^>]*>(.*?)</body>', body, re.DOTALL)
if m:
    # Strip tags for readable output
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
# Try to create a namespace without the required label
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

This test creates a new labeled namespace (distinct from the fixture) to prove admission is active after the policy is in place.

```sh
# Create a labeled namespace — should succeed
kubectl --context kind-kind-dev-misc-local create namespace kyverno-smoke-allowed-test 2>&1
# Apply the required label
kubectl --context kind-kind-dev-misc-local label namespace kyverno-smoke-allowed-test \
  kubecrate.io/validated=true
# Verify it exists
kubectl --context kind-kind-dev-misc-local get namespace kyverno-smoke-allowed-test && \
  echo "PASS: allowed test — labeled namespace created successfully."

# Clean up
kubectl --context kind-kind-dev-misc-local delete namespace kyverno-smoke-allowed-test --ignore-not-found
```

### 7. Controlled red test

This test temporarily breaks the Kyverno path by deleting the ClusterPolicy, verifies CrateCheck detects the red state, then restores through Flux reconciliation.

> Only run this on an authorized disposable QA cluster or with explicit approval for the exact target.

```sh
# Start port-forward for the red-test phase
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null; wait $PF_PID 2>/dev/null" EXIT
sleep 2

# ===== BREAK: delete the ClusterPolicy =====
echo "=== Breaking: deleting require-ns-label ClusterPolicy ==="
kubectl --context kind-kind-dev-misc-local delete clusterpolicy require-ns-label
echo ""

# ===== RED: poll CrateCheck for non-green kyverno-clusterpolicy-ready =====
echo "=== Polling CrateCheck for red kyverno-clusterpolicy-ready (up to 60s) ==="
python3 << 'PYEOF'
import json, subprocess, sys, time

deadline = time.time() + 60
found_non_green = False

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

    for c in payload.get("checks", []):
        if c["id"] == "kyverno-clusterpolicy-ready":
            state = c["state"]
            summary = c.get("summary", "")
            print(f"  {state:>8} {c['id']}: {summary}")
            if state != "green":
                found_non_green = True
                deadline = 0  # break out
            break
    time.sleep(5)

if not found_non_green:
    print("\nFAIL: kyverno-clusterpolicy-ready did not turn non-green within 60s.")
    sys.exit(1)
print("\nPASS: red test — CrateCheck detected non-green ClusterPolicy.")
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

# ===== RESTORE: reconcile the smoke-policy Kustomization =====
echo "=== Restoring: reconciling kyverno-smoke-policy Kustomization ==="
flux --context kind-kind-dev-misc-local reconcile kustomization kyverno-smoke-policy -n flux-system --timeout 120s
sleep 5

# ===== GREEN AFTER RESTORE =====
echo ""
echo "=== Polling CrateCheck for restored green kyverno-clusterpolicy-ready (up to 60s) ==="
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
    all_ok = True
    for cid in sorted(target_ids):
        c = checks.get(cid)
        state = c["state"] if c else "MISSING"
        summary = c.get("summary", "") if c else ""
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
print("\nPASS: restoration — all Kyverno checks returned to green.")
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
trap - EXIT

# Final verdict
if [ $RED_EXIT -ne 0 ]; then
    echo "FAIL: red test did not detect non-green ClusterPolicy."
    exit 1
fi
if [ $RESTORE_EXIT -ne 0 ]; then
    echo "FAIL: Kyverno checks did not return to green after restoration."
    exit 1
fi
echo "PASS: green → controlled red → restored green — all phases validated."
```

## Evidence summary checklist

Capture all of the following:

- [ ] Cluster context and node list
- [ ] Flux Kustomizations and Git source status with branch/revision
- [ ] Kyverno controller deployment and pods (core-kyverno namespace)
- [ ] ClusterPolicy require-ns-label (exists, Ready)
- [ ] Allowed fixture namespace kyverno-smoke-allowed (exists)
- [ ] CrateCheck /status.json — all Kyverno checks green
- [ ] CrateCheck human-readable UI snippet — green state
- [ ] Deny test output: unlabeled namespace creation denied with expected policy message
- [ ] Allowed test output: labeled namespace creation succeeds
- [ ] Red test: kyverno-clusterpolicy-ready detected as non-green after ClusterPolicy deletion
- [ ] CrateCheck /status.json — red state (kyverno-clusterpolicy-ready non-green)
- [ ] Restore: kyverno-smoke-policy Flux Kustomization reconciled
- [ ] CrateCheck /status.json — all Kyverno checks green after restoration
- [ ] CrateCheck human-readable UI snippet — restored green state

Do not claim final success from static rendering alone. Capture runtime evidence for each phase.
