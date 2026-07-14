#!/usr/bin/env python3
"""Behavioral tests for exact-tree final-QA safety helpers."""

import importlib.util
import json
import os
import subprocess
import shutil
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER_PATH = ROOT / "scripts" / "final_qa_helpers.py"
SCRIPT = ROOT / "scripts" / "final-qa-exact-tree.sh"
WAIT_PORT_FORWARD = ROOT / "scripts" / "wait-port-forward.sh"

spec = importlib.util.spec_from_file_location("final_qa_helpers", HELPER_PATH)
helpers = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(helpers)

IDS = list(helpers.EXPECTED_IDS)
NAMES = helpers.EXPECTED_NAMES


def check(check_id: str, status: str = "green") -> dict:
    return {"id": check_id, "name": NAMES[check_id], "status": status}


def payload(statuses: dict[str, str] | None = None) -> dict:
    statuses = statuses or {}
    checks = [check(i, statuses.get(i, "green")) for i in IDS]
    counts = {s: sum(c["status"] == s for c in checks) for s in ("green", "red", "yellow", "unknown")}
    overall = "green" if counts["green"] == 7 else "red"
    return {"status": overall, "summary": {"total": 7, **counts}, "checks": checks}


def html(statuses: dict[str, str] | None = None, stray: str = "") -> str:
    statuses = statuses or {}
    cards = "".join(
        f'<article class="check" data-status="{statuses.get(i, "green")}">'
        f'<div class="check-title"><span class="badge {statuses.get(i, "green")}">{statuses.get(i, "green")}</span>'
        f'<h3>{NAMES[i]}</h3></div></article>' for i in IDS
    )
    return f'<html><body>{stray}<div class="check-list" id="checks">{cards}</div></body></html>'


def test_json_exact_baseline_red_and_restore_contract() -> None:
    helpers.validate_status(payload(), "green")
    helpers.validate_status(payload({"eso-externalsecret-ready": "red"}), "red")


@pytest.mark.parametrize("bad", [
    [check(IDS[0])] * 2 + [check(i) for i in IDS[2:]],
    [check(i) for i in IDS[:-1]],
    [{"id": f"other-{n}", "name": f"Other {n}", "status": "green"} for n in range(7)],
])
def test_json_rejects_duplicate_missing_or_substituted_ids(bad: list[dict]) -> None:
    data = payload()
    data["checks"] = bad
    with pytest.raises(AssertionError):
        helpers.validate_status(data, "green")


def test_red_rejects_unrelated_eso_red_and_unrelated_check_change() -> None:
    with pytest.raises(AssertionError):
        helpers.validate_status(payload({"eso-secretstore-ready": "red"}), "red")
    with pytest.raises(AssertionError):
        helpers.validate_status(payload({"cratecheck-configmap-present": "red"}), "red")


def test_html_requires_structured_exact_cards_not_stray_score_text() -> None:
    helpers.validate_html(html(), "green")
    helpers.validate_html(html({"eso-projected-secret-exists": "red"}), "red")
    with pytest.raises(AssertionError):
        helpers.validate_html('<html><body><p>7/7</p></body></html>', "green")
    with pytest.raises(AssertionError):
        helpers.validate_html(html().replace(NAMES[IDS[-1]], "substituted"), "green")


class FakeRefs:
    def __init__(self, lookup, create=None, delete=None, after_delete=None):
        self.lookup = list(lookup)
        self.create_result = create
        self.delete_result = delete
        self.after_delete = after_delete
        self.calls = []

    def get(self, ref):
        self.calls.append(("get", ref))
        value = self.lookup.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def create(self, ref, sha):
        self.calls.append(("create", ref, sha))
        if isinstance(self.create_result, Exception):
            raise self.create_result
        return self.create_result

    def delete(self, ref):
        self.calls.append(("delete", ref))
        if isinstance(self.delete_result, Exception):
            raise self.delete_result
        return self.delete_result


def test_ref_race_422_never_establishes_ownership() -> None:
    api = FakeRefs([None], create=helpers.APIError(422, "exists"))
    with pytest.raises(helpers.APIError):
        helpers.create_owned_ref(api, "refs/heads/qa", "a" * 40)
    assert not any(c[0] == "delete" for c in api.calls)


def test_unknown_lookup_fails_closed_before_create() -> None:
    api = FakeRefs([helpers.APIError(500, "unknown")])
    with pytest.raises(helpers.APIError):
        helpers.create_owned_ref(api, "refs/heads/qa", "a" * 40)
    assert not any(c[0] == "create" for c in api.calls)


