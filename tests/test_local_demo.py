#!/usr/bin/env python3
"""Behavioral tests for the retained local-demo shipped entrypoint."""
import json, os, shutil, subprocess, time
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parent.parent
RUNNER=ROOT/"scripts/local-demo.sh"

def init_checkout(path:Path)->str:
    for d in ("scripts","kind","clusters/kind-dev-misc-local/entrypoint","clusters/kind-dev-misc-local/platform-services/flux"):(path/d).mkdir(parents=True,exist_ok=True)
    for f in ("local-demo.sh","render-direct-flux-source.py","validate-cratecheck-status.py"): shutil.copy2(ROOT/"scripts"/f,path/"scripts"/f)
    shutil.copy2(ROOT/"kind/config.yaml",path/"kind/config.yaml")
    (path/"clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    subprocess.run(["git","init","-q","-b","demo",path],check=True)
    subprocess.run(["git","-C",path,"config","user.email","demo@test"],check=True); subprocess.run(["git","-C",path,"config","user.name","Demo"],check=True)
    subprocess.run(["git","-C",path,"remote","add","origin","git@github.com:public-user/kubecrate.git"],check=True)
    subprocess.run(["git","-C",path,"add","."],check=True); subprocess.run(["git","-C",path,"commit","-qm","demo"],check=True)
    return subprocess.check_output(["git","-C",path,"rev-parse","HEAD"],text=True).strip()

def install_dispatch(tmp:Path,commit:str,remote_rc:int=0,remote_commit:str|None=None,create_rc:int=0):
    bindir=tmp/"bin"; bindir.mkdir(); log=tmp/"calls.log"; cluster=tmp/"cluster"; dispatch=bindir/"dispatch"
    dispatch.write_text(f'''#!/usr/bin/env bash
name=$(basename "$0"); printf '%s %s\\n' "$name" "$*" >>"$CALL_LOG"
+case "$name" in
+git) if [[ "$*" == *"ls-remote"* ]]; then test {remote_rc} -eq 0 || {{ printf '%s\\n' "${{FAKE_SECRET_SENTINEL:-}}" >&2; exit {remote_rc}; }}; printf '%s\\trefs/heads/demo\\n' '{remote_commit or commit}'; exit 0; fi; exec /usr/bin/git "$@";;
+docker) exit 0;;
+kustomize) cat <<'YAML'
+apiVersion: v1
+kind: ConfigMap
+metadata: {{name: flux-sync-values, namespace: flux-system}}
+data:
+  values.yaml: |
+    secret:
+      create: true
+      generate: {{sshKeyAlgorithm: ed25519}}
+    gitRepository:
+      spec:
+        url: ssh://git@github.com/public-user/kubecrate.git
+        ref: {{branch: demo}}
+YAML
+;;
+python3) exec {shutil.which('python3')} "$@";;
+kind) if [[ "$*" == "get clusters" ]]; then test ! -f "$CLUSTER_STATE" || cat "$CLUSTER_NAME"; exit 0; fi; if [[ "$*" == *"create cluster"* ]]; then prev=""; for arg; do test "$prev" != --name || printf '%s\\n' "$arg" >"$CLUSTER_NAME"; prev="$arg"; done; touch "$CLUSTER_STATE"; exit {create_rc}; fi; if [[ "$*" == *"delete cluster"* ]]; then rm -f "$CLUSTER_STATE"; exit 0; fi;;
kubectl) [[ -n "${{FAKE_CAPTURE_SECRET:-}}" ]] && printf 'Authorization: Bearer %s\n' "$FAKE_CAPTURE_SECRET"; [[ -n "${{FAKE_CAPTURE_SECRET:-}}" ]] && printf 'token=%s\n' "$FAKE_CAPTURE_SECRET" >&2; [[ -n "${{FAKE_HANG_MATCH:-}}" && "$*" == *"$FAKE_HANG_MATCH"* ]] && sleep 30; if [[ "$*" == "config current-context" ]]; then printf 'kind-%s' "$(cat "$CLUSTER_NAME")"; elif [[ "$*" == *"get gitrepository"* ]]; then printf '%s' "${{FAKE_REVISION-demo@sha1:{commit}}}"; elif [[ "$*" == *"get secret cratecheck-tls"* ]]; then printf 'ZmFrZS1jYQ=='; fi; exit "${{FAKE_KUBECTL_RC:-0}}";;
helm) [[ "${{FAKE_HANG_MATCH:-}}" == helm ]] && sleep 30; [[ "${{FAKE_DELAY_MATCH:-}}" == helm ]] && sleep "${{FAKE_DELAY_SECONDS:-2}}"; exit "${{FAKE_HELM_RC:-31}}";;
curl) [[ -n "${{FAKE_CAPTURE_SECRET:-}}" ]] && printf 'Authorization: Bearer %s\n' "$FAKE_CAPTURE_SECRET"; [[ -n "${{FAKE_CAPTURE_SECRET:-}}" ]] && printf 'password=%s\n' "$FAKE_CAPTURE_SECRET" >&2; [[ "${{FAKE_HANG_MATCH:-}}" == curl ]] && sleep 30; if [[ -v FAKE_STATUS_JSON ]]; then printf '%s' "$FAKE_STATUS_JSON"; else printf '{{}}'; fi; exit "${{FAKE_CURL_RC:-0}}";;
base64) if [[ "$*" == *"-d"* ]]; then printf 'fake-ca'; fi; exit 0;;
flux) [[ -n "${{FAKE_CAPTURE_SECRET:-}}" ]] && printf 'Authorization: Bearer %s\n' "$FAKE_CAPTURE_SECRET"; [[ -n "${{FAKE_CAPTURE_SECRET:-}}" ]] && printf 'credential=%s\n' "$FAKE_CAPTURE_SECRET" >&2; [[ "${{FAKE_HANG_MATCH:-}}" == flux ]] && sleep 30; exit "${{FAKE_FLUX_RC:-0}}";;
+esac
+exit 0
+'''.replace('\n+','\n'))
    dispatch.chmod(0o755)
    for name in ("git","docker","kustomize","python3","kind","kubectl","helm","flux","curl","base64"):(bindir/name).symlink_to(dispatch)
    return bindir,log,cluster

def run(repo,bindir,log,cluster,command,state,**extra):
    env={**os.environ,"PATH":f"{bindir}:{os.environ['PATH']}","CALL_LOG":str(log),"CLUSTER_STATE":str(cluster),"CLUSTER_NAME":str(cluster.parent/"cluster-name"),"KUBECRATE_LOCAL_STATE_DIR":str(state),"KUBECRATE_LOCAL_EVIDENCE_TIMEOUT":"1s","KUBECRATE_LOCAL_PROBE_TIMEOUT":"1s",**extra}
    return subprocess.run([str(repo/"scripts/local-demo.sh"),command],cwd=repo,env=env,text=True,capture_output=True,timeout=20)

def call_log(log):
    return log.read_text() if log.exists() else ""

def test_check_derives_public_fork_url_and_exact_ref(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit)
    result=run(repo,bindir,log,cluster,"check",tmp_path/"state")
    assert result.returncode==0,result.stderr
    assert "source=https://github.com/public-user/kubecrate.git" in result.stdout and "ref=demo" in result.stdout and f"commit={commit}" in result.stdout
    assert "kind create cluster" not in log.read_text()

@pytest.mark.parametrize(("case","error"),[("dirty","checkout is dirty"),("inaccessible","not anonymously accessible"),("mismatch","does not advertise checkout commit")])
def test_source_failures_precede_cluster_creation(tmp_path,case,error):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo)
    if case=="dirty":(repo/"kind/config.yaml").write_text("dirty\n")
    bindir,log,cluster=install_dispatch(tmp_path,commit,remote_rc=4 if case=="inaccessible" else 0,remote_commit="b"*40 if case=="mismatch" else None)
    result=run(repo,bindir,log,cluster,"up",tmp_path/"state")
    assert result.returncode!=0 and error in result.stderr
    assert "kind create cluster" not in log.read_text()

