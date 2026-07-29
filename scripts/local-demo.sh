#!/usr/bin/env bash
# Retained kind-first Kubecrate demo lifecycle.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
COMMAND="${1:-help}"
STATE_ROOT="${KUBECRATE_LOCAL_STATE_DIR:-$ROOT/.tmp/kubecrate-local}"
STATE_FILE="$STATE_ROOT/state.json"; EVIDENCE_DIR="$STATE_ROOT/evidence/latest"; CA_FILE="$STATE_ROOT/cratecheck-ca.crt"
CLUSTER_OVERRIDE_SET="${KUBECRATE_LOCAL_CLUSTER+x}"; CLUSTER="${KUBECRATE_LOCAL_CLUSTER:-kubecrate-local}"; REQUESTED_CLUSTER="$CLUSTER"; CONTEXT="kind-$CLUSTER"
SOURCE_URL=""; SOURCE_REF=""; EXPECTED_COMMIT=""; OBSERVED_REVISION=""; PHASE=preflight; FAILURE_STATE_ARMED=false; EVIDENCE_ON_ERROR=false; EVIDENCE_CAPTURED=false; EVIDENCE_SCRATCH=""; ERROR_REPORTED=false; CAPTURE_PID=""
SYNC_NAME=flux-system-sync; FLUX_NAMESPACE=flux-system
FLUX_CHART=oci://ghcr.io/fluxcd-community/charts/flux2; FLUX_CHART_VERSION="${KUBECRATE_FLUX_VERSION:-2.18.4}"
ENTRYPOINT_ROOT=clusters/kind-dev-misc-local/entrypoint
FLUX_HELM_VALUES=clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml
HTTP_URL=http://127.0.0.1:10080/status.json; HTTPS_URL=https://cratecheck.local:10443/status.json
WAIT_SHORT="${KUBECRATE_LOCAL_WAIT_SHORT:-180s}"; WAIT_LONG="${KUBECRATE_LOCAL_WAIT_LONG:-300s}"
EVIDENCE_TIMEOUT="${KUBECRATE_LOCAL_EVIDENCE_TIMEOUT:-8s}"
PROBE_TIMEOUT="${KUBECRATE_LOCAL_PROBE_TIMEOUT:-15s}"
OPERATION_GRACE="${KUBECRATE_LOCAL_OPERATION_GRACE:-5s}"

