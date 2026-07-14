#!/usr/bin/env bash
# Sourceable production lifecycle for final-qa-exact-tree.sh.
# Callers must initialize the documented lifecycle globals before installing traps.

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
  if ${EVIDENCE_READY:-false}; then
    key_title="${KEY_TITLE:-kubecrate-qa-${RUN_ID:-unknown}}"
    key_marker="${OWNED_KEY_MARKER:-${EVIDENCE}/owned-deploy-key.json}"
    python3 scripts/final_qa_helpers.py cleanup-deploy-key-markers \
      --repo "${REPO}" --title "${key_title}" --evidence-root "${EVIDENCE}" \
      --marker "${key_marker}" >/dev/null || cleanup_failed=true
  fi
  if ${EVIDENCE_READY:-false}; then
    python3 scripts/final_qa_helpers.py cleanup-ref-markers \
      --repo "${REPO}" --ref "refs/heads/${QA_BRANCH}" --sha "${CANDIDATE_SHA}" \
      --evidence-root "${EVIDENCE}" --owned-marker "${OWNED_REF_MARKER}" \
      --uncertain-marker "${UNCERTAIN_REF_MARKER}" --branch-created "${BRANCH_CREATED}" \
      >/dev/null || cleanup_failed=true
  elif ${BRANCH_CREATED}; then
    printf 'final-qa: created branch lacks validated evidence root\n' >&2
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
  if ${EVIDENCE_READY:-false}; then
    python3 scripts/final_qa_helpers.py cleanup-private --evidence-root "${EVIDENCE}" || cleanup_failed=true
  fi
  git diff --quiet && git diff --cached --quiet || cleanup_failed=true
  test "$(git write-tree)" = "${INITIAL_TREE}" || cleanup_failed=true
  if ${cleanup_failed}; then
    printf 'final-qa: cleanup verification failed (key=%s branch=%s cluster=%s)\n' "${KEY_ID:-none}" "${QA_BRANCH}" "${CLUSTER}" >&2
    exit 1
  fi
  exit "${rc}"
}

install_cleanup_traps() {
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

port_forward_ready() {
  test -n "${PORT_FORWARD_PID}" && kill -0 "${PORT_FORWARD_PID}" 2>/dev/null || return 1
  curl --fail --silent "${KUBECRATE_QA_STATUS_URL:-http://127.0.0.1:18080/status.json}" >/dev/null 2>&1
}

wait_port_forward() {
  scripts/wait-port-forward.sh "${PORT_FORWARD_PID}" "${EVIDENCE}/port-forward.log" \
    "${KUBECRATE_QA_STATUS_URL:-http://127.0.0.1:18080/status.json}" "${KUBECRATE_QA_PORT_FORWARD_TIMEOUT:-20}" \
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

browser_dump() {
  out="$1"
  browser=""
  for candidate in chromium chromium-browser google-chrome; do command -v "${candidate}" >/dev/null 2>&1 && browser="${candidate}" && break; done
  test -n "${browser}" || fail "Chromium/Chrome required for browser UI evidence"
  "${browser}" --headless --no-sandbox --disable-gpu --dump-dom "${KUBECRATE_QA_UI_URL:-http://127.0.0.1:18080/status}" >"${out}"
}

validate_status() {
  expected="$1"; file="$2"
  python3 scripts/final_qa_helpers.py validate-json --phase "${expected}" "${file}"
}

capture_green() {
  phase="$1"; assert_context
  curl --fail --silent --show-error "${KUBECRATE_QA_STATUS_URL:-http://127.0.0.1:18080/status.json}" >"${EVIDENCE}/${phase}-status.json"
  validate_status green "${EVIDENCE}/${phase}-status.json"
  browser_dump "${EVIDENCE}/${phase}-status.html"
  python3 scripts/final_qa_helpers.py validate-html --phase green "${EVIDENCE}/${phase}-status.html"
}

controlled_red() {
  assert_context
  RED_STATE=restore_required
  flux --context "${CONTEXT}" suspend kustomization external-secrets-operator-smoke -n flux-system
  assert_context
  kubectl --context "${CONTEXT}" delete secret eso-smoke-source -n kubecrate-system
  assert_context
  kubectl --context "${CONTEXT}" wait --for=condition=Ready=false externalsecret/eso-smoke-projection -n kubecrate-system --timeout=180s || true
}

capture_red() {
  assert_context
  curl --fail --silent --show-error "${KUBECRATE_QA_STATUS_URL:-http://127.0.0.1:18080/status.json}" >"${EVIDENCE}/red-status.json"
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
