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
INITIAL_TREE=""
RED_STATE=none
OWNED_REF_MARKER="${EVIDENCE}/owned-ref.json"
UNCERTAIN_REF_MARKER="${OWNED_REF_MARKER}.uncertain"

fail() { printf 'final-qa: ERROR: %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }
assert_context() {
  actual="$(kubectl config current-context 2>/dev/null || true)"
  test "${actual}" = "${CONTEXT}" || fail "expected kubecontext ${CONTEXT}, got ${actual:-none}"
}
protected_branch() {
  case "$1" in main|master|default|refs/heads/main|refs/heads/master|refs/heads/default) return 0;; *) return 1;; esac
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
  if test "${RED_STATE}" != none && ${CLUSTER_CREATED}; then
    restore_if_needed || cleanup_failed=true
  fi
  test -z "${PORT_FORWARD_PID}" || kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  if test -n "${KEY_ID}"; then
    key_before="$(key_state)"
    if test "${key_before}" = present; then
      gh api -X DELETE "repos/${REPO}/keys/${KEY_ID}" >/dev/null 2>&1 || cleanup_failed=true
    elif test "${key_before}" = unknown; then
      cleanup_failed=true
    fi
    test "$(key_state)" = absent || cleanup_failed=true
  fi
  if test -f "${OWNED_REF_MARKER}"; then
    python3 scripts/final_qa_helpers.py delete-ref-marker --marker "${OWNED_REF_MARKER}" >/dev/null 2>&1 || cleanup_failed=true
  fi
  if test -f "${UNCERTAIN_REF_MARKER}"; then
    printf 'final-qa: unverified ref creation requires manual investigation: %s\n' "${UNCERTAIN_REF_MARKER}" >&2
    cleanup_failed=true
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
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for cmd in git python3; do require "${cmd}"; done
CANDIDATE_SHA="$(git rev-parse "${CANDIDATE}^{commit}")"
CANDIDATE_TREE="$(git rev-parse "${CANDIDATE_SHA}^{tree}")"
test "$(git rev-parse HEAD)" = "${CANDIDATE_SHA}" || fail "local HEAD must equal candidate ${CANDIDATE_SHA}"
test "$(git write-tree)" = "${CANDIDATE_TREE}" || fail "local index tree must equal candidate tree"
test -z "$(git status --porcelain=v1 --untracked-files=all)" || fail "tracked worktree/index must be clean and untracked files are forbidden"
INITIAL_TREE="${CANDIDATE_TREE}"
if test "${KUBECRATE_QA_IDENTITY_GATE_ONLY:-0}" = 1; then
  printf 'final-qa: identity gate passed candidate=%s tree=%s\n' "${CANDIDATE_SHA}" "${CANDIDATE_TREE}"
  trap - EXIT INT TERM
  exit 0
fi
mkdir -p "${EVIDENCE}"
if test "${KUBECRATE_QA_TEST_MODE:-0}" = 1; then
  # Subprocess-only lifecycle seam. It is unreachable unless explicitly enabled and
  # performs only the same fake-PATH commands used by tests.
  test_cleanup() {
    rc=$?; trap - EXIT INT TERM; failed=false
    if test "${RED_STATE}" != none; then
      python3 scripts/final_qa_helpers.py restore --context "${CONTEXT}" || failed=true
    fi
    if test -f "${OWNED_REF_MARKER}"; then
      python3 scripts/final_qa_helpers.py delete-ref-marker --marker "${OWNED_REF_MARKER}" || failed=true
    fi
    if ${CLUSTER_CREATED}; then kind delete cluster --name "${CLUSTER}" || failed=true; fi
    ${failed} && exit 1
    exit "${rc}"
  }
  trap test_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  case "${KUBECRATE_QA_TEST_SCENARIO:-}" in
    after-suspend|after-delete)
      CLUSTER_CREATED=true
      RED_STATE=restore_required
      flux --context "${CONTEXT}" suspend kustomization external-secrets-operator-smoke -n flux-system
      if test "${KUBECRATE_QA_TEST_SCENARIO}" = after-suspend; then kill -TERM "$$"; fi
      kubectl --context "${CONTEXT}" delete secret eso-smoke-source -n kubecrate-system
      kill -TERM "$$"
      ;;
    after-ref-helper)
      python3 scripts/final_qa_helpers.py create-ref --repo "${REPO}" --ref "refs/heads/${QA_BRANCH}" \
        --sha "${CANDIDATE_SHA}" --marker "${OWNED_REF_MARKER}"
      kill -TERM "$$"
      ;;
    *) fail "unknown lifecycle test scenario";;
  esac
fi
for cmd in gh kind kubectl kustomize helm flux ssh-keygen curl base64; do require "${cmd}"; done
protected_branch "${QA_BRANCH}" && fail "refusing protected QA branch ${QA_BRANCH}"
case "${CLUSTER}" in kind-dev-misc-local|kubecrate-fix-eso) fail "refusing shared cluster ${CLUSTER}";; esac
case "${QA_BRANCH}" in kubecrate/cratecheck-restack-eso) fail "refusing reviewed/source branch mutation";; esac
if test "$(cluster_state)" != absent; then
  fail "QA cluster exists or absence could not be proved: ${CLUSTER}"