def test_owned_create_delete_and_absence() -> None:
    sha = "a" * 40
    obj = {"ref": "refs/heads/qa", "object": {"type": "commit", "sha": sha}}
    api = FakeRefs([None, obj, obj, None], create=obj, delete=None)
    helpers.create_owned_ref(api, "refs/heads/qa", sha)
    helpers.delete_owned_ref(api, "refs/heads/qa", sha)
    assert ("delete", "refs/heads/qa") in api.calls


def test_changed_ref_cleanup_refuses_delete() -> None:
    sha = "a" * 40
    changed = {"ref": "refs/heads/qa", "object": {"type": "commit", "sha": "b" * 40}}
    api = FakeRefs([changed])
    with pytest.raises(AssertionError):
        helpers.delete_owned_ref(api, "refs/heads/qa", sha)
    assert not any(c[0] == "delete" for c in api.calls)


def test_restoration_uses_explicit_context_and_checks_before_teardown() -> None:
    calls = []
    context = "kind-qa"

    def run(command, **_kwargs):
        calls.append(command)
        output = context + "\n" if len(calls) == 1 else ""
        return SimpleNamespace(returncode=0, stdout=output)

    helpers.restore_cluster(context, run=run)
    assert all("--context" in command and context in command for command in calls)
    joined = [" ".join(c) for c in calls]
    assert next(i for i, c in enumerate(joined) if "get secret eso-smoke-source" in c) < next(
        i for i, c in enumerate(joined) if "externalsecret/eso-smoke-projection" in c
    )


def test_restoration_failure_is_nonzero_and_stops_verification() -> None:
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        rc = 1 if "resume" in command else 0
        return SimpleNamespace(returncode=rc, stdout="kind-qa\n")

    with pytest.raises(RuntimeError):
        helpers.restore_cluster("kind-qa", run=run)
    assert len(calls) == 2


@pytest.mark.parametrize("state", ["suspended", "source_deleted"])
def test_failure_after_each_red_mutation_requires_restoration(state: str) -> None:
    assert helpers.restoration_required(state)


def test_mutation_state_is_set_immediately_after_suspend_and_delete() -> None:
    text = SCRIPT.read_text()
    suspend = text.index('flux --context "${CONTEXT}" suspend')
    delete = text.index('kubectl --context "${CONTEXT}" delete secret')
    intent = text.index("RED_STATE=restore_required")
    assert intent < suspend < delete
    cleanup = text[text.index("cleanup()") : text.index("trap cleanup EXIT")]
    assert cleanup.index("restore_if_needed") < cleanup.index("kind delete cluster")


def fake_gh(tmp_path: Path, responses: list[tuple[int, str]], log: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    queue = tmp_path / "responses.json"
    queue.write_text(json.dumps(responses))
    gh = bindir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys,pathlib\n"
        "q=pathlib.Path(os.environ['FAKE_GH_QUEUE']); data=json.loads(q.read_text()); status,body=data.pop(0); q.write_text(json.dumps(data))\n"
        "pathlib.Path(os.environ['FAKE_GH_LOG']).open('a').write(' '.join(sys.argv[1:])+'\\n')\n"
        "print(f'HTTP/2 {status} status\\ncontent-type: application/json\\n\\n{body}')\n"
        "raise SystemExit(0 if status < 400 else 1)\n"
    )
    gh.chmod(0o755)
    return bindir


def ref_obj(ref: str, sha: str) -> str:
    return json.dumps({"ref": ref, "object": {"type": "commit", "sha": sha}})


def run_helper(tmp_path: Path, responses: list[tuple[int, str]], *args: str) -> subprocess.CompletedProcess:
    log = tmp_path / "gh.log"
    bindir = fake_gh(tmp_path, responses, log)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_QUEUE": str(tmp_path / "responses.json"), "FAKE_GH_LOG": str(log)}
    return subprocess.run(["python3", HELPER_PATH, *args], env=env, text=True, capture_output=True)


