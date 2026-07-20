#!/usr/bin/env bash
# Direct disposable kind + Flux E2E runner.
# Creates a unique kind cluster, bootstraps Flux with HTTPS credentials,
# validates ESO, Envoy ingress, cert-manager TLS, and CrateCheck scenarios, then cleans up.
set -Eeuo pipefail

REPO="${KUBECRATE_GITHUB_REPO:-42aei/kubecrate}"
HTTPS_URL="https://github.com/${REPO}.git"
IDENTITY_MODE="${KUBECRATE_E2E_IDENTITY_MODE:-pr-head}"
PR_BRANCH="${KUBECRATE_PR_BRANCH:-kubecrate/envoy-after-eso-minimal-qa}"
PR_NUMBER="${KUBECRATE_PR_NUMBER:-19}"
EXPECTED_COMMIT="${KUBECRATE_EXPECTED_COMMIT:-$(git rev-parse HEAD)}"
SOURCE_BRANCH="${PR_BRANCH}"
CLUSTER_PREFIX="${KUBECRATE_E2E_CLUSTER_PREFIX:-kubecrate-e2e}"
CLUSTER=""
CONTEXT=""
SYNC_NAME=flux-system-sync
FLUX_CHART="oci://ghcr.io/fluxcd-community/charts/flux2"
FLUX_CHART_VERSION="${KUBECRATE_FLUX_VERSION:-2.18.4}"
ENTRYPOINT_ROOT="clusters/kind-dev-misc-local/entrypoint"
FLUX_HELM_VALUES="clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml"
FLUX_NAMESPACE=flux-system
TOKEN=""
CLUSTER_CREATED=false
PORT_FORWARD_PID=""
RED_STATE=none
CRATECHECK_PORT=18080
CRATECHECK_STATUS_URL="http://127.0.0.1:${CRATECHECK_PORT}/status.json"
ENVOY_STATUS_URL="http://127.0.0.1:10080/status.json"
ENVOY_TLS_STATUS_URL="https://cratecheck.local:10443/status.json"
RUN_TMP_ROOT="${KUBECRATE_E2E_TMP_ROOT:-${TMPDIR:-/tmp}}"
TMPDIR=""
EVIDENCE_ROOT="${KUBECRATE_E2E_EVIDENCE_DIR:-${PWD}/.tmp/direct-kind-flux-e2e-failures}"
CURRENT_PHASE=preflight
CURRENT_ASSERTION="preflight completed"
FAILURE_ASSERTION=""
EVIDENCE_COMMAND_TIMEOUT="${KUBECRATE_E2E_EVIDENCE_TIMEOUT:-5s}"
EVIDENCE_KUBECTL_REQUEST_TIMEOUT="${KUBECRATE_E2E_EVIDENCE_KUBECTL_TIMEOUT:-4s}"