fi
# The GitHub create-ref API is atomic: an existing/racing ref returns 422 and
# cannot be mistaken for ownership by this run.
python3 scripts/final_qa_helpers.py create-ref --repo "${REPO}" \
  --ref "refs/heads/${QA_BRANCH}" --sha "${CANDIDATE_SHA}" --marker "${OWNED_REF_MARKER}"
if test "${KUBECRATE_QA_FAILPOINT:-}" = after-ref-helper; then kill -TERM "$$"; fi
BRANCH_CREATED=true

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

port_forward_ready() {
  test -n "${PORT_FORWARD_PID}" && kill -0 "${PORT_FORWARD_PID}" 2>/dev/null || return 1
  curl --fail --silent http://127.0.0.1:18080/status.json >/dev/null 2>&1
}
wait_port_forward() {
  scripts/wait-port-forward.sh "${PORT_FORWARD_PID}" "${EVIDENCE}/port-forward.log" \
    http://127.0.0.1:18080/status.json "${KUBECRATE_QA_PORT_FORWARD_TIMEOUT:-20}" \
    "${KUBECRATE_QA_PORT_FORWARD_POLL_INTERVAL:-0.25}" || fail "CrateCheck transport not ready; see ${EVIDENCE}/port-forward.log"
}
start_port_forward() {
  assert_context
  kubectl --context "${CONTEXT}" port-forward -n cratecheck service/cratecheck 18080:8080 >"${EVIDENCE}/port-forward.log" 2>&1 &
  PORT_FORWARD_PID=$!
  wait_port_forward
}
ensure_port_forward() {
  port_forward_ready && return 0
  test -z "${PORT_FORWARD_PID}" || kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  start_port_forward
}
start_port_forward

browser_dump() {
  out="$1"
  browser=""
  for candidate in chromium chromium-browser google-chrome; do command -v "${candidate}" >/dev/null 2>&1 && browser="${candidate}" && break; done
  test -n "${browser}" || fail "Chromium/Chrome required for browser UI evidence"
  "${browser}" --headless --no-sandbox --disable-gpu --dump-dom http://127.0.0.1:18080/status >"${out}"
}
validate_status() {
  expected="$1"; file="$2"
  python3 scripts/final_qa_helpers.py validate-json --phase "${expected}" "${file}"
}
capture_green() {
  phase="$1"; assert_context
  curl --fail --silent --show-error http://127.0.0.1:18080/status.json >"${EVIDENCE}/${phase}-status.json"
  validate_status green "${EVIDENCE}/${phase}-status.json"
  browser_dump "${EVIDENCE}/${phase}-status.html"
  python3 scripts/final_qa_helpers.py validate-html --phase green "${EVIDENCE}/${phase}-status.html"
}
controlled_red() {
  assert_context
  RED_STATE=restore_required
  flux --context "${CONTEXT}" suspend kustomization external-secrets-operator-smoke -n flux-system
  if test "${KUBECRATE_QA_FAILPOINT:-}" = after-suspend; then kill -TERM "$$"; fi
  assert_context
  kubectl --context "${CONTEXT}" delete secret eso-smoke-source -n kubecrate-system
  if test "${KUBECRATE_QA_FAILPOINT:-}" = after-delete; then kill -TERM "$$"; fi
  assert_context
  kubectl --context "${CONTEXT}" wait --for=condition=Ready=false externalsecret/eso-smoke-projection -n kubecrate-system --timeout=180s || true
}
capture_red() {
  assert_context
  curl --fail --silent --show-error http://127.0.0.1:18080/status.json >"${EVIDENCE}/red-status.json"
  validate_status red "${EVIDENCE}/red-status.json"
  browser_dump "${EVIDENCE}/red-status.html"
  python3 scripts/final_qa_helpers.py validate-html --phase red "${EVIDENCE}/red-status.html"
}
restore_source_secret() {
  assert_context
  python3 scripts/final_qa_helpers.py restore --context "${CONTEXT}"
}
restore_if_needed() {
  test "$(kubectl config current-context 2>/dev/null)" = "${CONTEXT}" || return 1
  restore_source_secret || return 1
  sleep "${KUBECRATE_QA_OBSERVE_SECONDS:-35}"
  ensure_port_forward || return 1
  capture_green restored || return 1
  RED_STATE=none
}

capture_green "baseline"
controlled_red
# Let CrateCheck's configured interval observe the reversible failure.
sleep "${KUBECRATE_QA_OBSERVE_SECONDS:-35}"
capture_red
restore_if_needed
printf 'final-qa: PASS candidate=%s tree=%s branch=%s evidence=%s\n' "${CANDIDATE_SHA}" "${CANDIDATE_TREE}" "${QA_BRANCH}" "${EVIDENCE}"