def test_failed_up_retains_cluster_state_and_evidence(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); state=tmp_path/"state"
    result=run(repo,bindir,log,cluster,"up",state)
    assert result.returncode==31 and cluster.exists()
    assert result.stderr.count("local-demo: ERROR phase=flux-bootstrap") == 1
    assert result.stderr.count("local-demo: recovery=") == 1
    saved=json.loads((state/"state.json").read_text()); assert saved["lifecycle"]=="failed" and saved["phase"]=="flux-bootstrap"
    evidence="".join(p.read_text() for p in (state/"evidence/latest").iterdir()); assert "token=" not in evidence.lower() and "password=" not in evidence.lower()
    summary=json.loads((state/"evidence/latest/summary.json").read_text()); assert summary["result"]=="failed" and summary["phase"]=="flux-bootstrap"
    assert "kind delete cluster" not in log.read_text()

def test_matching_repeated_up_reuses_recorded_cluster(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    result=run(repo,bindir,log,cluster,"up",state)
    assert result.returncode==31
    assert "kind create cluster" not in log.read_text()
    assert "helm upgrade --install flux-system" in log.read_text()

def test_status_executes_shipped_schema_gate_and_fails_red(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    result=run(repo,bindir,log,cluster,"status",state,FAKE_STATUS_JSON='{"status":"red","checks":[],"summary":{}}')
    assert result.returncode!=0
    assert "CrateCheck JSON is not exact green" in result.stderr
    assert "validate-cratecheck-status.py --phase green" in log.read_text()
    summary=json.loads((state/"evidence/latest/summary.json").read_text()); assert summary["schemaVersion"]=="kubecrate.retained-demo.evidence/v1" and summary["result"]=="failed"

def write_state(state,cluster,commit):
    state.mkdir(); (state/"state.json").write_text(json.dumps({"owner":"kubecrate-retained-local-demo","cluster":cluster,"context":f"kind-{cluster}","sourceUrl":"https://github.com/public-user/kubecrate.git","sourceRef":"demo","expectedCommit":commit,"phase":"failed"}))

def test_down_refuses_protected_state_without_delete(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kind-dev-misc-local\n"); state=tmp_path/"state"; write_state(state,"kind-dev-misc-local",commit)
    result=run(repo,bindir,log,cluster,"down",state)
    assert result.returncode!=0 and "refusing protected cluster" in result.stderr and "kind delete cluster" not in log.read_text()

def test_down_deletes_recorded_cluster_and_proves_absence(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    result=run(repo,bindir,log,cluster,"down",state); calls=log.read_text()
    assert result.returncode==0,result.stderr
    assert calls.count("kind get clusters")>=2 and "kind delete cluster --name kubecrate-local" in calls
    assert not cluster.exists() and not (state/"state.json").exists()

@pytest.mark.parametrize("case", ["dirty", "inaccessible"])
def test_existing_state_is_byte_preserved_on_preflight_failure(tmp_path,case):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit,remote_rc=9 if case=="inaccessible" else 0)
    cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n")
    state=tmp_path/"state"; write_state(state,"kubecrate-local",commit); before=(state/"state.json").read_bytes()
    if case=="dirty": (repo/"kind/config.yaml").write_text("dirty\n")
    result=run(repo,bindir,log,cluster,"up",state)
    assert result.returncode != 0
    assert (state/"state.json").read_bytes() == before
    assert not (state/"evidence/latest").exists()
    assert all(word not in call_log(log) for word in ("kind create cluster","helm ","kubectl ","flux ","docker restart","kind delete"))

@pytest.mark.parametrize("name", ["kind-dev-misc-local", "kubecrate-qa-owned", "demo", "kubecrate-local..bad", "kubecrate-local-"])
@pytest.mark.parametrize("command", ["up", "restart", "recreate", "down"])
def test_lifecycle_refuses_non_demo_cluster_identity_before_mutation(tmp_path,name,command):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit)
    state=tmp_path/"state"
    if command != "up": write_state(state,name,commit)
    result=run(repo,bindir,log,cluster,command,state,KUBECRATE_LOCAL_CLUSTER=name)
    assert result.returncode != 0
    calls=call_log(log)
    assert all(word not in calls for word in ("kind get clusters","kind create","kind delete","helm ","kubectl ","flux ","docker "))

def test_private_mode_check_passes_and_uses_basic_auth_probe(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit)
    result=run(repo,bindir,log,cluster,"check",tmp_path/"state",KUBECRATE_LOCAL_GIT_BASIC_AUTH="1",KUBECRATE_LOCAL_GIT_USERNAME="u",KUBECRATE_LOCAL_GIT_PASSWORD="p")
    assert result.returncode==0,result.stderr
    assert "source=https://github.com/public-user/kubecrate.git" in result.stdout and f"commit={commit}" in result.stdout
    assert "credential.helper=!f()" in next(line for line in call_log(log).splitlines() if "ls-remote" in line)
    assert "credential.helper= -c" not in call_log(log)

def test_private_mode_missing_credentials_fails_before_mutation(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo)
    bindir,log,cluster=install_dispatch(tmp_path,commit)
    dispatch=bindir/"dispatch"; dispatch.write_text(dispatch.read_text().replace('git) if [[ "$*" == *"ls-remote"* ]]; then','git) if [[ "$*" == *"credential fill"* ]]; then exit 1; fi; if [[ "$*" == *"ls-remote"* ]]; then'))
    empty_home=tmp_path/"empty-home"; empty_home.mkdir()
    result=run(repo,bindir,log,cluster,"up",tmp_path/"state",KUBECRATE_LOCAL_GIT_BASIC_AUTH="1",HOME=str(empty_home))
    assert result.returncode!=0
    assert "phase=source-identity" in result.stderr
    assert "private source requires basic-auth credentials" in result.stderr
    assert "kind create cluster" not in call_log(log)

def test_private_mode_exactness_mismatch_fails(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo)
    bindir,log,cluster=install_dispatch(tmp_path,commit,remote_commit="b"*40)
    result=run(repo,bindir,log,cluster,"up",tmp_path/"state",KUBECRATE_LOCAL_GIT_BASIC_AUTH="1",KUBECRATE_LOCAL_GIT_USERNAME="u",KUBECRATE_LOCAL_GIT_PASSWORD="p")
    assert result.returncode!=0
    assert "does not advertise checkout commit" in result.stderr
    assert "kind create cluster" not in call_log(log)

def test_private_mode_up_creates_secret_and_renders_secretref(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); state=tmp_path/"state"
    result=run(repo,bindir,log,cluster,"up",state,FAKE_HELM_RC="0",KUBECRATE_LOCAL_GIT_BASIC_AUTH="1",KUBECRATE_LOCAL_GIT_USERNAME="git-user",KUBECRATE_LOCAL_GIT_PASSWORD="git-pass")
    assert result.returncode!=0
    calls=call_log(log)
    assert "kubectl --context kind-kubecrate-local -n flux-system create secret generic flux-system-sync --from-literal=username=git-user --from-literal=password=git-pass --dry-run=client -o yaml" in calls
    assert "kubectl --context kind-kubecrate-local apply -f -" in calls
    render=next(line for line in calls.splitlines() if "render-direct-flux-source.py" in line and "helm-values" not in line)
    assert "--anonymous" not in render
    assert "kind delete cluster" not in calls
    evidence="".join(p.read_text() for p in (state/"evidence/latest").iterdir())
    assert "git-pass" not in evidence

def test_anonymous_remote_probe_ignores_all_git_config_and_credentials(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit)
    hostile=tmp_path/"hostile"; hostile.mkdir(); marker=tmp_path/"credential-used"
    (hostile/".gitconfig").write_text('[url "https://attacker.invalid/"]\n insteadOf = https://github.com/\n[credential]\n helper = !touch '+str(marker)+'\n')
    (hostile/".netrc").write_text("machine github.com login attacker password stolen\n")
    result=run(repo,bindir,log,cluster,"check",tmp_path/"state",HOME=str(hostile),GIT_CONFIG_GLOBAL=str(hostile/".gitconfig"),GIT_CONFIG_COUNT="1",GIT_CONFIG_KEY_0="url.https://attacker.invalid/.insteadOf",GIT_CONFIG_VALUE_0="https://github.com/",GIT_ASKPASS=str(hostile/"askpass"))
    assert result.returncode == 0,result.stderr
    assert "https://github.com/public-user/kubecrate.git" in next(line for line in call_log(log).splitlines() if "ls-remote" in line)
    assert not marker.exists()

def test_missing_tools_still_create_parseable_bounded_evidence(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); init_checkout(repo); state=tmp_path/"state"
    env={**os.environ,"PATH":"/usr/bin:/bin","KUBECRATE_LOCAL_STATE_DIR":str(state),"KUBECRATE_LOCAL_EVIDENCE_TIMEOUT":"1s"}
    result=subprocess.run([str(repo/"scripts/local-demo.sh"),"evidence"],cwd=repo,env=env,text=True,capture_output=True,timeout=5)
    assert result.returncode == 0,result.stderr
    summary=json.loads((state/"evidence/latest/summary.json").read_text())
    assert summary["schemaVersion"] == "kubecrate.retained-demo.evidence/v1"
    for key in ("context","nodes","revision","fluxChildren","controllers","workloads","nativeConsumers","crateCheck","endpoints"): assert key in summary

def test_external_probe_has_total_timeout_and_exact_failure_phase(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit)
    dispatch=bindir/"dispatch"; dispatch.write_text(dispatch.read_text().replace('git) if [[ "$*" == *"ls-remote"* ]]; then', 'git) if [[ "$*" == *"ls-remote"* ]]; then sleep 30;'))
    started=time.monotonic(); result=run(repo,bindir,log,cluster,"check",tmp_path/"state",KUBECRATE_LOCAL_PROBE_TIMEOUT="1s"); elapsed=time.monotonic()-started
    assert elapsed < 5 and result.returncode == 124
    assert "phase=source-identity" in result.stderr and "recovery=" in result.stderr

@pytest.mark.parametrize(("sentinel","secret"), [
    ("token=tokenvalue987 password:passwordvalue987 credential=https://urluser987:urlpass987@example.test/x", "tokenvalue987"),
    ("Authorization: Basic basicvalue987", "basicvalue987"),
    ("Authorization: Bearer authbearervalue987", "authbearervalue987"),
    ("Bearer standalonevalue987", "standalonevalue987"),
])
def test_every_error_stream_is_sanitized(tmp_path,sentinel,secret):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit,remote_rc=7)
    result=run(repo,bindir,log,cluster,"check",tmp_path/"state",FAKE_SECRET_SENTINEL=sentinel)
    assert result.returncode == 7
    assert "[redacted]" in result.stderr
    assert secret not in result.stderr
    assert "local-demo: ERROR phase=source-identity" in result.stderr
    assert "local-demo: recovery=" in result.stderr
    assert "message=selected source is not anonymously accessible" in result.stderr

@pytest.mark.parametrize(("create_rc","helm_rc","phase","expected_rc"), [
    (23,31,"cluster-create",23),
    (0,31,"flux-bootstrap",31),
])
def test_owned_raw_failures_preserve_rc_phase_recovery_and_single_evidence(tmp_path,create_rc,helm_rc,phase,expected_rc):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit,create_rc=create_rc); state=tmp_path/"state"
    result=run(repo,bindir,log,cluster,"up",state,FAKE_HELM_RC=str(helm_rc))
    assert result.returncode == expected_rc
    assert result.stderr.count(f"local-demo: ERROR phase={phase}") == 1
    assert result.stderr.count("local-demo: recovery=") == 1
    assert call_log(log).count("curl --fail") == 1
    assert (state/"evidence/latest/summary.json").exists()

