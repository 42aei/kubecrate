#!/usr/bin/env bash
# Direct disposable kind + Flux E2E runner.
# Creates a unique kind cluster, bootstraps Flux with HTTPS credentials,
# validates ESO and CrateCheck, runs controlled red/green, and cleans up.
set -Eeuo pipefail

REPO="${KUBECRATE_GITHUB_REPO:-42aei/kubecrate}"
HTTPS_URL="https://github.com/${REPO}.git"
PR_BRANCH="${KUBECRATE_PR_BRANCH:-kubecrate/cratecheck-restack-eso}"
EXPECTED_COMMIT="${KUBECRATE_EXPECTED_COMMIT:-$(git rev-parse HEAD)}"
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
TMPDIR=""

fail() { printf 'direct-e2e: ERROR: %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

assert_context() {
  actual="$(kubectl config current-context 2>/dev/null || true)"
  test "${actual}" = "${CONTEXT}" || fail "expected kubecontext ${CONTEXT}, got ${actual:-none}"
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  cleanup_failed=false
  # Restore if we left the cluster in a broken state.
  if test "${RED_STATE}" != none && ${CLUSTER_CREATED}; then
    if test "$(kubectl config current-context 2>/dev/null || true)" = "${CONTEXT}"; then
      flux --context "${CONTEXT}" resume kustomization external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" >/dev/null 2>&1 || true
      flux --context "${CONTEXT}" reconcile kustomization external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
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

for cmd in gh git kind kubectl helm flux kustomize curl python3 base64; do
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

# Verify the PR branch head equals the expected commit.
remote_sha="$(git ls-remote --heads origin "${PR_BRANCH}" | awk '{print $1}')"
test -n "${remote_sha}" || fail "could not resolve remote branch ${PR_BRANCH}"
test "${remote_sha}" = "${EXPECTED_COMMIT}" || \
  fail "remote branch ${PR_BRANCH} SHA ${remote_sha} != expected ${EXPECTED_COMMIT}"

# Verify the PR head via gh API.
pr_head="$(gh api "repos/${REPO}/pulls/17" --jq '.head.sha' 2>/dev/null || true)"
test -n "${pr_head}" || fail "could not read PR #17 head"
test "${pr_head}" = "${EXPECTED_COMMIT}" || \
  fail "PR #17 head ${pr_head} != expected ${EXPECTED_COMMIT}"

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

# Create a private temporary directory for the token Secret manifest.
TMPDIR="$(mktemp -d)"
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
kind create cluster --name "${CLUSTER}" --config kind/config.yaml
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready node --all --timeout=180s

# ── Flux Bootstrap ───────────────────────────────────────────────────────────

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
  python3 scripts/render-direct-flux-source.py --https-url "${HTTPS_URL}" | \
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
if ! printf '%s' "${actual_revision}" | grep -qF "${EXPECTED_COMMIT}"; then
  fail "Flux artifact revision ${actual_revision} does not contain expected ${EXPECTED_COMMIT}"
fi

# Wait for Flux child Kustomizations in dependency order.
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/external-secrets-operator -n "${FLUX_NAMESPACE}" --timeout=300s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/external-secrets-operator-smoke -n "${FLUX_NAMESPACE}" --timeout=300s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Ready \
  kustomization/cratecheck -n "${FLUX_NAMESPACE}" --timeout=300s

# Wait for ESO and CrateCheck deployments.
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Available \
  deployment/cratecheck -n cratecheck --timeout=300s
assert_context
kubectl --context "${CONTEXT}" wait --for=condition=Available \
  deployment/external-secrets -n core-external-secrets-operator --timeout=180s

# ── ESO Validation ───────────────────────────────────────────────────────────

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
curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" >"${TMPDIR}/baseline-status.json"
validate_status_json green "${TMPDIR}/baseline-status.json"

# ── Controlled Red ───────────────────────────────────────────────────────────

RED_STATE=restore_required

assert_context
flux --context "${CONTEXT}" suspend kustomization external-secrets-operator-smoke \
  -n "${FLUX_NAMESPACE}"

assert_context
kubectl --context "${CONTEXT}" delete externalsecret eso-smoke-projection -n kubecrate-system

# Capture red.
curl --fail --silent --show-error "${CRATECHECK_STATUS_URL}" >"${TMPDIR}/red-status.json"
validate_status_json red "${TMPDIR}/red-status.json"

# ── Restore Green ────────────────────────────────────────────────────────────

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

# Kill port-forward before cleanup.
test -z "${PORT_FORWARD_PID}" || kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
PORT_FORWARD_PID=""

printf 'direct-e2e: PASS commit=%s cluster=%s\n' "${EXPECTED_COMMIT}" "${CLUSTER}"