fail() { printf 'direct-e2e: ERROR: %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

read_failure_evidence() {
  local label="$1"
  shift
  local evidence_rc
  set +e
  timeout --signal=TERM --kill-after=1s "${EVIDENCE_COMMAND_TIMEOUT}" "$@"
  evidence_rc=$?
  set -e
  if test "${evidence_rc}" -eq 124 || test "${evidence_rc}" -eq 137; then
    printf '[%s unavailable: evidence command timed out after %s]\n' \
      "${label}" "${EVIDENCE_COMMAND_TIMEOUT}"
  elif test "${evidence_rc}" -ne 0; then
    printf '[%s unavailable: evidence command exited %s]\n' "${label}" "${evidence_rc}"
  fi
}

write_failure_evidence() {
  local bundle="${EVIDENCE_ROOT}/${CLUSTER}"
  mkdir -p "${bundle}"
  chmod 700 "${EVIDENCE_ROOT}" "${bundle}" 2>/dev/null || true
  {
    printf 'result=fail\n'
    printf 'candidate=%s\n' "${EXPECTED_COMMIT}"
    printf 'ref=%s\n' "${SOURCE_BRANCH}"
    printf 'phase=%s\n' "${CURRENT_PHASE}"
    printf 'assertion=%s\n' "${FAILURE_ASSERTION:-${CURRENT_ASSERTION}}"
    printf 'cluster=%s\n' "${CLUSTER}"
    printf 'context=%s\n' "${CONTEXT}"
  } >"${bundle}/summary.txt"

  {
    printf '%s\n' '== nodes =='
    read_failure_evidence nodes kubectl --context "${CONTEXT}" \
      --request-timeout="${EVIDENCE_KUBECTL_REQUEST_TIMEOUT}" get nodes 2>&1
    printf '%s\n' '== Flux Kustomizations =='
    read_failure_evidence flux-kustomizations flux --context "${CONTEXT}" \
      get kustomizations -n "${FLUX_NAMESPACE}" 2>&1
    printf '%s\n' '== workload readiness =='
    read_failure_evidence deployments kubectl --context "${CONTEXT}" \
      --request-timeout="${EVIDENCE_KUBECTL_REQUEST_TIMEOUT}" get deployments -A 2>&1
  } >"${bundle}/readiness.txt"

  local status_file=""
  for candidate in cert-manager-restored-status.json cert-manager-red-status.json \
      cert-manager-baseline-status.json envoy-restored-status.json envoy-red-status.json \
      envoy-baseline-status.json restored-status.json red-status.json baseline-status.json; do
    if test -s "${TMPDIR}/${candidate}"; then status_file="${TMPDIR}/${candidate}"; break; fi
  done
  if test -n "${status_file}"; then
    python3 - "${status_file}" >"${bundle}/status-verdict.json" <<'PY' || \
      printf '{"status":"unavailable"}\n' >"${bundle}/status-verdict.json"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    data = json.load(stream)
verdict = {
    "status": data.get("status", data.get("overallStatus", data.get("overall_status", "unknown"))),
    "checks": [
        {"id": item.get("id", "unknown"), "status": item.get("status", item.get("state", "unknown"))}
        for item in data.get("checks", data.get("items", []))
        if isinstance(item, dict)
    ],
}
json.dump(verdict, sys.stdout, sort_keys=True)
sys.stdout.write("\n")
PY
  else
    printf '{"status":"not-observed"}\n' >"${bundle}/status-verdict.json"
  fi
  printf 'direct-e2e: failure evidence=%s\n' "${bundle}" >&2
}

assert_context() {
  actual="$(kubectl config current-context 2>/dev/null || true)"
  test "${actual}" = "${CONTEXT}" || fail "expected kubecontext ${CONTEXT}, got ${actual:-none}"
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  cleanup_failed=false
  if test "${rc}" -ne 0 && ${CLUSTER_CREATED}; then
    write_failure_evidence || true
  fi
  # Restore if we left the cluster in a broken state.
  if test "${RED_STATE}" != none && ${CLUSTER_CREATED}; then
    if test "$(kubectl config current-context 2>/dev/null || true)" = "${CONTEXT}"; then
      if test "${RED_STATE}" = eso_restore_required; then
        flux --context "${CONTEXT}" resume kustomization external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" >/dev/null 2>&1 || true
        flux --context "${CONTEXT}" reconcile kustomization external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
      elif test "${RED_STATE}" = envoy_restore_required; then
        kubectl --context "${CONTEXT}" -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
          -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":8080}]' >/dev/null 2>&1 || true
        flux --context "${CONTEXT}" resume kustomization envoy-gateway-smoke -n "${FLUX_NAMESPACE}" >/dev/null 2>&1 || true
        flux --context "${CONTEXT}" reconcile kustomization envoy-gateway-smoke -n "${FLUX_NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
      elif test "${RED_STATE}" = cert_manager_restore_required; then
        flux --context "${CONTEXT}" resume kustomization cert-manager-local-issuer -n "${FLUX_NAMESPACE}" >/dev/null 2>&1 || true
        flux --context "${CONTEXT}" reconcile kustomization cert-manager-local-issuer -n "${FLUX_NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
      fi
    fi
  fi
  test -z "${PORT_FORWARD_PID}" || kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  if ${CLUSTER_CREATED}; then
    cluster_before="$(cluster_state)"
    if test "${cluster_before}" = present; then
      kind delete cluster --name "${CLUSTER}" >/dev/null 2>&1 || cleanup_failed=true
    elif test "${cluster_before}" = unknown; then
      cleanup_failed=true
    fi
    test "$(cluster_state)" = absent || cleanup_failed=true
  fi
  # Scrub the token from the running process's memory.
  TOKEN=""
  if test -n "${TMPDIR}" && test -d "${TMPDIR}"; then
    rm -rf "${TMPDIR}" >/dev/null 2>&1 || true
  fi
  if ${cleanup_failed}; then
    printf 'direct-e2e: cleanup verification failed (cluster=%s)\n' "${CLUSTER}" >&2
    exit 1
  fi
  exit "${rc}"
}

cluster_state() {
  set +e
  clusters="$(kind get clusters 2>/dev/null)"
  state_rc=$?
  set -e
  test "${state_rc}" -eq 0 || { printf 'unknown\n'; return; }
  if grep -Fx "${CLUSTER}" <<<"${clusters}" >/dev/null; then printf 'present\n'; else printf 'absent\n'; fi
}

validate_status_json() {
  python3 scripts/validate-cratecheck-status.py --phase "$1" "$2"
}

validate_artifact_revision() {
  local revision="$1"
  if [[ ! "${revision}" =~ ^[^@[:space:]]+@sha1:([0-9a-f]{40})$ ]]; then
    fail "unsupported Flux artifact revision format: ${revision:-empty}"
  fi
  test "${BASH_REMATCH[1]}" = "${EXPECTED_COMMIT}" || \
    fail "Flux artifact commit ${BASH_REMATCH[1]} != expected ${EXPECTED_COMMIT}"
}

# Strict projected Secret decode: validates canonical base64 alphabet/padding,
# enforces exact expected value, never prints encoded or decoded content.
decode_smoke_value() {
  local encoded
  encoded="$(kubectl --context "${CONTEXT}" get secret "$1" \
    -n kubecrate-system -o jsonpath='{.data.smoke-test}' 2>/dev/null)" \
    || fail "could not read $1 smoke-test field"
  test -n "${encoded}" || fail "$1 smoke-test field empty"
  [[ "${encoded}" =~ ^[A-Za-z0-9+/]*={0,2}$ ]] || fail "$1 value not valid base64"
  local decoded
  decoded="$(printf '%s' "${encoded}" | base64 -d 2>/dev/null)" \
    || fail "could not decode $1"
  local canonical
  canonical="$(printf '%s' "${decoded}" | base64 | tr -d '\n')" \
    || fail "could not validate $1 encoding"
  test "${encoded}" = "${canonical}" || fail "$1 value not canonical base64"
  test "${decoded}" = "kubecrate-eso-smoke-ok" \
    || fail "projected $1 Secret value mismatch"
}

# ── Preflight ────────────────────────────────────────────────────────────────

for cmd in gh git kind kubectl helm flux kustomize curl python3 base64 timeout; do
  require "${cmd}"
done

# Verify faksibot is active and can read the repo.
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  fail "gh auth status failed — is faksibot logged in?"
fi

# Require exact faksibot identity before token retrieval and cluster creation.
active_user="$(gh api user --jq '.login' 2>/dev/null || true)"
test "${active_user}" = "faksibot" || fail "expected faksibot, got ${active_user:-unknown}"

# Obtain a runtime-only token.  Never print it.
TOKEN="$(gh auth token)"
test -n "${TOKEN}" || fail "gh auth token returned empty value"

case "${IDENTITY_MODE}" in
  pr-head)
    # Verify the PR branch head equals the expected commit.
    remote_sha="$(git ls-remote --heads origin "${PR_BRANCH}" | awk '{print $1}')"
    test -n "${remote_sha}" || fail "could not resolve remote branch ${PR_BRANCH}"
    test "${remote_sha}" = "${EXPECTED_COMMIT}" || \
      fail "remote branch ${PR_BRANCH} SHA ${remote_sha} != expected ${EXPECTED_COMMIT}"

    # Verify the PR head via gh API.
    pr_head="$(gh api "repos/${REPO}/pulls/${PR_NUMBER}" --jq '.head.sha' 2>/dev/null || true)"
    test -n "${pr_head}" || fail "could not read PR #${PR_NUMBER} head"
    test "${pr_head}" = "${EXPECTED_COMMIT}" || \
      fail "PR #${PR_NUMBER} head ${pr_head} != expected ${EXPECTED_COMMIT}"
    ;;
  current-main)
    SOURCE_BRANCH=main
    remote_sha="$(git ls-remote --heads origin main | awk '{print $1}')"
    test -n "${remote_sha}" || fail "could not resolve remote branch main"
    test "${remote_sha}" = "${EXPECTED_COMMIT}" || \
      fail "remote branch main SHA ${remote_sha} != expected ${EXPECTED_COMMIT}"

    IFS=$'\t' read -r pr_state pr_merged pr_merge_commit < <(
      gh api "repos/${REPO}/pulls/${PR_NUMBER}" \
        --jq '[.state, .merged, .merge_commit_sha] | @tsv' 2>/dev/null || true
    )
    test "${pr_state}" = closed && test "${pr_merged}" = true || \
      fail "PR #${PR_NUMBER} is not closed and merged"
    test "${pr_merge_commit}" = "${EXPECTED_COMMIT}" || \
      fail "PR #${PR_NUMBER} merge commit ${pr_merge_commit:-unknown} != expected ${EXPECTED_COMMIT}"
    ;;
  *) fail "unsupported identity mode: ${IDENTITY_MODE}" ;;
