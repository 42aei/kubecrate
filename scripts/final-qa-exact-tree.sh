#!/usr/bin/env bash
# Safeguarded live final QA for one immutable Kubecrate candidate.
# This script performs remote and cluster mutations. Read docs/final-qa-exact-tree.md.
set -Eeuo pipefail

REPO="${KUBECRATE_GITHUB_REPO:-42aei/kubecrate}"
REMOTE="${KUBECRATE_QA_REMOTE:-origin}"
CANDIDATE="${KUBECRATE_QA_CANDIDATE:-HEAD}"
RUN_ID="${KUBECRATE_QA_RUN_ID:-$(date -u +%Y%m%d%H%M%S)-$$}"
QA_BRANCH="${KUBECRATE_QA_BRANCH:-kubecrate-qa/${RUN_ID}}"
CLUSTER="${KUBECRATE_QA_CLUSTER:-kubecrate-qa-${RUN_ID}}"
CONTEXT="kind-${CLUSTER}"
EXPECTED_CHECKS=7
EVIDENCE="${KUBECRATE_QA_EVIDENCE:-.tmp/final-qa-${RUN_ID}}"
QA_VALUES="${EVIDENCE}/flux-sync-values.yaml"
KEY_ID=""
PORT_FORWARD_PID=""
BRANCH_CREATED=false
CLUSTER_CREATED=false
INITIAL_TREE="$(git write-tree)"

fail() { printf 'final-qa: ERROR: %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }
assert_context() {
  actual="$(kubectl config current-context 2>/dev/null || true)"
  test "${actual}" = "${CONTEXT}" || fail "expected kubecontext ${CONTEXT}, got ${actual:-none}"
}
protected_branch() {
  case "$1" in main|master|default|refs/heads/main|refs/heads/master|refs/heads/default) return 0;; *) return 1;; esac
}
remote_branch_state() {
  set +e
  git ls-remote --exit-code --heads "${REMOTE}" "refs/heads/${QA_BRANCH}" >/dev/null 2>&1
  state_rc=$?
  set -e
  case "${state_rc}" in 0) printf 'present\n';; 2) printf 'absent\n';; *) printf 'unknown\n';; esac
}
cluster_state() {
  set +e
  clusters="$(kind get clusters 2>/dev/null)"
  state_rc=$?
  set -e
  test "${state_rc}" -eq 0 || { printf 'unknown\n'; return; }
  if grep -Fx "${CLUSTER}" <<<"${clusters}" >/dev/null; then printf 'present\n'; else printf 'absent\n'; fi
}
key_state() {
  set +e
  key_result="$(gh api "repos/${REPO}/keys/${KEY_ID}" 2>&1)"
  state_rc=$?
  set -e
  if test "${state_rc}" -eq 0; then
    printf 'present\n'
  elif grep -Eq 'HTTP 404|Not Found' <<<"${key_result}"; then
    printf 'absent\n'
  else
    printf 'unknown\n'
  fi
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  cleanup_failed=false
  test -z "${PORT_FORWARD_PID}" || kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  if declare -F restore_if_needed >/dev/null 2>&1; then restore_if_needed; fi
  if test -n "${KEY_ID}"; then
    key_before="$(key_state)"
    if test "${key_before}" = present; then
      gh api -X DELETE "repos/${REPO}/keys/${KEY_ID}" >/dev/null 2>&1 || cleanup_failed=true
    elif test "${key_before}" = unknown; then
      cleanup_failed=true
    fi
    test "$(key_state)" = absent || cleanup_failed=true
  fi
  if ${BRANCH_CREATED}; then
    branch_before="$(remote_branch_state)"
    if test "${branch_before}" = present; then
      git push "${REMOTE}" --delete "${QA_BRANCH}" >/dev/null 2>&1 || cleanup_failed=true
    elif test "${branch_before}" = unknown; then
      cleanup_failed=true
    fi
    test "$(remote_branch_state)" = absent || cleanup_failed=true
  fi
  if ${CLUSTER_CREATED}; then
    cluster_before="$(cluster_state)"
    if test "${cluster_before}" = present; then
      kind delete cluster --name "${CLUSTER}" >/dev/null 2>&1 || cleanup_failed=true
    elif test "${cluster_before}" = unknown; then
      cleanup_failed=true
    fi
    test "$(cluster_state)" = absent || cleanup_failed=true
  fi
  rm -rf "${EVIDENCE}/private"
  git diff --quiet && git diff --cached --quiet || cleanup_failed=true
  test "$(git write-tree)" = "${INITIAL_TREE}" || cleanup_failed=true
  if ${cleanup_failed}; then
    printf 'final-qa: cleanup verification failed (key=%s branch=%s cluster=%s)\n' "${KEY_ID:-none}" "${QA_BRANCH}" "${CLUSTER}" >&2
    exit 1
  fi
  exit "${rc}"
}
trap cleanup EXIT INT TERM