@pytest.mark.parametrize("responses", [
    [(404, '{"message":"Not Found"}'), (422, '{"message":"exists"}')],
    [(500, '{"message":"unknown"}')],
    [(404, '{"message":"Not Found"}'), (201, 'not-json')],
])
def test_helper_cli_does_not_claim_ownership_for_422_unknown_or_malformed(tmp_path: Path, responses) -> None:
    marker = tmp_path / "owned.json"
    result = run_helper(tmp_path, responses, "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40, "--marker", str(marker))
    assert result.returncode != 0
    assert not marker.exists()
    if responses[-1][0] == 201:
        assert marker.with_suffix(".json.uncertain").exists()
    else:
        assert not marker.with_suffix(".json.uncertain").exists()


def test_helper_cli_marker_survives_interruption_and_delete_proves_absence(tmp_path: Path) -> None:
    marker = tmp_path / "owned.json"; ref = "refs/heads/qa"; sha = "a" * 40; obj = ref_obj(ref, sha)
    created = run_helper(tmp_path, [(404, '{"message":"Not Found"}'), (201, obj), (200, obj)], "create-ref", "--repo", "o/r", "--ref", ref, "--sha", sha, "--marker", str(marker))
    assert created.returncode == 0 and marker.exists()
    deleted = run_helper(tmp_path, [(200, obj), (204, ''), (404, '{"message":"Not Found"}')], "delete-ref-marker", "--marker", str(marker))
    assert deleted.returncode == 0 and not marker.exists()


def test_helper_cli_changed_ref_refuses_delete_and_retains_marker(tmp_path: Path) -> None:
    marker = tmp_path / "owned.json"; marker.write_text(json.dumps({"state":"owned","repo":"o/r","ref":"refs/heads/qa","sha":"a"*40}))
    changed = ref_obj("refs/heads/qa", "b" * 40)
    result = run_helper(tmp_path, [(200, changed)], "delete-ref-marker", "--marker", str(marker))
    assert result.returncode != 0 and marker.exists()
    assert "DELETE" not in (tmp_path / "gh.log").read_text()


def run_transport_wait(tmp_path: Path, curl_script: str, process_script: str = "sleep 5") -> subprocess.CompletedProcess:
    bindir = tmp_path / "transport-bin"; bindir.mkdir()
    curl = bindir / "curl"; curl.write_text(f"#!/usr/bin/env bash\n{curl_script}\n"); curl.chmod(0o755)
    process = subprocess.Popen(["bash", "-c", process_script])
    try:
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        return subprocess.run([WAIT_PORT_FORWARD, str(process.pid), str(tmp_path / "pf.log"), "http://localhost/status.json", "0.12", "0.02"], env=env, text=True, capture_output=True)
    finally:
        process.terminate(); process.wait()


def test_port_forward_delayed_readiness_succeeds(tmp_path: Path) -> None:
    count = tmp_path / "count"
    result = run_transport_wait(tmp_path, f'n=$(cat "{count}" 2>/dev/null || echo 0); n=$((n+1)); echo $n >"{count}"; test $n -ge 3')
    assert result.returncode == 0 and int(count.read_text()) == 3


def test_port_forward_early_death_fails_with_log_pointer(tmp_path: Path) -> None:
    dead = subprocess.Popen(["bash", "-c", "exit 0"])
    dead.wait()
    result = subprocess.run([WAIT_PORT_FORWARD, str(dead.pid), str(tmp_path / "pf.log"), "http://localhost/status.json", "0.12", "0.02"], text=True, capture_output=True)
    assert result.returncode != 0 and "exited early" in result.stderr and "pf.log" in result.stderr


def test_port_forward_timeout_is_bounded_and_reports_log(tmp_path: Path) -> None:
    result = run_transport_wait(tmp_path, "exit 1")
    assert result.returncode != 0 and "timed out" in result.stderr and "pf.log" in result.stderr


def test_restoration_rechecks_transport_before_restored_capture() -> None:
    text = SCRIPT.read_text(); restore = text[text.index("restore_if_needed()") :]
    assert restore.index("restore_source_secret") < restore.index("ensure_port_forward") < restore.index("capture_green restored")


def lifecycle_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "lifecycle"; (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "scripts/final-qa-exact-tree.sh")
    shutil.copy2(HELPER_PATH, repo / "scripts/final_qa_helpers.py")
    sha = init_repo(repo, "lifecycle")
    subprocess.run(["git", "-C", repo, "add", "scripts"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "--amend", "-qm", "lifecycle"], check=True)
    sha = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    bindir = tmp_path / "lifecycle-bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    for name in ("flux", "kubectl", "kind"):
        command = bindir / name
        command.write_text("#!/usr/bin/env bash\necho \"$(basename $0) $*\" >>\"$CALL_LOG\"\n"
                           "if [[ $(basename $0) == kubectl && $* == *'config current-context'* ]]; then echo \"$EXPECTED_CONTEXT\"; fi\n"
                           "test \"${FAIL_RESTORE:-0}\" != 1 || [[ $* != *resume* ]]\n")
        command.chmod(0o755)
    return repo, bindir, log


@pytest.mark.parametrize("scenario", ["after-suspend", "after-delete"])
def test_actual_shell_signal_restores_before_cluster_delete(tmp_path: Path, scenario: str) -> None:
    repo, bindir, log = lifecycle_repo(tmp_path); evidence = tmp_path / "evidence"; run_id = "signal"
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log),
           "EXPECTED_CONTEXT": "kind-kubecrate-qa-signal", "KUBECRATE_QA_RUN_ID": run_id,
           "KUBECRATE_QA_EVIDENCE": str(evidence), "KUBECRATE_QA_TEST_MODE": "1", "KUBECRATE_QA_TEST_SCENARIO": scenario}
    result = subprocess.run([repo / "scripts/final-qa-exact-tree.sh"], cwd=repo, env=env, text=True, capture_output=True)
    calls = log.read_text(); assert result.returncode != 0
    assert calls.index("flux --context kind-kubecrate-qa-signal resume") < calls.index("kind delete cluster")
    assert "kubectl --context kind-kubecrate-qa-signal get secret eso-smoke-source" in calls