esac

# Verify local worktree is clean.
git diff --quiet || fail "worktree has unstaged changes"
git diff --cached --quiet || fail "worktree has staged changes"

# Verify kind/config.yaml exists.
test -f kind/config.yaml || fail "kind/config.yaml not found"

# ── Cluster ──────────────────────────────────────────────────────────────────

CLUSTER="${CLUSTER_PREFIX}-$(date +%s)-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom 2>/dev/null | head -c 6 || true)"
CONTEXT="kind-${CLUSTER}"

case "${CLUSTER}" in
  kind-dev-misc-local|kubecrate-fix-eso) fail "refusing shared cluster name ${CLUSTER}";;
esac

# Verify the cluster name is valid for kind.
[[ "${CLUSTER}" =~ ^[a-z0-9.-]+$ ]] || fail "invalid kind cluster name: ${CLUSTER}"
test "${#CLUSTER}" -le 63 || fail "kind cluster name too long: ${CLUSTER}"

# Verify cluster does not already exist.
if test "$(cluster_state)" != absent; then
  fail "cluster ${CLUSTER} already exists or state unknown"
fi

# Install cleanup trap.
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'failure_rc=$?; test -n "${FAILURE_ASSERTION}" || FAILURE_ASSERTION="${CURRENT_ASSERTION} (line ${LINENO}, rc ${failure_rc})"' ERR

