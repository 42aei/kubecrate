#!/usr/bin/env python3
"""Behavioral tests for exact-tree final-QA safety helpers."""

import importlib.util
import json
import os
import signal
import stat
import subprocess
import shutil
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER_PATH = ROOT / "scripts" / "final_qa_helpers.py"
SCRIPT = ROOT / "scripts" / "final-qa-exact-tree.sh"
LIFECYCLE = ROOT / "scripts" / "final-qa-lifecycle.sh"
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


def test_ref_race_422_never_establishes_ownership(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"
    api = FakeRefs([None], create=helpers.APIError(422, "exists"))
    with pytest.raises(helpers.APIError):
        helpers.create_owned_ref(
            api, "refs/heads/qa", "a" * 40, repo="o/r", marker=marker, evidence_root=root
        )
    assert not marker.exists()
    assert not marker.with_suffix(".json.uncertain").exists()
    assert not any(c[0] == "delete" for c in api.calls)


def test_unknown_lookup_fails_closed_before_create() -> None:
    api = FakeRefs([helpers.APIError(500, "unknown")])
    with pytest.raises(helpers.APIError):
        helpers.create_owned_ref(api, "refs/heads/qa", "a" * 40)
    assert not any(c[0] == "create" for c in api.calls)


def test_owned_create_establishes_exact_ref() -> None:
    sha = "a" * 40
    obj = {"ref": "refs/heads/qa", "object": {"type": "commit", "sha": sha}}
    api = FakeRefs([None, obj], create=obj)
    helpers.create_owned_ref(api, "refs/heads/qa", sha)
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
    text = LIFECYCLE.read_text()
    suspend = text.index('flux --context "${CONTEXT}" suspend')
    delete = text.index('kubectl --context "${CONTEXT}" delete secret')
    intent = text.index("RED_STATE=restore_required")
    assert intent < suspend < delete
    cleanup = text[text.index("cleanup()") : text.index("install_cleanup_traps()")]
    assert cleanup.index("restore_if_needed") < cleanup.index("kind delete cluster")


def fake_gh(tmp_path: Path, responses: list, log: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    queue = tmp_path / "responses.json"
    queue.write_text(json.dumps(responses))
    gh = bindir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys,pathlib\n"
        "q=pathlib.Path(os.environ['FAKE_GH_QUEUE']); data=json.loads(q.read_text()); item=data.pop(0); q.write_text(json.dumps(data))\n"
        "pathlib.Path(os.environ['FAKE_GH_LOG']).open('a').write(' '.join(sys.argv[1:])+'\\n')\n"
        "status,body=item[0],item[1]; include='--include' in sys.argv; stream=sys.stderr if len(item)>2 and item[2]=='stderr' else sys.stdout\n"
        "print(body if (not include or body.startswith('HTTP/')) else f'HTTP/2 {status} status\\ncontent-type: application/json\\n\\n{body}', file=stream)\n"
        "print(f'gh: request failed (HTTP {status})', file=sys.stderr) if status >= 400 else None\n"
        "raise SystemExit(0 if status < 400 else 1)\n"
    )
    gh.chmod(0o755)
    return bindir


def ref_obj(ref: str, sha: str) -> str:
    return json.dumps({"ref": ref, "object": {"type": "commit", "sha": sha}})


def run_helper(tmp_path: Path, responses: list, *args: str) -> subprocess.CompletedProcess:
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
    root = tmp_path / "evidence"; marker = root / "owned.json"
    result = run_helper(tmp_path, responses, "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40, "--evidence-root", str(root), "--marker", str(marker))
    assert result.returncode != 0
    assert not marker.exists()
    if responses[-1][0] == 201:
        assert marker.with_suffix(".json.uncertain").exists()
    else:
        assert not marker.with_suffix(".json.uncertain").exists()


def test_legacy_delete_ref_marker_cli_is_retired_without_api_or_evidence_loss(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700)
    marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    marker.write_text(json.dumps({"state":"owned","repo":"o/r","ref":"refs/heads/qa","sha":"a"*40})); marker.chmod(0o600)
    uncertain.write_text(json.dumps({"state":"created-unverified","repo":"o/r","ref":"refs/heads/qa","sha":"a"*40})); uncertain.chmod(0o600)
    result = run_helper(
        tmp_path, [(200, ref_obj("refs/heads/qa", "a"*40)), (204, ""), (404, '{"message":"Not Found"}')],
        "delete-ref-marker", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a"*40,
        "--evidence-root", str(root), "--marker", str(marker))
    assert result.returncode != 0
    assert marker.exists() and uncertain.exists()
    assert not (tmp_path / "gh.log").exists()


def test_helper_cli_marker_survives_interruption_and_delete_proves_absence(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; ref = "refs/heads/qa"; sha = "a" * 40; obj = ref_obj(ref, sha)
    created = run_helper(tmp_path, [(404, '{"message":"Not Found"}'), (201, obj), (200, obj)], "create-ref", "--repo", "o/r", "--ref", ref, "--sha", sha, "--evidence-root", str(root), "--marker", str(marker))
    assert created.returncode == 0 and marker.exists()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    deleted = run_helper(tmp_path, [(200, obj), (204, ''), (404, '{"message":"Not Found"}')], "cleanup-ref-markers", "--repo", "o/r", "--ref", ref, "--sha", sha, "--evidence-root", str(root), "--owned-marker", str(marker), "--uncertain-marker", str(marker.with_suffix(".json.uncertain")), "--branch-created", "true")
    assert deleted.returncode == 0 and not marker.exists()


def test_helper_cli_empty_create_body_uses_exact_readback_then_marker_gated_delete(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    ref = "refs/heads/qa"; sha = "a" * 40; obj = ref_obj(ref, sha)
    created = run_helper(
        tmp_path,
        [(404, '{"message":"Not Found"}'), (201, ""), (200, obj)],
        "create-ref", "--repo", "o/r", "--ref", ref, "--sha", sha,
        "--evidence-root", str(root), "--marker", str(marker),
    )
    assert created.returncode == 0 and marker.exists() and not uncertain.exists()
    deleted = run_helper(
        tmp_path,
        [(200, obj), (204, ""), (404, '{"message":"Not Found"}')],
        "cleanup-ref-markers", "--repo", "o/r", "--ref", ref, "--sha", sha,
        "--evidence-root", str(root), "--owned-marker", str(marker),
        "--uncertain-marker", str(uncertain), "--branch-created", "true",
    )
    assert deleted.returncode == 0 and not marker.exists() and not uncertain.exists()
    assert "-X DELETE" in (tmp_path / "gh.log").read_text()


@pytest.mark.parametrize("readback", [
    (404, '{"message":"Not Found"}'),
    (200, "[]"),
    (200, ref_obj("refs/heads/other", "a" * 40)),
    (200, ref_obj("refs/heads/qa", "b" * 40)),
    (500, '{"message":"unknown"}'),
])
def test_helper_cli_empty_create_body_unproved_readback_retains_uncertainty_without_delete(
    tmp_path: Path, readback: tuple[int, str]
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    result = run_helper(
        tmp_path,
        [(404, '{"message":"Not Found"}'), (201, ""), readback],
        "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40,
        "--evidence-root", str(root), "--marker", str(marker),
    )
    assert result.returncode != 0 and not marker.exists() and uncertain.exists()
    assert "-X DELETE" not in (tmp_path / "gh.log").read_text()


def test_helper_cli_mismatched_create_object_retains_uncertainty_without_readback_or_delete(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    result = run_helper(
        tmp_path,
        [(404, '{"message":"Not Found"}'), (201, ref_obj("refs/heads/other", "a" * 40))],
        "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40,
        "--evidence-root", str(root), "--marker", str(marker),
    )
    assert result.returncode != 0 and not marker.exists() and uncertain.exists()
    log = (tmp_path / "gh.log").read_text()
    assert log.count("-X GET") == 1 and "-X DELETE" not in log


def test_helper_cli_changed_ref_refuses_delete_and_retains_marker(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700); marker = root / "owned.json"; marker.write_text(json.dumps({"state":"owned","repo":"o/r","ref":"refs/heads/qa","sha":"a"*40})); marker.chmod(0o600)
    changed = ref_obj("refs/heads/qa", "b" * 40)
    result = run_helper(tmp_path, [(200, changed)], "cleanup-ref-markers", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a"*40, "--evidence-root", str(root), "--owned-marker", str(marker), "--uncertain-marker", str(marker.with_suffix(".json.uncertain")), "--branch-created", "true")
    assert result.returncode != 0 and marker.exists()
    assert "DELETE" not in (tmp_path / "gh.log").read_text()


@pytest.mark.parametrize("field,value", [("repo", "evil/r"), ("ref", "refs/heads/other"), ("sha", "b" * 40)])
def test_marker_expected_identity_mismatch_retains_marker_without_api(tmp_path: Path, field: str, value: str) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700); marker = root / "owned.json"
    data = {"state": "owned", "repo": "o/r", "ref": "refs/heads/qa", "sha": "a" * 40}; data[field] = value
    marker.write_text(json.dumps(data)); marker.chmod(0o600)
    result = run_helper(tmp_path, [], "cleanup-ref-markers", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a"*40, "--evidence-root", str(root), "--owned-marker", str(marker), "--uncertain-marker", str(marker.with_suffix(".json.uncertain")), "--branch-created", "true")
    assert result.returncode != 0 and marker.exists()
    assert not (tmp_path / "gh.log").exists()


@pytest.mark.parametrize("kind", ["symlink-root", "symlink-marker", "outside", "traversal", "malformed"])
def test_marker_refuses_unsafe_paths_and_malformed_content(tmp_path: Path, kind: str) -> None:
    real = tmp_path / "real"; real.mkdir(mode=0o700)
    root = tmp_path / "evidence"
    if kind == "symlink-root": root.symlink_to(real, target_is_directory=True)
    else: root.mkdir(mode=0o700)
    marker = root / "owned.json"
    if kind == "symlink-marker": marker.symlink_to(tmp_path / "victim")
    elif kind == "outside": marker = tmp_path / "outside.json"
    elif kind == "traversal": marker = root / ".." / "outside.json"
    elif kind == "malformed": marker.write_text("{"); marker.chmod(0o600)
    args = ("create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a"*40, "--evidence-root", str(root), "--marker", str(marker))
    responses = [(404, '{"message":"Not Found"}'), (201, ref_obj("refs/heads/qa", "a"*40)), (200, ref_obj("refs/heads/qa", "a"*40))]
    if kind == "malformed":
        args = ("cleanup-ref-markers", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a"*40, "--evidence-root", str(root), "--owned-marker", str(marker), "--uncertain-marker", str(marker.with_suffix(".json.uncertain")), "--branch-created", "true"); responses = []
    result = run_helper(tmp_path, responses, *args)
    assert result.returncode != 0


def test_marker_write_and_unlink_fsync_file_and_parent(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; events = []
    real_fsync, real_replace, real_unlink = helpers.os.fsync, helpers.os.replace, helpers.os.unlink
    monkeypatch.setattr(helpers.os, "fsync", lambda fd: (events.append(("fsync", stat.S_ISDIR(os.fstat(fd).st_mode))), real_fsync(fd))[1])
    monkeypatch.setattr(helpers.os, "replace", lambda *a, **kw: (events.append(("replace", False)), real_replace(*a, **kw))[1])
    monkeypatch.setattr(helpers.os, "unlink", lambda *a, **kw: (events.append(("unlink", False)), real_unlink(*a, **kw))[1])
    helpers._write_marker(marker, "o/r", "refs/heads/qa", "a"*40, "owned", evidence_root=root)
    assert events[:3] == [("fsync", False), ("replace", False), ("fsync", True)]
    api = FakeRefs([{"ref":"refs/heads/qa","object":{"type":"commit","sha":"a"*40}}, None])
    helpers.cleanup_ref_markers(marker, marker.with_suffix(".json.uncertain"), evidence_root=root, expected_repo="o/r", expected_ref="refs/heads/qa", expected_sha="a"*40, branch_created=True, api=api)
    assert events[-2:] == [("unlink", False), ("fsync", True)]


@pytest.mark.parametrize("raw,status,body", [
    ("HTTP/1.1 200 Connection established\nproxy: yes\n\nHTTP/2 404 Not Found\ncontent-type: application/json\n\n{\"message\":\"Not Found\"}", 404, {"message": "Not Found"}),
    ("HTTP/2 204 No Content\nserver: github\n\n", 204, None),
    # gh 2.45 emits the status line with LF while the remaining headers use
    # CRLF. This is the framing captured from the live successful POST.
    ("HTTP/2.0 201 Created\nAccess-Control-Allow-Origin: *\r\nContent-Type: application/json; charset=utf-8\r\nX-GitHub-Request-Id: probe\r\n\r\n{\"ref\":\"refs/heads/kubecrate-qa/parser-probe\",\"object\":{\"sha\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"type\":\"commit\"}}", 201, {"ref": "refs/heads/kubecrate-qa/parser-probe", "object": {"sha": "a" * 40, "type": "commit"}}),
])
def test_github_parser_uses_final_http_block(tmp_path: Path, raw: str, status: int, body) -> None:
    assert helpers.GitHubRefsAPI._parse_response(raw) == (status, body)


def test_github_refs_api_rejects_non_object_success_and_malformed_404(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"
    result = run_helper(
        tmp_path,
        [(404, '{"message":"Not Found"}'), (201, "[]")],
        "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40,
        "--evidence-root", str(root), "--marker", str(marker),
    )
    assert result.returncode != 0 and not marker.exists()
    assert marker.with_suffix(".json.uncertain").exists()

    bindir = fake_gh(tmp_path, [[404, "[]"]], tmp_path / "lookup.log")
    old = os.environ.copy(); os.environ.update({"PATH": f"{bindir}:{old['PATH']}", "FAKE_GH_QUEUE": str(tmp_path / "responses.json"), "FAKE_GH_LOG": str(tmp_path / "lookup.log")})
    try:
        with pytest.raises(helpers.APIError):
            helpers.GitHubRefsAPI("o/r").get("refs/heads/qa")
    finally:
        os.environ.clear(); os.environ.update(old)


def test_github_empty_success_body_returns_no_create_claim_and_ignores_stderr(monkeypatch) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout="",
        stderr='HTTP/2 201 Created\n\n{"ref":"wrong-stream"}',
    )
    monkeypatch.setattr(helpers.subprocess, "run", lambda *args, **kwargs: result)
    assert helpers.GitHubRefsAPI("o/r").create("refs/heads/qa", "a" * 40) is None


def test_github_parser_accepts_stderr_response_and_rejects_stale_or_malformed(tmp_path: Path) -> None:
    raw = 'HTTP/1.1 500 Stale\n\n{"message":"stale"}\nHTTP/2 200 OK\ncontent-type: application/json\n\n{"ref":"final"}'
    result = run_helper(tmp_path, [[200, raw, "stderr"]], "delete-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a"*40)
    assert result.returncode != 0
    assert not (tmp_path / "gh.log").exists()  # removed ungated form fails before any API call
    with pytest.raises(helpers.APIError):
        helpers.GitHubRefsAPI._parse_response("HTTP/2 nope\n\n{}")
    with pytest.raises(helpers.APIError):
        helpers.GitHubRefsAPI._parse_response("HTTP/2 200 OK\n\nnot-json")


def test_existing_permissive_evidence_root_is_refused_without_rehabilitation(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o755)
    result = run_helper(tmp_path, [], "prepare-evidence", "--evidence-root", str(root))
    assert result.returncode != 0 and stat.S_IMODE(root.stat().st_mode) == 0o755
    assert not (tmp_path / "gh.log").exists()


def test_parent_component_swap_to_symlink_is_refused(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    root = Path("parent/evidence"); root.mkdir(parents=True, mode=0o700); root.parent.chmod(0o700)
    outside = tmp_path / "outside"; outside.mkdir(mode=0o700)
    real_open = helpers.os.open; swapped = False
    def swap_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "evidence" and kwargs.get("dir_fd") is not None and not swapped:
            root.rename(root.with_name("moved")); root.symlink_to(outside, target_is_directory=True); swapped = True
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(helpers.os, "open", swap_open)
    with pytest.raises(OSError):
        helpers._private_evidence_dir(root)
    assert list(outside.iterdir()) == []


def test_marker_wrong_mode_fails_before_api_and_is_retained(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700); marker = root / "owned.json"
    marker.write_text(json.dumps({"state":"owned","repo":"o/r","ref":"refs/heads/qa","sha":"a"*40})); marker.chmod(0o644)
    api = FakeRefs([])
    with pytest.raises(AssertionError):
        helpers.cleanup_ref_markers(marker, marker.with_suffix(".json.uncertain"), evidence_root=root, expected_repo="o/r", expected_ref="refs/heads/qa", expected_sha="a"*40, branch_created=True, api=api)
    assert marker.exists() and api.calls == []


def test_marker_replacement_before_api_is_detected_and_retained(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700); marker = root / "owned.json"
    marker.write_text(json.dumps({"state":"owned","repo":"o/r","ref":"refs/heads/qa","sha":"a"*40})); marker.chmod(0o600)
    original = helpers._assert_entry_identity; swapped = False
    def swap(name, directory_fd, opened):
        nonlocal swapped
        if not swapped:
            replacement = root / "replacement"
            replacement.write_text(marker.read_text()); replacement.chmod(0o600); replacement.replace(marker); swapped = True
        original(name, directory_fd, opened)
    monkeypatch.setattr(helpers, "_assert_entry_identity", swap)
    api = FakeRefs([])
    with pytest.raises(AssertionError):
        helpers.cleanup_ref_markers(marker, marker.with_suffix(".json.uncertain"), evidence_root=root, expected_repo="o/r", expected_ref="refs/heads/qa", expected_sha="a"*40, branch_created=True, api=api)
    assert marker.exists() and api.calls == []


def test_confined_private_cleanup_refuses_symlink_child(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700)
    external = tmp_path / "external"; external.mkdir(); victim = external / "keep"; victim.write_text("safe")
    (root / "private").symlink_to(external, target_is_directory=True)
    result = run_helper(tmp_path, [], "cleanup-private", "--evidence-root", str(root))
    assert result.returncode != 0 and victim.read_text() == "safe"


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
    text = LIFECYCLE.read_text(); restore = text[text.index("restore_if_needed()") :]
    assert restore.index("restore_source_secret") < restore.index("ensure_port_forward") < restore.index("capture_green restored")


def lifecycle_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "lifecycle"; (repo / "scripts").mkdir(parents=True)
    shutil.copy2(LIFECYCLE, repo / "scripts/final-qa-lifecycle.sh")
    shutil.copy2(HELPER_PATH, repo / "scripts/final_qa_helpers.py")
    shutil.copy2(WAIT_PORT_FORWARD, repo / "scripts/wait-port-forward.sh")
    harness = repo / "harness.sh"
    harness.write_text('''#!/usr/bin/env bash
set -Eeuo pipefail
REPO=o/r; QA_BRANCH=kubecrate-qa/test; CANDIDATE_SHA="${CANDIDATE_SHA}"; CLUSTER=kubecrate-qa-test; CONTEXT=kind-kubecrate-qa-test
EVIDENCE="${EVIDENCE}"; OWNED_REF_MARKER="${EVIDENCE}/owned-ref.json"; UNCERTAIN_REF_MARKER="${OWNED_REF_MARKER}.uncertain"
KEY_ID=; PORT_FORWARD_PID=; BRANCH_CREATED=false; CLUSTER_CREATED=true; INITIAL_TREE="$(git write-tree)"; RED_STATE=none; EVIDENCE_READY=false
fail() { echo "ERROR: $*" >&2; return 1; }
assert_context() { test "$(kubectl config current-context)" = "${CONTEXT}"; }
source scripts/final-qa-lifecycle.sh
python3 scripts/final_qa_helpers.py prepare-evidence --evidence-root "${EVIDENCE}"
EVIDENCE_READY=true
install_cleanup_traps
if test "${SCENARIO}" = after-ref-helper; then
  python3 scripts/final_qa_helpers.py create-ref --repo "${REPO}" --ref "refs/heads/${QA_BRANCH}" --sha "${CANDIDATE_SHA}" --evidence-root "${EVIDENCE}" --marker "${OWNED_REF_MARKER}"
  echo ref-helper-ready >"${BARRIER}"
  while :; do sleep 1; done
fi
controlled_red
while :; do sleep 1; done
'''); harness.chmod(0o755)
    init_repo(repo, "lifecycle")
    subprocess.run(["git", "-C", repo, "add", "scripts"], check=True)
    subprocess.run(["git", "-C", repo, "add", "harness.sh"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "--amend", "-qm", "lifecycle"], check=True)
    bindir = tmp_path / "lifecycle-bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    status_file = tmp_path / "status.json"; status_file.write_text(json.dumps(payload()))
    html_file = tmp_path / "status.html"; html_file.write_text(html())
    for name in ("flux", "kubectl", "kind", "curl", "chromium"):
        command = bindir / name
        command.write_text("#!/usr/bin/env bash\nname=$(basename $0); echo \"$name $*\" >>\"$CALL_LOG\"\n"
                           "if [[ $name == kubectl && $* == *'config current-context'* ]]; then echo kind-kubecrate-qa-test; fi\n"
                           "if [[ $name == kubectl && $* == *'port-forward'* ]]; then sleep 30; fi\n"
                           "if [[ $name == kind && $* == 'get clusters' ]]; then test -f \"$CLUSTER_DELETED\" || echo kubecrate-qa-test; fi\n"
                           "if [[ $name == kind && $* == *'delete cluster'* ]]; then touch \"$CLUSTER_DELETED\"; fi\n"
                           "if [[ $name == curl ]]; then cat \"$STATUS_FILE\"; fi\n"
                           "if [[ $name == chromium ]]; then cat \"$HTML_FILE\"; fi\n"
                           "if [[ $name == flux && $* == *suspend* && $SCENARIO == after-suspend ]]; then touch \"$BARRIER\"; fi\n"
                           "if [[ $name == kubectl && $* == *'delete secret'* && $SCENARIO == after-delete ]]; then touch \"$BARRIER\"; fi\n"
                           "test \"${FAIL_RESTORE:-0}\" != 1 || [[ $* != *resume* ]]\n")
        command.chmod(0o755)
    return repo, bindir, log


def run_lifecycle_signal(tmp_path: Path, scenario: str, *, fail_restore: bool = False):
    repo, bindir, log = lifecycle_repo(tmp_path); evidence = tmp_path / "evidence"; barrier = tmp_path / "barrier"
    sha = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log), "SCENARIO": scenario,
           "CANDIDATE_SHA": sha, "EVIDENCE": str(evidence), "BARRIER": str(barrier), "CLUSTER_DELETED": str(tmp_path / "deleted"),
           "KUBECRATE_QA_OBSERVE_SECONDS": "0", "KUBECRATE_QA_PORT_FORWARD_TIMEOUT": "1", "KUBECRATE_QA_PORT_FORWARD_POLL_INTERVAL": ".01",
           "STATUS_FILE": str(tmp_path / "status.json"), "HTML_FILE": str(tmp_path / "status.html"), "FAIL_RESTORE": "1" if fail_restore else "0"}
    process = subprocess.Popen([repo / "harness.sh"], cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.monotonic() + 5
    while not barrier.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(0.01)
    assert barrier.exists(), process.communicate(timeout=1)
    os.killpg(process.pid, signal.SIGINT if scenario == "after-delete" else signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=10)
    return process.returncode, log.read_text(), stdout, stderr, evidence


@pytest.mark.parametrize("scenario", ["after-suspend", "after-delete"])
def test_actual_shell_signal_restores_before_cluster_delete(tmp_path: Path, scenario: str) -> None:
    rc, calls, _, _, _ = run_lifecycle_signal(tmp_path, scenario)
    assert rc != 0
    assert calls.index("flux --context kind-kubecrate-qa-test resume") < calls.index("kind delete cluster")
    assert "kubectl --context kind-kubecrate-qa-test get secret eso-smoke-source" in calls
    assert "kubectl --context kind-kubecrate-qa-test port-forward" in calls
    assert "curl --fail --silent --show-error" in calls
    assert "chromium --headless" in calls


def test_actual_shell_restoration_failure_is_nonzero_before_teardown(tmp_path: Path) -> None:
    rc, calls, _, _, _ = run_lifecycle_signal(tmp_path, "after-suspend", fail_restore=True)
    assert rc != 0 and calls.index("resume") < calls.index("kind delete cluster")


def test_actual_shell_ref_marker_survives_helper_signal_and_is_consumed(tmp_path: Path) -> None:
    repo, bindir, log = lifecycle_repo(tmp_path); evidence = tmp_path / "ref-evidence"; barrier = tmp_path / "barrier"
    sha = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(); ref = "refs/heads/kubecrate-qa/test"
    ghbin = fake_gh(tmp_path, [(404, '{"message":"Not Found"}'), (201, ref_obj(ref, sha)), (200, ref_obj(ref, sha)), (200, ref_obj(ref, sha)), (204, ''), (404, '{"message":"Not Found"}')], tmp_path / "gh.log")
    env = {**os.environ, "PATH": f"{ghbin}:{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log), "SCENARIO": "after-ref-helper", "CANDIDATE_SHA": sha,
           "EVIDENCE": str(evidence), "BARRIER": str(barrier), "CLUSTER_DELETED": str(tmp_path / "deleted"), "STATUS_FILE": str(tmp_path / "status.json"),
           "HTML_FILE": str(tmp_path / "status.html"), "FAKE_GH_QUEUE": str(tmp_path / "responses.json"), "FAKE_GH_LOG": str(tmp_path / "gh.log")}
    process = subprocess.Popen([repo / "harness.sh"], cwd=repo, env=env, start_new_session=True); deadline = time.monotonic() + 5
    while not barrier.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(.01)
    assert barrier.exists(); os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=10)
    assert process.returncode != 0 and not (evidence / "owned-ref.json").exists()
    assert "-X DELETE" in (tmp_path / "gh.log").read_text()


def run_shipped_ref_cleanup(tmp_path: Path, *, branch_created: bool, owned: str = "absent",
                            uncertain: str = "absent", responses: list | None = None):
    repo = tmp_path / "cleanup"; (repo / "scripts").mkdir(parents=True)
    shutil.copy2(LIFECYCLE, repo / "scripts/final-qa-lifecycle.sh")
    shutil.copy2(HELPER_PATH, repo / "scripts/final_qa_helpers.py")
    sha = init_repo(repo, "cleanup"); evidence = tmp_path / "cleanup-evidence"
    evidence.mkdir(mode=0o700); marker = evidence / "owned-ref.json"; uncertain_marker = evidence / "owned-ref.json.uncertain"
    good_owned = {"state": "owned", "repo": "o/r", "ref": "refs/heads/kubecrate-qa/test", "sha": sha}
    good_uncertain = {**good_owned, "state": "created-unverified"}
    for path, state, payload_value in ((marker, owned, good_owned), (uncertain_marker, uncertain, good_uncertain)):
        if state == "valid":
            path.write_text(json.dumps(payload_value)); path.chmod(0o600)
        elif state == "malformed":
            path.write_text("{"); path.chmod(0o600)
        elif state == "mismatch":
            path.write_text(json.dumps({**payload_value, "sha": "b" * 40})); path.chmod(0o600)
        elif state == "symlink":
            path.symlink_to(tmp_path / "missing-target")
    harness = repo / "cleanup.sh"
    harness.write_text('''#!/usr/bin/env bash
set -Eeuo pipefail
REPO=o/r; QA_BRANCH=kubecrate-qa/test; CANDIDATE_SHA="$CANDIDATE_SHA"; EVIDENCE="$EVIDENCE"
OWNED_REF_MARKER="$EVIDENCE/owned-ref.json"; UNCERTAIN_REF_MARKER="$OWNED_REF_MARKER.uncertain"
KEY_ID=; PORT_FORWARD_PID=; BRANCH_CREATED="$BRANCH_CREATED"; CLUSTER_CREATED=false
INITIAL_TREE="$(git write-tree)"; RED_STATE=none; EVIDENCE_READY=true; CLUSTER=unused
source scripts/final-qa-lifecycle.sh
cleanup
'''); harness.chmod(0o755)
    log = tmp_path / "cleanup-gh.log"
    resolved_responses = [
        (status, ref_obj("refs/heads/kubecrate-qa/test", sha) if body == "__REF_OBJECT__" else body, *rest)
        for status, body, *rest in (responses or [])
    ]
    bindir = fake_gh(tmp_path, resolved_responses, log)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_QUEUE": str(tmp_path / "responses.json"),
           "FAKE_GH_LOG": str(log), "CANDIDATE_SHA": sha, "EVIDENCE": str(evidence),
           "BRANCH_CREATED": "true" if branch_created else "false"}
    result = subprocess.run([harness], cwd=repo, env=env, text=True, capture_output=True)
    return result, marker, uncertain_marker, (log.read_text() if log.exists() else "")


@pytest.mark.parametrize("owned", ["absent", "symlink"])
def test_shipped_cleanup_created_branch_requires_safe_owned_marker(tmp_path: Path, owned: str) -> None:
    result, marker, _, calls = run_shipped_ref_cleanup(tmp_path, branch_created=True, owned=owned)
    assert result.returncode != 0
    assert "DELETE" not in calls
    if owned == "symlink":
        assert marker.is_symlink()


@pytest.mark.parametrize("uncertain", ["valid", "symlink", "malformed", "mismatch"])
def test_shipped_cleanup_uncertain_or_unsafe_marker_fails_closed_and_retains_diagnostic(tmp_path: Path, uncertain: str) -> None:
    result, _, marker, calls = run_shipped_ref_cleanup(tmp_path, branch_created=False, uncertain=uncertain)
    assert result.returncode != 0
    assert "DELETE" not in calls
    assert marker.is_symlink() if uncertain == "symlink" else marker.exists()


def test_shipped_cleanup_valid_owned_marker_deletes_exact_ref_and_consumes_marker(tmp_path: Path) -> None:
    result, marker, _, calls = run_shipped_ref_cleanup(
        tmp_path, branch_created=True, owned="valid", responses=[
            (200, "__REF_OBJECT__"), (204, ""), (404, '{"message":"Not Found"}')])
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "-X DELETE repos/o/r/git/refs/heads/kubecrate-qa/test" in calls


def test_shipped_cleanup_absent_markers_are_ok_without_create_state(tmp_path: Path) -> None:
    result, _, _, calls = run_shipped_ref_cleanup(tmp_path, branch_created=False)
    assert result.returncode == 0, result.stderr
    assert "DELETE" not in calls


def test_shipped_entrypoint_ignores_test_failpoint_env_and_refuses_shared_cluster(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; repo.mkdir(); shutil.copytree(ROOT / "scripts", repo / "scripts"); sha = init_repo(repo, "guard")
    bindir = tmp_path / "guard-bin"; bindir.mkdir(); log = tmp_path / "guard.log"
    for name in ("gh", "kind", "kubectl", "kustomize", "helm", "flux", "ssh-keygen", "curl", "base64"):
        path = bindir / name; path.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >>"$CALL_LOG"\n'); path.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log), "KUBECRATE_QA_CANDIDATE": sha,
           "KUBECRATE_QA_CLUSTER": "kind-dev-misc-local", "KUBECRATE_QA_TEST_MODE": "1", "KUBECRATE_QA_TEST_SCENARIO": "after-delete", "KUBECRATE_QA_FAILPOINT": "after-ref-helper"}
    result = subprocess.run([repo / "scripts/final-qa-exact-tree.sh"], cwd=repo, env=env, text=True, capture_output=True)
    calls = log.read_text() if log.exists() else ""
    assert result.returncode != 0 and "refusing shared cluster" in result.stderr
    assert not any(word in calls for word in ("create cluster", "delete cluster", "suspend", "delete secret", "api -X"))


def test_shipped_entrypoint_symlinked_evidence_early_failure_mutates_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"; repo.mkdir(); shutil.copytree(ROOT / "scripts", repo / "scripts"); sha = init_repo(repo, "guard")
    external = tmp_path / "external"; private = external / "private"; private.mkdir(parents=True); victim = private / "keep"; victim.write_text("untouched")
    evidence = tmp_path / "evidence"; evidence.symlink_to(external, target_is_directory=True)
    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls"
    for name in ("gh", "kind", "kubectl"):
        command = bindir / name; command.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >>"$CALL_LOG"\n'); command.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(log), "KUBECRATE_QA_CANDIDATE": sha,
           "KUBECRATE_QA_EVIDENCE": str(evidence)}
    result = subprocess.run([repo / "scripts/final-qa-exact-tree.sh"], cwd=repo, env=env, text=True, capture_output=True)
    assert result.returncode != 0 and victim.read_text() == "untouched"
    calls = log.read_text() if log.exists() else ""
    assert not any(word in calls for word in ("api", "delete cluster", "delete secret", "suspend"))


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


def test_invalid_kind_override_fails_before_any_external_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = init_repo(repo, "invalid-cluster")
    bindir = tmp_path / "bin"; bindir.mkdir()
    mutation_log = tmp_path / "mutations.log"
    for name in ("gh", "kind", "kubectl", "kustomize", "helm", "flux", "ssh-keygen", "curl", "base64"):
        command = bindir / name
        command.write_text(f"#!/bin/sh\nprintf '%s\\n' '{name} $*' >>'{mutation_log}'\nexit 99\n")
        command.chmod(0o755)
    evidence = tmp_path / "evidence"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "KUBECRATE_QA_CANDIDATE": sha,
        "KUBECRATE_QA_CLUSTER": "kubecrate-qa-20260714T213200Z",
        "KUBECRATE_QA_EVIDENCE": str(evidence),
    }
    result = subprocess.run([SCRIPT], cwd=repo, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "invalid kind cluster name" in result.stderr
    assert not mutation_log.exists()


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
