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
# shellcheck source=final-qa-lifecycle.sh
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/final-qa-lifecycle.sh"
install_cleanup_traps

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
  --ref "refs/heads/${QA_BRANCH}" --sha "${CANDIDATE_SHA}" \
  --evidence-root "${EVIDENCE}" --marker "${OWNED_REF_MARKER}"
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

start_port_forward

capture_green "baseline"
controlled_red
# Let CrateCheck's configured interval observe the reversible failure.
sleep "${KUBECRATE_QA_OBSERVE_SECONDS:-35}"
capture_red
restore_if_needed
printf 'final-qa: PASS candidate=%s tree=%s branch=%s evidence=%s\n' "${CANDIDATE_SHA}" "${CANDIDATE_TREE}" "${QA_BRANCH}" "${EVIDENCE}"