# Create a private temporary directory for the token Secret manifest.
TMPDIR="$(mktemp -d "${RUN_TMP_ROOT%/}/kubecrate-direct-e2e.XXXXXX")"
chmod 700 "${TMPDIR}"

# Write the HTTPS credentials Secret manifest.
cat >"${TMPDIR}/flux-https-secret.yaml" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SYNC_NAME}
  namespace: ${FLUX_NAMESPACE}
stringData:
  username: git
  password: ${TOKEN}
EOF
chmod 600 "${TMPDIR}/flux-https-secret.yaml"

# Mark cluster as cleanup-owned before creation so a partial-create
# that lists the cluster but exits non-zero still triggers deletion.
CLUSTER_CREATED=true
# Create the kind cluster.
CURRENT_PHASE=cluster-create
CURRENT_ASSERTION="disposable kind cluster created and became Ready"
kind create cluster --name "${CLUSTER}" --config kind/config.yaml
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready node --all --timeout=180s

# ── Flux Bootstrap ───────────────────────────────────────────────────────────

CURRENT_PHASE=flux-bootstrap
CURRENT_ASSERTION="Flux bootstrap and root reconciliation completed"

assert_context
helm upgrade --install flux-system "${FLUX_CHART}" \
  --kube-context "${CONTEXT}" --version "${FLUX_CHART_VERSION}" \
  --namespace "${FLUX_NAMESPACE}" --create-namespace \
  -f "${FLUX_HELM_VALUES}"

# Wait for Flux controllers.
for deployment in source-controller kustomize-controller helm-controller; do
  assert_context
  kubectl --context "${CONTEXT}" wait --for=condition=Available \
    "deployment/${deployment}" -n "${FLUX_NAMESPACE}" --timeout=180s