for cmd in git gh kind kubectl kustomize helm flux python3 ssh-keygen curl base64; do require "${cmd}"; done
protected_branch "${QA_BRANCH}" && fail "refusing protected QA branch ${QA_BRANCH}"
case "${CLUSTER}" in kind-dev-misc-local|kubecrate-fix-eso) fail "refusing shared cluster ${CLUSTER}";; esac
case "${QA_BRANCH}" in kubecrate/cratecheck-restack-eso) fail "refusing reviewed/source branch mutation";; esac
git diff --quiet && git diff --cached --quiet || fail "worktree/index must be clean"

CANDIDATE_SHA="$(git rev-parse "${CANDIDATE}^{commit}")"
CANDIDATE_TREE="$(git rev-parse "${CANDIDATE_SHA}^{tree}")"
if test "$(remote_branch_state)" != absent; then
  fail "QA branch exists or absence could not be proved: ${QA_BRANCH}"
fi
if test "$(cluster_state)" != absent; then
  fail "QA cluster exists or absence could not be proved: ${CLUSTER}"
fi
# A direct commit-to-ref push means the QA branch contains the exact candidate
# commit/tree. The runtime values below select that branch without altering it.
git push "${REMOTE}" "${CANDIDATE_SHA}:refs/heads/${QA_BRANCH}"
BRANCH_CREATED=true
REMOTE_SHA="$(git ls-remote --heads "${REMOTE}" "refs/heads/${QA_BRANCH}" | cut -f1)"
test "${REMOTE_SHA}" = "${CANDIDATE_SHA}" || fail "remote QA SHA mismatch"
REMOTE_TREE="$(git rev-parse "${REMOTE_SHA}^{tree}")"
test "${REMOTE_TREE}" = "${CANDIDATE_TREE}" || fail "remote QA tree mismatch"

mkdir -p "${EVIDENCE}"
cat >"${QA_VALUES}" <<EOF
secret:
  create: true
gitRepository:
  spec:
    url: ssh://git@github.com/${REPO}.git
    interval: 1m
    ref:
      branch: ${QA_BRANCH}
kustomization:
  spec:
    interval: 1m
    path: ./clusters/kind-dev-misc-local/entrypoint
    prune: true
    timeout: 5m
    wait: false
EOF
git diff --quiet && git diff --cached --quiet || fail "QA artifact mutated reviewed candidate tree"

python3 scripts/preflight-flux-deploy-key.py --repo "${REPO}"
kind create cluster --name "${CLUSTER}" --config kind/config.yaml
CLUSTER_CREATED=true
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready node --all --timeout=180s

# Runtime-only values select the exact QA branch; reviewed source files stay unchanged.
assert_context
helm upgrade --install flux-system oci://ghcr.io/fluxcd-community/charts/flux2 \
  --kube-context "${CONTEXT}" --version 2.18.4 --namespace flux-system \
  --create-namespace -f clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml
# Render a QA-only stream that replaces only ConfigMap/flux-sync-values data.
# It is applied to the disposable cluster and never committed to the exact tree.
assert_context
kustomize build clusters/kind-dev-misc-local/entrypoint | \
  python3 scripts/render-final-qa-flux-source.py --values "${QA_VALUES}" | \
  kubectl --context "${CONTEXT}" apply -f -
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready helmrelease/flux-system-sync -n flux-system --timeout=180s

mkdir -p "${EVIDENCE}/private"
chmod 700 "${EVIDENCE}/private"
kubectl --context "${CONTEXT}" get secret flux-system -n flux-system -o jsonpath='{.data.identity\.pub}' | base64 -d >"${EVIDENCE}/private/identity.pub"
python3 - "${EVIDENCE}/private/identity.pub" "${EVIDENCE}/private/key-request.json" "${RUN_ID}" <<'PY'
import json, pathlib, sys
pub = pathlib.Path(sys.argv[1]).read_text().strip()
pathlib.Path(sys.argv[2]).write_text(json.dumps({"title": f"kubecrate-qa-{sys.argv[3]}", "key": pub, "read_only": True}))
PY
chmod 600 "${EVIDENCE}/private/key-request.json"
KEY_JSON="$(gh api -X POST "repos/${REPO}/keys" --input "${EVIDENCE}/private/key-request.json" --jq '{id,title,read_only,verified,enabled}')"
KEY_ID="$(python3 -c 'import json,sys
obj=json.load(sys.stdin)
key_id=obj.get("id")
assert type(key_id) is int, "created key id must be an integer"
print(key_id)
' <<<"${KEY_JSON}")"
python3 -c 'import json,sys
obj=json.load(sys.stdin); expected=int(sys.argv[1])
assert type(obj.get("id")) is int and obj["id"] == expected
assert obj.get("title") == sys.argv[2]
for field in ("read_only", "verified", "enabled"):
    assert type(obj.get(field)) is bool and obj[field] is True, field
' "${KEY_ID}" "kubecrate-qa-${RUN_ID}" <<<"${KEY_JSON}"
KEY_READ="$(gh api "repos/${REPO}/keys/${KEY_ID}" --jq '{id,title,read_only,verified,enabled}')"
python3 -c 'import json,sys
obj=json.load(sys.stdin); expected=int(sys.argv[1])
assert type(obj.get("id")) is int and obj["id"] == expected
assert obj.get("title") == sys.argv[2]
for field in ("read_only", "verified", "enabled"):
    assert type(obj.get(field)) is bool and obj[field] is True, field