def test_actual_shell_restoration_failure_is_nonzero_before_teardown(tmp_path: Path) -> None:
    repo, bindir, log = lifecycle_repo(tmp_path)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log), "FAIL_RESTORE": "1",
           "EXPECTED_CONTEXT": "kind-kubecrate-qa-fail", "KUBECRATE_QA_RUN_ID": "fail", "KUBECRATE_QA_EVIDENCE": str(tmp_path / "e"),
           "KUBECRATE_QA_TEST_MODE": "1", "KUBECRATE_QA_TEST_SCENARIO": "after-suspend"}
    result = subprocess.run([repo / "scripts/final-qa-exact-tree.sh"], cwd=repo, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    calls = log.read_text(); assert calls.index("resume") < calls.index("kind delete cluster")


def test_actual_shell_ref_marker_survives_helper_signal_and_is_consumed(tmp_path: Path) -> None:
    repo, bindir, log = lifecycle_repo(tmp_path); evidence = tmp_path / "ref-evidence"
    sha = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(); ref = "refs/heads/kubecrate-qa/ref"
    ghbin = fake_gh(tmp_path, [(404, '{"message":"Not Found"}'), (201, ref_obj(ref, sha)), (200, ref_obj(ref, sha)),
                               (200, ref_obj(ref, sha)), (204, ''), (404, '{"message":"Not Found"}')], tmp_path / "gh.log")
    env = {**os.environ, "PATH": f"{ghbin}:{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log), "FAKE_GH_QUEUE": str(tmp_path / "responses.json"),
           "FAKE_GH_LOG": str(tmp_path / "gh.log"), "EXPECTED_CONTEXT": "kind-kubecrate-qa-ref", "KUBECRATE_QA_RUN_ID": "ref",
           "KUBECRATE_QA_EVIDENCE": str(evidence), "KUBECRATE_QA_TEST_MODE": "1", "KUBECRATE_QA_TEST_SCENARIO": "after-ref-helper"}
    result = subprocess.run([repo / "scripts/final-qa-exact-tree.sh"], cwd=repo, env=env, text=True, capture_output=True)
    assert result.returncode != 0 and not (evidence / "owned-ref.json").exists()
    assert "-X DELETE" in (tmp_path / "gh.log").read_text()


def init_repo(path: Path, content: str) -> str:
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "qa@example.test"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "QA"], check=True)
    (path / "tracked").write_text(content)
    subprocess.run(["git", "-C", path, "add", "."], check=True)
    subprocess.run(["git", "-C", path, "commit", "-qm", content], check=True)
    return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()


def run_identity_gate(repo: Path, candidate: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KUBECRATE_QA_CANDIDATE": candidate, "KUBECRATE_QA_IDENTITY_GATE_ONLY": "1"}
    return subprocess.run([SCRIPT], cwd=repo, env=env, text=True, capture_output=True)


def test_clean_checkout_a_candidate_b_rejects_before_any_external_command(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    a = init_repo(repo, "a")
    (repo / "tracked").write_text("b")
    subprocess.run(["git", "-C", repo, "commit", "-qam", "b"], check=True)
    b = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", repo, "checkout", "-q", a], check=True)
    result = run_identity_gate(repo, b)
    assert result.returncode != 0
    assert "local HEAD must equal candidate" in result.stderr


def test_matching_candidate_passes_identity_gate_and_untracked_rejects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = init_repo(repo, "match")
    result = run_identity_gate(repo, sha)
    assert result.returncode == 0, result.stderr
    (repo / "shadow").write_text("bad")
    result = run_identity_gate(repo, sha)
    assert result.returncode != 0
    assert "untracked files" in result.stderr