done

# Apply the HTTPS credentials Secret.
assert_context
kubectl --context "${CONTEXT}" apply -f "${TMPDIR}/flux-https-secret.yaml"

# Scrub the token from the Secret manifest file immediately after apply.
rm -f "${TMPDIR}/flux-https-secret.yaml"

# Render the entrypoint with HTTPS source override and apply.
assert_context
kustomize build "${ENTRYPOINT_ROOT}" | \
  python3 scripts/render-direct-flux-source.py --https-url "${HTTPS_URL}" \
    --branch "${SOURCE_BRANCH}" | \
  kubectl --context "${CONTEXT}" apply -f -

# Wait for the HelmRelease to become Ready.
assert_context
kubectl --context "${CONTEXT}" annotate --overwrite \
  "helmrelease/${SYNC_NAME}" -n "${FLUX_NAMESPACE}" \
  "reconcile.fluxcd.io/requestedAt=$(date +%s)"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  "helmrelease/${SYNC_NAME}" -n "${FLUX_NAMESPACE}" --timeout=180s

# Reconcile source and root Kustomization.
assert_context
flux --context "${CONTEXT}" reconcile source git "${SYNC_NAME}" \
  -n "${FLUX_NAMESPACE}" --timeout=180s
assert_context
flux --context "${CONTEXT}" reconcile kustomization "${SYNC_NAME}" \
  -n "${FLUX_NAMESPACE}" --timeout=300s

# Verify the reconciled revision matches the expected commit.
actual_revision="$(kubectl --context "${CONTEXT}" get gitrepository "${SYNC_NAME}" \
  -n "${FLUX_NAMESPACE}" -o jsonpath='{.status.artifact.revision}' 2>/dev/null || true)"
test -n "${actual_revision}" || fail "could not read Flux artifact revision"
validate_artifact_revision "${actual_revision}"

# Wait for Flux child Kustomizations in dependency order.
CURRENT_PHASE=flux-child-readiness
CURRENT_ASSERTION="external-secrets-operator Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/external-secrets-operator -n "${FLUX_NAMESPACE}" --timeout=300s
CURRENT_ASSERTION="external-secrets-operator-smoke Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" --timeout=300s
CURRENT_ASSERTION="cratecheck Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/cratecheck -n "${FLUX_NAMESPACE}" --timeout=300s
CURRENT_ASSERTION="cert-manager Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/cert-manager -n "${FLUX_NAMESPACE}" --timeout=300s
CURRENT_ASSERTION="cert-manager local issuer Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/cert-manager-local-issuer -n "${FLUX_NAMESPACE}" --timeout=300s
CURRENT_ASSERTION="envoy-gateway Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/envoy-gateway -n "${FLUX_NAMESPACE}" --timeout=300s
CURRENT_ASSERTION="envoy-gateway-smoke Kustomization became Ready"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/envoy-gateway-smoke -n "${FLUX_NAMESPACE}" --timeout=300s

# The smoke Kustomization can be Ready before Envoy has programmed its generated
# data plane. Gate baseline status and host ingress on the Gateway contract.
CURRENT_ASSERTION="Envoy smoke Gateway became Programmed"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Programmed \
  gateway/kubecrate-envoy-smoke -n core-envoy-gateway --timeout=300s

# Wait for ESO and CrateCheck deployments.
CURRENT_PHASE=workload-readiness
CURRENT_ASSERTION="CrateCheck Deployment became Available"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Available \
  deployment/cratecheck -n cratecheck --timeout=300s
CURRENT_ASSERTION="External Secrets Deployment became Available"
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Available \
  deployment/external-secrets -n core-external-secrets-operator --timeout=180s

# ── ESO Validation ───────────────────────────────────────────────────────────

CURRENT_PHASE=eso-green
CURRENT_ASSERTION="projected ESO Secret matched the expected value"

# Verify the projected Secret value exactly, without printing it.
assert_context
decode_smoke_value eso-smoke-projected

# ── CrateCheck Green ─────────────────────────────────────────────────────────

# Start port-forward.
assert_context
kubectl --context "${CONTEXT}" port-forward -n cratecheck service/cratecheck \
  "${CRATECHECK_PORT}:8080" >/dev/null 2>&1 &