@pytest.mark.parametrize(("command","hang_match","phase"), [
    ("status","get nodes","status"),
    ("status","flux","status"),
    ("status","curl","status"),
])
def test_status_external_hangs_are_totally_bounded(tmp_path,command,hang_match,phase):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    started=time.monotonic(); result=run(repo,bindir,log,cluster,command,state,FAKE_HANG_MATCH=hang_match); elapsed=time.monotonic()-started
    assert elapsed < 8 and result.returncode != 0
    assert result.stderr.count(f"local-demo: ERROR phase={phase}") == 1
    assert result.stderr.count("local-demo: recovery=") == 1

@pytest.mark.parametrize(("curl_rc","payload","expected"), [
    (22,"",("error",22)),
    (0,"",("error",1)),
    (0,'{"status":"red","checks":[],"summary":{}}',("red",0)),
])
def test_evidence_http_summary_uses_rc_and_semantics(tmp_path,curl_rc,payload,expected):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    result=run(repo,bindir,log,cluster,"evidence",state,FAKE_CURL_RC=str(curl_rc),FAKE_STATUS_JSON=payload)
    assert result.returncode == 0,result.stderr
    summary=json.loads((state/"evidence/latest/summary.json").read_text())
    assert (summary["endpoints"]["http"]["status"],summary["endpoints"]["http"]["rc"]) == expected
    assert summary["revision"]["status"] == "match" and summary["revision"]["observed"] == f"demo@sha1:{commit}"