' "${KEY_ID}" "kubecrate-qa-${RUN_ID}" <<<"${KEY_READ}"
rm -rf "${EVIDENCE}/private"

assert_context
flux --context "${CONTEXT}" reconcile source git flux-system -n flux-system --timeout=180s
assert_context
flux --context "${CONTEXT}" reconcile kustomization flux-system -n flux-system --timeout=300s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Available deployment/cratecheck -n cratecheck --timeout=300s
assert_context
kubectl --context "${CONTEXT}" port-forward -n cratecheck service/cratecheck 18080:8080 >"${EVIDENCE}/port-forward.log" 2>&1 &
PORT_FORWARD_PID=$!

browser_dump() {
  out="$1"
  browser=""
  for candidate in chromium chromium-browser google-chrome; do command -v "${candidate}" >/dev/null 2>&1 && browser="${candidate}" && break; done
  test -n "${browser}" || fail "Chromium/Chrome required for browser UI evidence"
  "${browser}" --headless --no-sandbox --disable-gpu --dump-dom http://127.0.0.1:18080/status >"${out}"
}
validate_status() {
  expected="$1"; file="$2"
  python3 - "${expected}" "${EXPECTED_CHECKS}" "${file}" <<'PY'
import json, sys
expected, count, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
data=json.load(open(path)); checks=data.get("checks"); summary=data.get("summary")
assert isinstance(checks, list) and len(checks)==count, f"expected {count} checks"
assert isinstance(summary, dict) and type(summary.get("total")) is int and summary["total"] == count
assert all(isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("status"), str) for c in checks)
def green(c):
    return c["status"] == "green"
greens=sum(green(c) for c in checks)
if expected == "green":
    assert data.get("status") == "green"
    assert summary.get("green") == count and greens == count, f"only {greens}/{count} green"
else:
    assert data.get("status") in {"red", "yellow", "unknown"}
    relevant=[c for c in checks if str(c.get("id", "")).startswith("eso-")]
    assert relevant and any(not green(c) for c in relevant), "ESO checks did not become non-green"
PY
}
capture_green() {
  phase="$1"; assert_context
  curl --fail --silent --show-error http://127.0.0.1:18080/status.json >"${EVIDENCE}/${phase}-status.json"
  validate_status green "${EVIDENCE}/${phase}-status.json"
  browser_dump "${EVIDENCE}/${phase}-status.html"
  grep -Eq '7[[:space:]]*/[[:space:]]*7|7 of 7' "${EVIDENCE}/${phase}-status.html" || fail "${phase} UI does not show 7/7"
}
controlled_red() {
  assert_context
  flux --context "${CONTEXT}" suspend kustomization external-secrets-operator-smoke -n flux-system
  assert_context
  kubectl --context "${CONTEXT}" delete secret eso-smoke-source -n kubecrate-system
  assert_context
  kubectl --context "${CONTEXT}" wait --for=condition=Ready=false externalsecret/eso-smoke-projection -n kubecrate-system --timeout=180s || true
}
capture_red() {
  assert_context
  curl --fail --silent --show-error http://127.0.0.1:18080/status.json >"${EVIDENCE}/red-status.json"
  validate_status red "${EVIDENCE}/red-status.json"
  browser_dump "${EVIDENCE}/red-status.html"
}
restore_source_secret() {
  assert_context
  flux --context "${CONTEXT}" resume kustomization external-secrets-operator-smoke -n flux-system
  assert_context
  flux --context "${CONTEXT}" reconcile kustomization external-secrets-operator-smoke -n flux-system --timeout=180s
  assert_context
  kubectl --context "${CONTEXT}" wait --for=jsonpath='{.status.conditions[?(@.type=="Ready")].status}'=True externalsecret/eso-smoke-projection -n kubecrate-system --timeout=180s
}
RED_ACTIVE=false
restore_if_needed() {
  if ${RED_ACTIVE} && ${CLUSTER_CREATED}; then
    if test "$(kubectl config current-context 2>/dev/null || true)" = "${CONTEXT}"; then
      flux --context "${CONTEXT}" resume kustomization external-secrets-operator-smoke -n flux-system >/dev/null 2>&1 || true
      flux --context "${CONTEXT}" reconcile kustomization external-secrets-operator-smoke -n flux-system --timeout=180s >/dev/null 2>&1 || true
    fi
  fi
}

capture_green "baseline"
RED_ACTIVE=true
controlled_red
# Let CrateCheck's configured interval observe the reversible failure.
sleep 35
capture_red
restore_source_secret
RED_ACTIVE=false
sleep 35
capture_green "restored"
printf 'final-qa: PASS candidate=%s tree=%s branch=%s evidence=%s\n' "${CANDIDATE_SHA}" "${CANDIDATE_TREE}" "${QA_BRANCH}" "${EVIDENCE}"