PORT_FORWARD_PID=$!

# Wait for port-forward readiness.
deadline=$((SECONDS + 20))
while (( SECONDS < deadline )); do
  if kill -0 "${PORT_FORWARD_PID}" 2>/dev/null && \
     curl --fail --silent "${CRATECHECK_STATUS_URL}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
  fail "port-forward process died"
fi
if ! curl --fail --silent "${CRATECHECK_STATUS_URL}" >/dev/null 2>&1; then
  fail "CrateCheck not reachable after port-forward"
fi

# Capture baseline green.
CURRENT_PHASE=cratecheck-green
CURRENT_ASSERTION="CrateCheck baseline status was all green"
curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" >"${TMPDIR}/baseline-status.json"
validate_status_json green "${TMPDIR}/baseline-status.json"

# ── Controlled Red ───────────────────────────────────────────────────────────

CURRENT_PHASE=eso-controlled-red
CURRENT_ASSERTION="only the expected ESO checks became red"

RED_STATE=eso_restore_required

assert_context
flux --context "${CONTEXT}" suspend kustomization external-secrets-operator-smoke \
  -n "${FLUX_NAMESPACE}"

assert_context
kubectl --context "${CONTEXT}" delete externalsecret eso-smoke-projection -n kubecrate-system

# Capture red.
curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" >"${TMPDIR}/red-status.json"
validate_status_json eso-red "${TMPDIR}/red-status.json"

# ── Restore Green ────────────────────────────────────────────────────────────

CURRENT_PHASE=eso-restore-green
CURRENT_ASSERTION="ESO projection and CrateCheck status returned to green"

assert_context
flux --context "${CONTEXT}" resume kustomization external-secrets-operator-smoke \
  -n "${FLUX_NAMESPACE}"
assert_context
flux --context "${CONTEXT}" reconcile kustomization external-secrets-operator-smoke \
  -n "${FLUX_NAMESPACE}" --timeout=180s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" --timeout=180s

# Verify the projected value is restored.
assert_context
decode_smoke_value eso-smoke-projected

# Capture restored green.
curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" >"${TMPDIR}/restored-status.json"
validate_status_json green "${TMPDIR}/restored-status.json"

RED_STATE=none

# ── Envoy Gateway Scenario ───────────────────────────────────────────────────

CURRENT_PHASE=envoy-green
CURRENT_ASSERTION="Envoy ingress baseline status was all green"

# Prove the host ingress path and the full all-green JSON contract.
curl --fail --silent --show-error "${ENVOY_STATUS_URL}" >"${TMPDIR}/envoy-baseline-status.json"
validate_status_json green "${TMPDIR}/envoy-baseline-status.json"

RED_STATE=envoy_restore_required
CURRENT_PHASE=envoy-controlled-red
CURRENT_ASSERTION="only envoy-httproute-ready became red"
assert_context
flux --context "${CONTEXT}" suspend kustomization envoy-gateway-smoke \
  -n "${FLUX_NAMESPACE}"
assert_context
kubectl --context "${CONTEXT}" -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":9999}]'

# Poll the direct path because ingress is intentionally unavailable during red.
deadline=$((SECONDS + 60))
while (( SECONDS < deadline )); do
  curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" >"${TMPDIR}/envoy-red-status.json"
  if validate_status_json envoy-red "${TMPDIR}/envoy-red-status.json" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
validate_status_json envoy-red "${TMPDIR}/envoy-red-status.json"

# Restore the exact backend port and GitOps reconciliation.
CURRENT_PHASE=envoy-restore-green
CURRENT_ASSERTION="Envoy route and all checks returned to green"
assert_context
kubectl --context "${CONTEXT}" -n cratecheck patch httproute envoy-smoke-cratecheck --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/backendRefs/0/port","value":8080}]'
assert_context
flux --context "${CONTEXT}" resume kustomization envoy-gateway-smoke \
  -n "${FLUX_NAMESPACE}"
assert_context
flux --context "${CONTEXT}" reconcile kustomization envoy-gateway-smoke \
  -n "${FLUX_NAMESPACE}" --timeout=180s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/envoy-gateway-smoke -n "${FLUX_NAMESPACE}" --timeout=180s