def test_evidence_revision_mismatch_is_explicit(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    result=run(repo,bindir,log,cluster,"evidence",state,FAKE_REVISION=f"demo@sha1:{'b'*40}")
    summary=json.loads((state/"evidence/latest/summary.json").read_text())
    assert result.returncode == 0 and summary["revision"]["status"] == "mismatch"
    assert summary["revision"]["expected"] == commit and summary["revision"]["observed"] == f"demo@sha1:{'b'*40}"

@pytest.mark.parametrize(("observed","status"), [
    ("wrong-ref@sha1:{commit}", "mismatch"),
    ("malformed", "mismatch"),
    ("", "unavailable"),
])
def test_evidence_revision_compares_full_ref_and_commit(tmp_path,observed,status):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    value=observed.format(commit=commit)
    result=run(repo,bindir,log,cluster,"evidence",state,FAKE_REVISION=value)
    summary=json.loads((state/"evidence/latest/summary.json").read_text())
    assert result.returncode == 0
    assert summary["revision"]["observed"] == (value or None)
    assert summary["revision"]["status"] == status

def test_long_operation_uses_wait_bound_not_probe_bound(tmp_path):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); state=tmp_path/"state"
    result=run(repo,bindir,log,cluster,"up",state,FAKE_DELAY_MATCH="helm",FAKE_DELAY_SECONDS="2",FAKE_HELM_RC="31",KUBECRATE_LOCAL_PROBE_TIMEOUT="1s",KUBECRATE_LOCAL_WAIT_LONG="5s")
    assert result.returncode == 31
    assert "phase=flux-bootstrap" in result.stderr and "rc=31" in result.stderr