sanitize(){ sed -E -e 's#(https?://)[^/@[:space:]]+@#\1[redacted]@#g' -e 's#([Aa]uthoriz[a]tion:[[:space:]]+([Bb]asic|[Bb]earer)[[:space:]]+)[^[:space:]]+#\1[redacted]#g' -e 's#([Bb]earer[[:space:]]+)[^[:space:]]+#\1[redacted]#g' -e 's#(token|password|identity|secret|credential)([=:][[:space:]]*)[^[:space:]]+#\1\2[redacted]#Ig'; }
exec > >(sanitize) 2> >(sanitize >&2)
recovery(){ printf 'local-demo: recovery=make local-evidence; make local-status; inspect context=%s; choose make local-restart, make local-recreate, or make local-down\n' "$CONTEXT" >&2; }
capture_failure_once(){ if $EVIDENCE_ON_ERROR && ! $EVIDENCE_CAPTURED; then EVIDENCE_CAPTURED=true; capture_evidence failed >/dev/null 2>&1 || true; fi; }
error_owner(){ local rc="$1" message="$2"; ERROR_REPORTED=true; printf 'local-demo: ERROR phase=%s message=%s\n' "$PHASE" "$message" >&2; recovery; capture_failure_once; exit "$rc"; }
fail(){ error_owner "${FAIL_RC:-1}" "$*"; }
bounded_probe(){ timeout --signal=TERM --kill-after=2s "$PROBE_TIMEOUT" "$@"; }
duration_with_grace(){ python3 - "$1" "$OPERATION_GRACE" <<'PY'
import re,sys
def seconds(value):
    match=re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([smhd]?)",value)
    if not match: raise SystemExit(f"invalid timeout duration: {value}")
    return float(match.group(1))*{"":1,"s":1,"m":60,"h":3600,"d":86400}[match.group(2)]
print(f"{seconds(sys.argv[1])+seconds(sys.argv[2]):g}s")
PY
}
bounded_operation(){ local bound; bound="$(duration_with_grace "$1")"; shift; timeout --signal=TERM --kill-after=2s "$bound" "$@"; }
require(){ command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"; }
validate_cluster_identity(){ [[ "$CLUSTER" =~ ^kubecrate-local(-[a-z0-9]+)*$ ]] && test ${#CLUSTER} -le 63 || fail "refusing protected cluster or non-demo identity $CLUSTER; allowed: kubecrate-local or kubecrate-local-<lowercase-alphanumeric-segment>"; CONTEXT="kind-$CLUSTER"; }
cluster_state(){ validate_cluster_identity; local out rc; set +e; out="$(bounded_probe kind get clusters 2>/dev/null)"; rc=$?; set -e; test $rc -eq 0 || { echo unknown; return; }; grep -Fx "$CLUSTER" <<<"$out" >/dev/null && echo present || echo absent; }
normalize_url(){ local raw="$1" path; case "$raw" in git@github.com:*) path="${raw#git@github.com:}";; ssh://git@github.com/*) path="${raw#ssh://git@github.com/}";; https://github.com/*) path="${raw#https://github.com/}";; http://github.com/*) path="${raw#http://github.com/}";; *) fail "cannot derive supported GitHub URL; set KUBECRATE_LOCAL_SOURCE_URL";; esac; path="${path%.git}"; [[ "$path" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "ambiguous repository path"; printf 'https://github.com/%s.git\n' "$path"; }
normalize_ssh_url(){ local raw="$1" path; case "$raw" in git@github.com:*) path="${raw#git@github.com:}";; ssh://git@github.com/*) path="${raw#ssh://git@github.com/}";; https://github.com/*) path="${raw#https://github.com/}";; http://github.com/*) path="${raw#http://github.com/}";; *) fail "cannot derive supported GitHub SSH URL; set KUBECRATE_LOCAL_SOURCE_URL";; esac; path="${path%.git}"; [[ "$path" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "ambiguous repository path"; printf 'ssh://git@github.com/%s.git\n' "$path"; }
derive_source(){
  PHASE=source-identity
  EXPECTED_COMMIT="$(git rev-parse --verify 'HEAD^{commit}' 2>/dev/null)" || fail "HEAD is not a commit"
  test ${#EXPECTED_COMMIT} -eq 40 || fail "HEAD is not a full commit"
  test -z "$(git status --porcelain=v1 --untracked-files=all)" || fail "checkout is dirty"
  SOURCE_REF="${KUBECRATE_LOCAL_SOURCE_REF:-$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)}"; test -n "$SOURCE_REF" || fail "detached HEAD requires KUBECRATE_LOCAL_SOURCE_REF"
  git check-ref-format --branch "$SOURCE_REF" >/dev/null 2>&1 || fail "selected source ref is invalid"
  local raw="${KUBECRATE_LOCAL_SOURCE_URL:-$(git remote get-url origin 2>/dev/null || true)}"; test -n "$raw" || fail "origin URL unavailable"
  SOURCE_URL="$(normalize_url "$raw")"
  local advertised rc count
  if test -n "${KUBECRATE_LOCAL_ANONYMOUS_SOURCE:-}"; then
    local isolated_home; isolated_home="$(mktemp -d)"; set +e
    advertised="$(env -i PATH="$PATH" HOME="$isolated_home" CALL_LOG="${CALL_LOG:-}" FAKE_SECRET_SENTINEL="${FAKE_SECRET_SENTINEL:-}" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 GIT_ASKPASS= SSH_ASKPASS= timeout --signal=TERM --kill-after=2s "$PROBE_TIMEOUT" git -c credential.helper= -c core.askPass= ls-remote --heads "$SOURCE_URL" "refs/heads/$SOURCE_REF" 2>&1)"; rc=$?; rm -rf "$isolated_home"; set -e
    test $rc -eq 0 || { printf '%s\n' "$advertised" >&2; FAIL_RC=$rc fail "selected source is not anonymously accessible"; }
  else
    set +e
    advertised="$(GIT_TERMINAL_PROMPT=0 timeout --signal=TERM --kill-after=2s "$PROBE_TIMEOUT" git ls-remote --heads "$raw" "refs/heads/$SOURCE_REF" 2>&1)"; rc=$?; set -e
    test $rc -eq 0 || { printf '%s\n' "$advertised" >&2; FAIL_RC=$rc fail "selected source is not accessible with current Git credentials"; }
  fi
  count="$(awk 'NF{n++} END{print n+0}' <<<"$advertised")"; test "$count" -eq 1 || fail "selected remote/ref did not resolve exactly once"
  test "$(awk 'NR==1{print $1}' <<<"$advertised")" = "$EXPECTED_COMMIT" || fail "selected remote/ref does not advertise checkout commit $EXPECTED_COMMIT"
  test "$(awk 'NR==1{print $2}' <<<"$advertised")" = "refs/heads/$SOURCE_REF" || fail "selected remote returned unexpected ref"
}
write_state(){ validate_cluster_identity; mkdir -p "$STATE_ROOT"; chmod 700 "$STATE_ROOT"; python3 - "$STATE_FILE" "$1" "$2" "$CLUSTER" "$CONTEXT" "$SOURCE_URL" "$SOURCE_REF" "$EXPECTED_COMMIT" <<'PY'
import json,os,sys,tempfile
path,lifecycle,phase,cluster,context,url,ref,commit=sys.argv[1:]
data={"schemaVersion":1,"owner":"kubecrate-retained-local-demo","lifecycle":lifecycle,"phase":phase,"cluster":cluster,"context":context,"sourceUrl":url,"sourceRef":ref,"expectedCommit":commit}
fd,tmp=tempfile.mkstemp(dir=os.path.dirname(path),prefix="state.")
with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(data,f,sort_keys=True); f.write("\n")
os.chmod(tmp,0o600); os.replace(tmp,path)
PY
}
state_value(){ python3 - "$STATE_FILE" "$1" <<'PY'
import json,sys
with open(sys.argv[1],encoding="utf-8") as f: print(json.load(f).get(sys.argv[2],""))
PY
}
load_state(){ PHASE=state; test -s "$STATE_FILE" || fail "no retained demo state at $STATE_FILE"; test "$(state_value owner)" = kubecrate-retained-local-demo || fail "invalid state owner"; local recorded_cluster="$(state_value cluster)" recorded_context="$(state_value context)"; if test -n "$CLUSTER_OVERRIDE_SET"; then test "$recorded_cluster" = "$REQUESTED_CLUSTER" || fail "recorded cluster does not match requested cluster"; fi; CLUSTER="$recorded_cluster"; CONTEXT="$recorded_context"; validate_cluster_identity; test "$CONTEXT" = "kind-$CLUSTER" || fail "state identity is ambiguous"; SOURCE_URL="$(state_value sourceUrl)"; SOURCE_REF="$(state_value sourceRef)"; EXPECTED_COMMIT="$(state_value expectedCommit)"; }
assert_context(){ local actual="$(bounded_probe kubectl config current-context 2>/dev/null || true)"; test "$actual" = "$CONTEXT" || fail "expected current context $CONTEXT, got ${actual:-none}"; }
validate_revision(){ [[ "$1" =~ ^([^@[:space:]]+)@sha1:([0-9a-f]{40})$ ]] || fail "unsupported Flux artifact revision: ${1:-empty}"; test "${BASH_REMATCH[1]}" = "$SOURCE_REF" && test "${BASH_REMATCH[2]}" = "$EXPECTED_COMMIT" || fail "Flux revision mismatch"; }
cleanup_scratch(){ test -z "$EVIDENCE_SCRATCH" || rm -rf "$EVIDENCE_SCRATCH"; EVIDENCE_SCRATCH=""; }
run_capture(){ local label="$1" artifact="$2"; shift 2; local raw="$EVIDENCE_SCRATCH/.${label}.raw" rc; set +e; timeout --signal=TERM --kill-after=2s "$EVIDENCE_TIMEOUT" "$@" >"$raw" 2>&1 & CAPTURE_PID=$!; wait "$CAPTURE_PID"; rc=$?; CAPTURE_PID=""; set -e; sanitize <"$raw" >"$EVIDENCE_SCRATCH/$artifact"; rm -f "$raw"; printf '%s\n' "$rc" >"$EVIDENCE_SCRATCH/.${label}.rc"; test $rc -eq 0 || printf '[unavailable rc=%s]\n' "$rc" >>"$EVIDENCE_SCRATCH/$artifact"; return 0; }
capture_http(){ local label="$1" artifact="$2"; shift 2; local raw="$EVIDENCE_SCRATCH/.${label}.raw" err="$EVIDENCE_SCRATCH/.${label}.err" rc semantic=error; set +e; timeout --signal=TERM --kill-after=2s "$EVIDENCE_TIMEOUT" curl --fail --silent --show-error "$@" >"$raw" 2>"$err" & CAPTURE_PID=$!; wait "$CAPTURE_PID"; rc=$?; CAPTURE_PID=""; set -e; sanitize <"$err" >"$EVIDENCE_SCRATCH/${label}-error.txt"; if test $rc -eq 0 && test -s "$raw"; then sanitize <"$raw" >"$EVIDENCE_SCRATCH/$artifact"; set +e; python3 scripts/validate-cratecheck-status.py --phase green "$EVIDENCE_SCRATCH/$artifact" >/dev/null 2>&1; local valid=$?; set -e; if test $valid -eq 0; then semantic=green; else semantic=red; fi; else : >"$EVIDENCE_SCRATCH/$artifact"; test $rc -ne 0 || rc=1; fi; rm -f "$raw" "$err"; printf '%s\n' "$rc" >"$EVIDENCE_SCRATCH/.${label}.rc"; printf '%s\n' "$semantic" >"$EVIDENCE_SCRATCH/.${label}.semantic"; }
write_summary(){ local result="$1"; python3 - "$EVIDENCE_SCRATCH/summary.json" "$result" "$PHASE" "$CLUSTER" "$CONTEXT" "$SOURCE_URL" "$SOURCE_REF" "$EXPECTED_COMMIT" "$OBSERVED_REVISION" "$HTTP_URL" "$HTTPS_URL" <<'PY'
import json,os,sys
path,result,phase,cluster,context,url,ref,commit,observed,http,https=sys.argv[1:]
root=path.rsplit('/',1)[0]
def section(label,artifact):
    try: rc=int(open(f"{root}/.{label}.rc",encoding="utf-8").read().strip())
    except (OSError,ValueError): rc=None
    return {"status":"captured" if rc == 0 and os.path.getsize(f"{root}/{artifact}") > 0 else ("error" if rc is not None else "unavailable"),"rc":rc,"artifact":artifact}
def endpoint(label,artifact,address):
    item=section(label,artifact); semantic_path=f"{root}/.{label}.semantic"
    try: semantic=open(semantic_path,encoding="utf-8").read().strip()
    except OSError: semantic="unavailable"
    item.update(url=address,status=semantic if semantic in {"green","red"} else ("error" if item["rc"] is not None else "unavailable")); return item
import re
revision_match=re.fullmatch(r"([^@\s]+)@sha1:([0-9a-f]{40})",observed)
revision_status="unavailable" if not observed else ("match" if revision_match and revision_match.groups()==(ref,commit) else "mismatch")
data={"schemaVersion":"kubecrate.retained-demo.evidence/v1","result":result,"phase":phase,"context":{"cluster":cluster,"kubeContext":context},"nodes":section("nodes","nodes.txt"),"revision":{"expected":commit or None,"observed":observed or None,"status":revision_status,"rc":section("revision","revision.txt")["rc"],"sourceUrl":url or None,"sourceRef":ref or None},"fluxChildren":section("flux-children","flux-children.txt"),"controllers":section("controllers","controllers.txt"),"workloads":section("workloads","workloads.txt"),"nativeConsumers":section("native-consumers","native-consumers.txt"),"crateCheck":endpoint("http","cratecheck-status.json",http),"endpoints":{"http":endpoint("http","cratecheck-status.json",http),"https":endpoint("https","cratecheck-status-https.json",https)}}
with open(path,"w",encoding="utf-8") as f: json.dump(data,f,sort_keys=True); f.write("\n")
PY
}
publish_evidence(){
  local root="$STATE_ROOT/evidence" bundles="$STATE_ROOT/evidence/bundles" bundle link
  mkdir -p "$bundles"; chmod 700 "$root" "$bundles"
  bundle="$bundles/$(date +%s)-$$-$RANDOM"
  mv "$EVIDENCE_SCRATCH" "$bundle"; EVIDENCE_SCRATCH=""
  if test -d "$EVIDENCE_DIR" && test ! -L "$EVIDENCE_DIR"; then mv "$EVIDENCE_DIR" "$bundles/legacy-$(date +%s)-$$"; fi
  link="$root/.latest.$$"; ln -s "bundles/${bundle##*/}" "$link"; mv -Tf "$link" "$EVIDENCE_DIR"
}
capture_evidence(){
  local result="${1:-inspect}" present=false
  cleanup_scratch; mkdir -p "$STATE_ROOT"; chmod 700 "$STATE_ROOT"
  EVIDENCE_SCRATCH="$(mktemp -d "$STATE_ROOT/.evidence-scratch.XXXXXX")"; chmod 700 "$EVIDENCE_SCRATCH"
  if command -v kind >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1 && validate_cluster_identity 2>/dev/null && test "$(cluster_state)" = present; then present=true; fi
  if $present && command -v kubectl >/dev/null 2>&1; then
    run_capture nodes nodes.txt kubectl --context "$CONTEXT" --request-timeout=6s get nodes -o wide
    run_capture revision revision.txt kubectl --context "$CONTEXT" --request-timeout=6s get gitrepository "$SYNC_NAME" -n "$FLUX_NAMESPACE" -o jsonpath='{.status.artifact.revision}'
    if test "$(cat "$EVIDENCE_SCRATCH/.revision.rc")" -eq 0; then OBSERVED_REVISION="$(cat "$EVIDENCE_SCRATCH/revision.txt")"; fi
    run_capture flux-children flux-children.txt kubectl --context "$CONTEXT" --request-timeout=6s get kustomizations -n "$FLUX_NAMESPACE"
    run_capture controllers controllers.txt kubectl --context "$CONTEXT" --request-timeout=6s get deployments -n "$FLUX_NAMESPACE"
    run_capture workloads workloads.txt kubectl --context "$CONTEXT" --request-timeout=6s get deployments -A
    run_capture native-consumers native-consumers.txt kubectl --context "$CONTEXT" --request-timeout=6s get externalsecret,secretstore,gatewayclass,gateway,httproute,certificate,clusterissuer,clusterpolicy -A
    run_capture events events.txt kubectl --context "$CONTEXT" --request-timeout=6s get events -A --field-selector type=Warning
  fi
  if command -v curl >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    capture_http http cratecheck-status.json "$HTTP_URL"
    if test -s "$CA_FILE"; then capture_http https cratecheck-status-https.json --cacert "$CA_FILE" --resolve cratecheck.local:10443:127.0.0.1 "$HTTPS_URL"; fi
  fi
  if command -v python3 >/dev/null 2>&1; then write_summary "$result"; else printf '{"schemaVersion":"kubecrate.retained-demo.evidence/v1","result":"unavailable","phase":"evidence"}\n' >"$EVIDENCE_SCRATCH/summary.json"; fi
  publish_evidence; printf 'local-demo: evidence=%s\n' "$EVIDENCE_DIR"
}
cleanup_exit(){ local rc=$?; trap - EXIT INT TERM ERR; test -z "$CAPTURE_PID" || kill "$CAPTURE_PID" 2>/dev/null || true; cleanup_scratch; exit "$rc"; }
on_exit(){ local rc=$?; trap - EXIT INT TERM ERR; cleanup_scratch; if test $rc -ne 0; then if ! $ERROR_REPORTED; then ERROR_REPORTED=true; printf 'local-demo: ERROR phase=%s message=command failed rc=%s\n' "$PHASE" "$rc" >&2; recovery; fi; if $FAILURE_STATE_ARMED; then write_state failed "$PHASE" 2>/dev/null || true; fi; capture_failure_once; if $FAILURE_STATE_ARMED; then printf 'local-demo: retained_failure cluster=%s evidence=%s\n' "$CLUSTER" "$EVIDENCE_DIR" >&2; fi; fi; exit "$rc"; }
check_prereqs(){ PHASE=prerequisites; validate_cluster_identity; for c in git kind kubectl kustomize helm flux docker curl python3 base64 timeout; do require "$c"; done; bounded_probe docker info >/dev/null 2>&1 || fail "Docker daemon unavailable"; test -f kind/config.yaml || fail "kind/config.yaml unavailable"; }
check_down_prereqs(){ PHASE=prerequisites; for c in kind python3; do require "$c"; done; }
render_source_args(){ if test -n "${KUBECRATE_LOCAL_ANONYMOUS_SOURCE:-}"; then printf '%s\0%s\0%s\0%s\0%s\0' --https-url "$SOURCE_URL" --branch "$SOURCE_REF" --anonymous; else printf '%s\0%s\0%s\0%s\0' --ssh-url "$(normalize_ssh_url "$SOURCE_URL")" --branch "$SOURCE_REF"; fi; }
validate_source_render(){ PHASE=source-render; local args=(); mapfile -d '' -t args < <(render_source_args); bounded_probe kustomize build "$ENTRYPOINT_ROOT" | bounded_probe python3 scripts/render-direct-flux-source.py "${args[@]}" >/dev/null || fail "exact Flux source rendering is impossible"; }
command_check(){ trap on_exit EXIT; check_prereqs; derive_source; validate_source_render; trap - EXIT; printf 'local-demo: check=pass cluster=%s context=%s source=%s ref=%s commit=%s\n' "$CLUSTER" "$CONTEXT" "$SOURCE_URL" "$SOURCE_REF" "$EXPECTED_COMMIT"; }
print_deploy_key(){ if test -z "${KUBECRATE_LOCAL_ANONYMOUS_SOURCE:-}"; then printf 'local-demo: register this deploy key with the Git provider for %s before waiting for GitOps readiness:\n' "$SOURCE_URL"; bounded_probe kubectl --context "$CONTEXT" get secret "$SYNC_NAME" -n "$FLUX_NAMESPACE" -o jsonpath='{.data.identity\.pub}' | bounded_probe base64 -d; printf '\nlocal-demo: after registration, rerun make local-up or make local-status\n'; fi; }
bootstrap(){ PHASE=flux-bootstrap; assert_context; bounded_operation "$WAIT_LONG" helm upgrade --install flux-system "$FLUX_CHART" --kube-context "$CONTEXT" --version "$FLUX_CHART_VERSION" --namespace "$FLUX_NAMESPACE" --create-namespace -f "$FLUX_HELM_VALUES" --wait --timeout "$WAIT_LONG"; for d in source-controller kustomize-controller helm-controller; do bounded_operation "$WAIT_SHORT" kubectl --context "$CONTEXT" wait --for=condition=Available "deployment/$d" -n "$FLUX_NAMESPACE" --timeout="$WAIT_SHORT"; done; assert_context; local args=(); mapfile -d '' -t args < <(render_source_args); bounded_probe kustomize build "$ENTRYPOINT_ROOT" | bounded_probe python3 scripts/render-direct-flux-source.py "${args[@]}" | bounded_operation "$WAIT_SHORT" kubectl --context "$CONTEXT" apply -f -; bounded_operation "$WAIT_SHORT" kubectl --context "$CONTEXT" wait --for=condition=Ready "helmrelease/$SYNC_NAME" -n "$FLUX_NAMESPACE" --timeout="$WAIT_SHORT"; print_deploy_key; bounded_operation "$WAIT_LONG" flux --context "$CONTEXT" reconcile source git "$SYNC_NAME" -n "$FLUX_NAMESPACE" --timeout="$WAIT_LONG"; bounded_operation "$WAIT_LONG" flux --context "$CONTEXT" reconcile kustomization "$SYNC_NAME" -n "$FLUX_NAMESPACE" --timeout="$WAIT_LONG"; }
status_checks(){
  EVIDENCE_ON_ERROR=true; PHASE=status; test "$(cluster_state)" = present || fail "recorded cluster $CLUSTER is absent"
  printf 'local-demo: intended_context=%s ambient_context=%s\n' "$CONTEXT" "$(bounded_probe kubectl config current-context 2>/dev/null || printf none)"
  bounded_probe kubectl --context "$CONTEXT" get nodes; bounded_operation "$WAIT_SHORT" kubectl --context "$CONTEXT" wait --for=condition=Ready node --all --timeout="$WAIT_SHORT"
  local revision; revision="$(bounded_probe kubectl --context "$CONTEXT" --request-timeout=10s get gitrepository "$SYNC_NAME" -n "$FLUX_NAMESPACE" -o jsonpath='{.status.artifact.revision}')"; validate_revision "$revision"; OBSERVED_REVISION="$revision"
  bounded_probe flux --context "$CONTEXT" get sources git -n "$FLUX_NAMESPACE"; bounded_probe flux --context "$CONTEXT" get kustomizations -n "$FLUX_NAMESPACE"
  local k; for k in flux-system-sync external-secrets-operator external-secrets-operator-smoke cratecheck cert-manager cert-manager-local-issuer envoy-gateway envoy-gateway-smoke kyverno kyverno-smoke-policy kyverno-smoke; do bounded_operation "$WAIT_LONG" kubectl --context "$CONTEXT" wait --for=condition=Ready "kustomization/$k" -n "$FLUX_NAMESPACE" --timeout="$WAIT_LONG"; done
  local t; for t in flux-system/source-controller flux-system/kustomize-controller flux-system/helm-controller core-external-secrets-operator/external-secrets cratecheck/cratecheck core-envoy-gateway/envoy-gateway core-cert-manager/cert-manager core-kyverno/kyverno-admission-controller; do bounded_operation "$WAIT_LONG" kubectl --context "$CONTEXT" wait --for=condition=Available "deployment/${t#*/}" -n "${t%/*}" --timeout="$WAIT_LONG"; done
  bounded_operation "$WAIT_LONG" kubectl --context "$CONTEXT" wait --for=condition=Programmed gateway/kubecrate-envoy-smoke -n core-envoy-gateway --timeout="$WAIT_LONG"
  bounded_operation "$WAIT_LONG" kubectl --context "$CONTEXT" wait --for=condition=Ready certificate/cratecheck-tls -n cratecheck --timeout="$WAIT_LONG"
  bounded_operation "$WAIT_LONG" kubectl --context "$CONTEXT" wait --for=condition=Ready clusterpolicy/require-ns-label --timeout="$WAIT_LONG"
  bounded_probe kubectl --context "$CONTEXT" get secret eso-smoke-projected -n kubecrate-system -o name >/dev/null; bounded_probe kubectl --context "$CONTEXT" get namespace kyverno-smoke-allowed -o name >/dev/null
  mkdir -p "$STATE_ROOT"; bounded_probe kubectl --context "$CONTEXT" get secret cratecheck-tls -n cratecheck -o jsonpath='{.data.ca\.crt}' | bounded_probe base64 -d >"$CA_FILE"; test -s "$CA_FILE" || fail "trusted local CA is empty"
  bounded_probe curl --fail --silent --show-error "$HTTP_URL" >"$STATE_ROOT/status.json"; python3 scripts/validate-cratecheck-status.py --phase green "$STATE_ROOT/status.json" || fail "CrateCheck JSON is not exact green"
  bounded_probe curl --fail --silent --show-error --cacert "$CA_FILE" --resolve cratecheck.local:10443:127.0.0.1 "$HTTPS_URL" >"$STATE_ROOT/status-https.json"; python3 scripts/validate-cratecheck-status.py --phase green "$STATE_ROOT/status-https.json" || fail "trusted HTTPS JSON is not exact green"
  bounded_probe kubectl --context "$CONTEXT" get helmreleases -A; bounded_probe kubectl --context "$CONTEXT" get externalsecret,secretstore -A; bounded_probe kubectl --context "$CONTEXT" get gatewayclass,gateway,httproute -A; bounded_probe kubectl --context "$CONTEXT" get certificate,clusterissuer -A; bounded_probe kubectl --context "$CONTEXT" get clusterpolicy
  printf 'local-demo: status=green cluster=%s context=%s revision=%s\nlocal-demo: http=%s https=%s ca=%s\n' "$CLUSTER" "$CONTEXT" "$revision" "$HTTP_URL" "$HTTPS_URL" "$CA_FILE"; cat "$STATE_ROOT/status.json"; printf '\n'
}
command_up(){ trap on_exit EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; check_prereqs; derive_source; validate_source_render; local st; st="$(cluster_state)"; test "$st" != unknown || fail "kind cluster inventory unavailable"; if test "$st" = present; then test -s "$STATE_FILE" || fail "cluster exists without retained-demo ownership state"; local url="$SOURCE_URL" ref="$SOURCE_REF" commit="$EXPECTED_COMMIT"; load_state; test "$SOURCE_URL" = "$url" && test "$SOURCE_REF" = "$ref" && test "$EXPECTED_COMMIT" = "$commit" || fail "existing cluster belongs to another source; use make local-recreate"; FAILURE_STATE_ARMED=true; EVIDENCE_ON_ERROR=true; else write_state creating cluster-create; FAILURE_STATE_ARMED=true; EVIDENCE_ON_ERROR=true; PHASE=cluster-create; bounded_operation "$WAIT_LONG" kind create cluster --name "$CLUSTER" --config kind/config.yaml; fi; assert_context; bounded_operation "$WAIT_SHORT" kubectl --context "$CONTEXT" --request-timeout=10s wait --for=condition=Ready node --all --timeout="$WAIT_SHORT"; write_state converging flux-bootstrap; bootstrap; status_checks; write_state running ready; PHASE=ready; capture_evidence pass; FAILURE_STATE_ARMED=false; EVIDENCE_ON_ERROR=false; trap - EXIT INT TERM ERR; echo 'local-demo: up=pass retained=true down="make local-down"'; }
command_status(){ trap on_exit EXIT; check_prereqs; load_state; status_checks; capture_evidence pass; }
command_evidence(){ trap cleanup_exit EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; validate_cluster_identity; if test -s "$STATE_FILE" && command -v python3 >/dev/null 2>&1; then load_state; PHASE="$(state_value phase)"; else PHASE=evidence; fi; capture_evidence inspect; }
command_restart(){ trap on_exit EXIT; check_prereqs; load_state; PHASE=restart; test "$(cluster_state)" = present || fail "recorded cluster absent"; assert_context; mapfile -t nodes < <(bounded_probe kind get nodes --name "$CLUSTER"); test ${#nodes[@]} -gt 0 || fail "recorded cluster has no nodes"; bounded_probe docker restart "${nodes[@]}" >/dev/null; bounded_operation "$WAIT_LONG" kubectl --context "$CONTEXT" --request-timeout=10s wait --for=condition=Ready node --all --timeout="$WAIT_LONG"; status_checks; }
command_down(){ trap on_exit EXIT; validate_cluster_identity; check_down_prereqs; load_state; PHASE=down; local st; st="$(cluster_state)"; test "$st" != unknown || fail "kind cluster inventory unavailable"; test "$st" != present || bounded_probe kind delete cluster --name "$CLUSTER"; test "$(cluster_state)" = absent || fail "cluster absence proof failed"; rm -f "$STATE_FILE" "$CA_FILE" "$STATE_ROOT/status.json" "$STATE_ROOT/status-https.json"; printf 'local-demo: down=pass cluster=%s absence=proven evidence_retained=%s\n' "$CLUSTER" "$EVIDENCE_DIR"; }
usage(){ echo 'usage: scripts/local-demo.sh check|up|status|evidence|restart|recreate|down'; }
case "$COMMAND" in check) command_check;; up) command_up;; status) command_status;; evidence) command_evidence;; restart) command_restart;; recreate) command_down; command_up;; down) command_down;; help|-h|--help) usage;; *) usage >&2; exit 2;; esac