deadline=$((SECONDS + 60))
while (( SECONDS < deadline )); do
  if curl --fail --silent --show-error "${ENVOY_STATUS_URL}" \
      >"${TMPDIR}/envoy-restored-status.json" 2>/dev/null && \
     validate_status_json green "${TMPDIR}/envoy-restored-status.json" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error "${ENVOY_STATUS_URL}" >"${TMPDIR}/envoy-restored-status.json"
validate_status_json green "${TMPDIR}/envoy-restored-status.json"
RED_STATE=none

# ── cert-manager TLS Scenario ────────────────────────────────────────────────

CURRENT_PHASE=cert-manager-tls-green
CURRENT_ASSERTION="cert-manager-issued certificate provided trusted HTTPS"
assert_context
kubectl --context "${CONTEXT}" get secret cratecheck-tls -n cratecheck \
  -o jsonpath='{.data.ca\.crt}' | base64 -d >"${TMPDIR}/cratecheck-ca.crt"
test -s "${TMPDIR}/cratecheck-ca.crt" || fail "cert-manager TLS CA certificate is empty"
curl --fail --silent --show-error --cacert "${TMPDIR}/cratecheck-ca.crt" \
  --resolve cratecheck.local:10443:127.0.0.1 "${ENVOY_TLS_STATUS_URL}" \
  >"${TMPDIR}/cert-manager-baseline-status.json"
validate_status_json green "${TMPDIR}/cert-manager-baseline-status.json"

RED_STATE=cert_manager_restore_required
CURRENT_PHASE=cert-manager-controlled-red
CURRENT_ASSERTION="only the cert-manager TLS Certificate check became red"
assert_context
flux --context "${CONTEXT}" suspend kustomization cert-manager-local-issuer \
  -n "${FLUX_NAMESPACE}"
assert_context
kubectl --context "${CONTEXT}" delete certificate cratecheck-tls -n cratecheck
curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" \
  >"${TMPDIR}/cert-manager-red-status.json"
validate_status_json cert-manager-red "${TMPDIR}/cert-manager-red-status.json"
curl --fail --silent --show-error --cacert "${TMPDIR}/cratecheck-ca.crt" \
  --resolve cratecheck.local:10443:127.0.0.1 "${ENVOY_TLS_STATUS_URL}" >/dev/null

CURRENT_PHASE=cert-manager-restore-green
CURRENT_ASSERTION="cert-manager TLS issuance, HTTPS, and all checks returned to green"
assert_context
flux --context "${CONTEXT}" resume kustomization cert-manager-local-issuer \
  -n "${FLUX_NAMESPACE}"
assert_context
flux --context "${CONTEXT}" reconcile kustomization cert-manager-local-issuer \
  -n "${FLUX_NAMESPACE}" --timeout=180s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/cert-manager-local-issuer -n "${FLUX_NAMESPACE}" --timeout=180s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  certificate/cratecheck-tls -n cratecheck --timeout=180s
kubectl --context "${CONTEXT}" get secret cratecheck-tls -n cratecheck \
  -o jsonpath='{.data.ca\.crt}' | base64 -d >"${TMPDIR}/cratecheck-ca.crt"

deadline=$((SECONDS + 60))
while (( SECONDS < deadline )); do
  if curl --fail --silent --show-error --cacert "${TMPDIR}/cratecheck-ca.crt" \
      --resolve cratecheck.local:10443:127.0.0.1 "${ENVOY_TLS_STATUS_URL}" \
      >"${TMPDIR}/cert-manager-restored-status.json" 2>/dev/null && \
     validate_status_json green "${TMPDIR}/cert-manager-restored-status.json" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error --cacert "${TMPDIR}/cratecheck-ca.crt" \
  --resolve cratecheck.local:10443:127.0.0.1 "${ENVOY_TLS_STATUS_URL}" \
  >"${TMPDIR}/cert-manager-restored-status.json"
validate_status_json green "${TMPDIR}/cert-manager-restored-status.json"
RED_STATE=none

# Kill port-forward before cleanup.
test -z "${PORT_FORWARD_PID}" || kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
PORT_FORWARD_PID=""

printf 'direct-e2e: PASS commit=%s cluster=%s\n' "${EXPECTED_COMMIT}" "${CLUSTER}"