@pytest.mark.parametrize("hang_match", ["get nodes", "get kustomizations", "curl"])
def test_interrupted_evidence_never_publishes_raw_secret(tmp_path,hang_match):
    repo=tmp_path/"repo"; repo.mkdir(); commit=init_checkout(repo); bindir,log,cluster=install_dispatch(tmp_path,commit); cluster.touch(); (tmp_path/"cluster-name").write_text("kubecrate-local\n"); state=tmp_path/"state"; write_state(state,"kubecrate-local",commit)
    sentinel="interruptionsecret987"
    env={**os.environ,"PATH":f"{bindir}:{os.environ['PATH']}","CALL_LOG":str(log),"CLUSTER_STATE":str(cluster),"CLUSTER_NAME":str(tmp_path/"cluster-name"),"KUBECRATE_LOCAL_STATE_DIR":str(state),"KUBECRATE_LOCAL_EVIDENCE_TIMEOUT":"20s","FAKE_CAPTURE_SECRET":sentinel,"FAKE_HANG_MATCH":hang_match}
    proc=subprocess.Popen([str(repo/"scripts/local-demo.sh"),"evidence"],cwd=repo,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    deadline=time.monotonic()+5
    while hang_match not in call_log(log) and time.monotonic()<deadline: time.sleep(.05)
    os.killpg(proc.pid,15); proc.communicate(timeout=5)
    evidence=state/"evidence"
    retained="".join(p.read_text(errors="ignore") for p in evidence.rglob("*") if p.is_file()) if evidence.exists() else ""
    assert sentinel not in retained
    assert not list(state.glob(".evidence-scratch.*"))

def test_runner_and_make_entrypoints_are_shipped():
    assert RUNNER.stat().st_mode&0o111 and subprocess.run(["bash","-n",RUNNER]).returncode==0
    makefile=(ROOT/"Makefile").read_text()
    for command in ("check","up","status","evidence","restart","recreate","down"): assert f"local-{command}:" in makefile
    status_body=RUNNER.read_text().split("status_checks(){",1)[1].split("command_up(){",1)[0]
    assert "assert_context" not in status_body
    for mutation in (" apply "," delete "," patch "," reconcile "," suspend "," resume "):
        assert mutation not in status_body
