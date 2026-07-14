#!/usr/bin/env python3
"""Behavioral tests for exact-tree final-QA safety helpers."""

import ctypes
import base64
import errno
import importlib.util
import json
import os
import signal
import stat
import subprocess
import shutil
import time
from contextlib import nullcontext
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
        if isinstance(value, BaseException):
            raise value
        return value

    def create(self, ref, sha):
        self.calls.append(("create", ref, sha))
        if callable(self.create_result):
            return self.create_result(ref, sha)
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
    # The pre-POST attempt marker is deliberately retained: a 422 after an
    # absent preflight can be a race and cannot prove which actor created it.
    assert marker.with_suffix(".json.uncertain").exists()
    assert not any(c[0] == "delete" for c in api.calls)


def test_unknown_lookup_fails_closed_before_create() -> None:
    api = FakeRefs([helpers.APIError(500, "unknown")])
    with pytest.raises(helpers.APIError):
        helpers.create_owned_ref(api, "refs/heads/qa", "a" * 40)
    assert not any(c[0] == "create" for c in api.calls)


class FakeKeys:
    def __init__(self, listed=None, created=None, readback=None):
        self.listed = list(listed or [])
        self.created = created
        self.readback = readback
        self.calls = []

    def list(self):
        self.calls.append(("list",))
        if self.listed and isinstance(self.listed[0], list):
            return self.listed.pop(0)
        return self.listed

    def create(self, title, key):
        self.calls.append(("create", title))
        if isinstance(self.created, BaseException): raise self.created
        return self.created

    def get(self, key_id):
        self.calls.append(("get", key_id))
        return self.readback

    def delete(self, key_id):
        self.calls.append(("delete", key_id))
        self.readback = None


def deploy_key(key_id=7, title="kubecrate-qa-run", key=None):
    key = key or public_key()
    return {"id": key_id, "title": title, "key": key,
            "read_only": True, "verified": True, "enabled": True}


def public_key(seed: int = 1, comment: str = "qa") -> str:
    algorithm = b"ssh-ed25519"
    blob = len(algorithm).to_bytes(4, "big") + algorithm + len(bytes([seed]) * 32).to_bytes(4, "big") + bytes([seed]) * 32
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"


def test_public_key_fingerprint_normalizes_comment_and_spacing_and_rejects_bad_keys() -> None:
    key = public_key()
    bare = " ".join(key.split()[:2])
    assert helpers._public_key_fingerprint(key) == helpers._public_key_fingerprint(f"  {bare}   other comment  ")
    assert helpers._public_key_fingerprint(key).startswith("SHA256:")
    for bad in ("ssh-ed25519 !!!", "ssh-dss AAAA", "ssh-rsa " + key.split()[1], "ssh-ed25519 AAAA"):
        with pytest.raises(AssertionError):
            helpers._public_key_fingerprint(bad)


def test_public_key_fingerprint_strictly_parses_ed25519_ssh_blob() -> None:
    algorithm = b"ssh-ed25519"
    def line(blob: bytes, outer: str = "ssh-ed25519") -> str:
        return f"{outer} {base64.b64encode(blob).decode()} comment with spaces"
    ssh_string = lambda value: len(value).to_bytes(4, "big") + value
    valid = ssh_string(algorithm) + ssh_string(b"k" * 32)
    assert helpers._public_key_fingerprint(line(valid)) == helpers._public_key_fingerprint(
        "  " + line(valid, "ssh-ed25519") + "  ")
    malformed = (
        b"", b"\0\0\0", b"\0\0\0\x0cssh-ed2551",  # truncated length/algorithm
        ssh_string(algorithm),
        ssh_string(algorithm) + ssh_string(b"k" * 31),
        ssh_string(algorithm) + ssh_string(b"k" * 33),
        valid + b"trailing",
        ssh_string(b"ssh-rsa") + ssh_string(b"k" * 32),
        (999).to_bytes(4, "big") + algorithm + ssh_string(b"k" * 32),
    )
    for blob in malformed:
        with pytest.raises(AssertionError):
            helpers._public_key_fingerprint(line(blob))
    with pytest.raises(AssertionError):
        helpers._public_key_fingerprint("ssh-rsa " + line(valid).split()[1])
    with pytest.raises(AssertionError):
        helpers._public_key_fingerprint("ssh-ed25519 not-base64!")


def test_create_requires_post_get_and_complete_list_exact_key_proof(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; key = public_key(); obj = deploy_key(key=key)
    api = FakeKeys(listed=[[], [obj]], created=obj, readback=obj)
    assert helpers.create_deploy_key(api, obj["title"], key, repo="o/r", marker=marker, evidence_root=root) == 7
    assert json.loads(marker.read_text())["fingerprint"] == helpers._public_key_fingerprint(key)
    assert ("list",) in api.calls


@pytest.mark.parametrize("mutation", [
    lambda obj: {k: v for k, v in obj.items() if k != "key"},
    lambda obj: {**obj, "key": public_key(2)},
    lambda obj: {**obj, "read_only": False},
])
def test_create_missing_mismatched_or_non_strict_key_proof_retains_uncertainty(tmp_path: Path, mutation) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; key = public_key(); exact = deploy_key(key=key)
    api = FakeKeys(listed=[[], [exact]], created=mutation(exact), readback=exact)
    with pytest.raises(AssertionError):
        helpers.create_deploy_key(api, exact["title"], key, repo="o/r", marker=marker, evidence_root=root)
    assert not marker.exists() and marker.with_suffix(".json.uncertain").exists()


def test_create_rejects_duplicate_title_or_fingerprint_across_authoritative_list(tmp_path: Path) -> None:
    key = public_key(); exact = deploy_key(key=key)
    for duplicate in (deploy_key(8, exact["title"], public_key(2)), deploy_key(8, "other", key)):
        root = tmp_path / str(duplicate["id"]) / "evidence"
        marker = root / "owned.json"; api = FakeKeys(listed=[[], [exact, duplicate]], created=exact, readback=exact)
        with pytest.raises(AssertionError):
            helpers.create_deploy_key(api, exact["title"], key, repo="o/r", marker=marker, evidence_root=root)
        assert not marker.exists()


def test_github_deploy_key_list_paginates_until_short_page_and_fails_at_boundary(monkeypatch) -> None:
    api = helpers.GitHubDeployKeysAPI("o/r"); calls = []
    pages: list[object] = [[deploy_key(i + 1, f"key-{i}", public_key((i % 250) + 1)) for i in range(100)], [deploy_key(101, "target", public_key(251))]]
    def request(method, endpoint, fields=None):
        calls.append(endpoint); return 200, pages.pop(0)
    monkeypatch.setattr(api, "_request", request)
    assert len(api.list()) == 101
    assert calls == ["repos/o/r/keys?per_page=100&page=1", "repos/o/r/keys?per_page=100&page=2"]

    calls.clear(); pages[:] = [[deploy_key(i + 1, f"key-{i}", public_key((i % 250) + 1)) for i in range(100)], "bad"]
    with pytest.raises(helpers.APIError): api.list()
    assert calls[-1].endswith("page=2")


def test_github_deploy_key_list_complete_pagination_edges(monkeypatch) -> None:
    full = [deploy_key(i + 1, f"key-{i}", public_key((i % 250) + 1)) for i in range(100)]
    api = helpers.GitHubDeployKeysAPI("o/r")

    responses = [(200, full), (500, {"message": "boom"})]
    monkeypatch.setattr(api, "_request", lambda *_args: responses.pop(0))
    with pytest.raises(helpers.APIError):
        api.list()

    responses = [(200, full), (200, [])]
    monkeypatch.setattr(api, "_request", lambda *_args: responses.pop(0))
    assert len(api.list()) == 100 and not responses

    api.MAX_LIST_PAGES = 2
    responses = [(200, full), (200, full)]
    monkeypatch.setattr(api, "_request", lambda *_args: responses.pop(0))
    with pytest.raises(helpers.APIError, match="safety bound"):
        api.list()


def test_duplicate_identity_split_across_pages_blocks_cleanup_and_retains_marker(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; key = public_key(); exact = deploy_key(key=key)
    root.mkdir(mode=0o700)
    helpers._create_json_marker_exclusive(marker, {
        "state": "owned", "repo": "o/r", "title": exact["title"], "key_id": 7,
        "fingerprint": helpers._public_key_fingerprint(key)}, evidence_root=root)
    api = helpers.GitHubDeployKeysAPI("o/r")
    full = [exact] + [deploy_key(i + 20, f"other-{i}", public_key((i % 250) + 2)) for i in range(99)]
    responses = [(200, exact), (200, full), (200, [deploy_key(999, "duplicate", key)])]
    monkeypatch.setattr(api, "_request", lambda *_args: responses.pop(0))
    with pytest.raises(AssertionError, match="fingerprint is not unique"):
        helpers.cleanup_deploy_key_markers(api, repo="o/r", title=exact["title"], marker=marker, evidence_root=root)
    assert marker.exists()


def test_rejected_create_cleanup_never_deletes_preexisting_key_and_consumes_only_proved_absence(tmp_path: Path) -> None:
    key = public_key(); exact = deploy_key(key=key)
    for name, listed, consumed in (("present", [exact], False), ("absent", [], True)):
        root = tmp_path / name; marker = root / "owned.json"
        api = FakeKeys(listed=[[], listed], created=helpers.APIError(422, "validation failed"), readback=exact)
        with pytest.raises(helpers.APIError):
            helpers.create_deploy_key(api, exact["title"], key, repo="o/r", marker=marker, evidence_root=root)
        uncertain = marker.with_suffix(".json.uncertain")
        assert json.loads(uncertain.read_text())["state"] == "create-rejected"
        with (pytest.raises(AssertionError) if not consumed else nullcontext()):
            helpers.cleanup_deploy_key_markers(api, repo="o/r", title=exact["title"], marker=marker, evidence_root=root)
        assert uncertain.exists() is not consumed
        assert not any(call[0] == "delete" for call in api.calls)


def test_interrupted_rejected_state_transition_is_fail_closed_without_delete(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    key = public_key(); pending = {"state": "created-unverified", "repo": "o/r",
        "title": "kubecrate-qa-run", "fingerprint": helpers._public_key_fingerprint(key)}
    helpers._create_json_marker_exclusive(uncertain, pending, evidence_root=root)
    real_write = os.write; writes = 0
    def interrupted_write(fd, data):
        nonlocal writes
        writes += 1
        if writes == 1:
            return real_write(fd, data[:8])
        raise InterruptedError("simulated transition interruption")
    monkeypatch.setattr(helpers.os, "write", interrupted_write)
    with pytest.raises(InterruptedError):
        helpers._transition_json_marker_state(
            uncertain, evidence_root=root, expected=pending, new_state="create-rejected")
    monkeypatch.setattr(helpers.os, "write", real_write)
    api = FakeKeys(listed=[[deploy_key(key=key)]], readback=deploy_key(key=key))
    with pytest.raises(json.JSONDecodeError):
        helpers.cleanup_deploy_key_markers(
            api, repo="o/r", title=pending["title"], marker=marker, evidence_root=root)
    assert uncertain.exists() and not any(call[0] == "delete" for call in api.calls)


def prepare_public_key(root: Path, key: str) -> None:
    private = root / "private"; private.mkdir(parents=True, mode=0o700)
    root.chmod(0o700); private.chmod(0o700)
    path = private / "identity.pub"; path.write_text(key + "\n"); path.chmod(0o600)


def test_actual_deploy_key_cli_create_and_owned_cleanup_prove_exact_identity_without_key_leak(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; key = public_key(); obj = deploy_key(key=key)
    prepare_public_key(root, key)
    created = run_helper(tmp_path, [(200, "[]"), (201, json.dumps(obj)), (200, json.dumps(obj)),
                                    (200, json.dumps([obj]))],
                         "create-deploy-key", "--repo", "o/r", "--title", obj["title"],
                         "--evidence-root", str(root), "--marker", str(marker))
    assert created.returncode == 0, created.stderr
    log = (tmp_path / "gh.log").read_text()
    assert key not in created.stdout + created.stderr + log
    deleted = run_helper(tmp_path, [(200, json.dumps(obj)), (200, json.dumps([obj])),
                                    (204, ""), (404, '{"message":"Not Found"}'), (200, "[]")],
                         "cleanup-deploy-key-markers", "--repo", "o/r", "--title", obj["title"],
                         "--evidence-root", str(root), "--marker", str(marker))
    assert deleted.returncode == 0, deleted.stderr
    assert not marker.exists() and "-X DELETE repos/o/r/keys/7" in (tmp_path / "gh.log").read_text()


@pytest.mark.parametrize("listed,retained", [([], False), (None, True)])
def test_actual_deploy_key_cli_422_rejection_never_deletes(tmp_path: Path, listed, retained: bool) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; key = public_key(); obj = deploy_key(key=key)
    prepare_public_key(root, key)
    rejected = run_helper(tmp_path, [(200, "[]"), (422, '{"message":"validation failed"}')],
                          "create-deploy-key", "--repo", "o/r", "--title", obj["title"],
                          "--evidence-root", str(root), "--marker", str(marker))
    uncertain = marker.with_suffix(".json.uncertain")
    assert rejected.returncode != 0 and json.loads(uncertain.read_text())["state"] == "create-rejected"
    queue = [obj] if listed is None else listed
    cleaned = run_helper(tmp_path, [(200, json.dumps(queue))], "cleanup-deploy-key-markers",
                         "--repo", "o/r", "--title", obj["title"], "--evidence-root", str(root),
                         "--marker", str(marker))
    assert (cleaned.returncode != 0) is retained
    assert uncertain.exists() is retained
    assert "DELETE" not in (tmp_path / "gh.log").read_text()


def test_owned_cleanup_mismatch_or_ambiguous_list_never_deletes_and_retains_marker(tmp_path: Path) -> None:
    key = public_key(); exact = deploy_key(key=key)
    for name, readback, listed in (
        ("mismatch", deploy_key(key=public_key(2)), [exact]),
        ("duplicate", exact, [exact, deploy_key(8, "other", key)]),
    ):
        root = tmp_path / name; marker = root / "owned.json"; root.mkdir(mode=0o700)
        helpers._create_json_marker_exclusive(marker, {
            "state": "owned", "repo": "o/r", "title": exact["title"], "key_id": 7,
            "fingerprint": helpers._public_key_fingerprint(key)}, evidence_root=root)
        api = FakeKeys(listed=[listed], readback=readback)
        with pytest.raises(AssertionError):
            helpers.cleanup_deploy_key_markers(api, repo="o/r", title=exact["title"],
                                               marker=marker, evidence_root=root)
        assert marker.exists() and not any(call[0] == "delete" for call in api.calls)


@pytest.mark.parametrize("phase", ["during-post", "after-post"])
def test_actual_deploy_key_helper_interruption_retains_uncertainty_and_cleanup_never_deletes(
    tmp_path: Path, phase: str
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    key = public_key(); obj = deploy_key(key=key); prepare_public_key(root, key)
    bindir = tmp_path / "blocking-key-bin"; bindir.mkdir(); barrier = tmp_path / "barrier"; log = tmp_path / "key.log"
    gh = bindir / "gh"
    gh.write_text(f'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
log=pathlib.Path(os.environ["FAKE_GH_LOG"]); log.open("a").write(" ".join(sys.argv[1:])+"\\n")
endpoint=next(a for a in sys.argv if a.startswith("repos/")); method=sys.argv[sys.argv.index("-X")+1]
if method == "GET" and "?" in endpoint: print("[]"); raise SystemExit(0)
if ("{phase}" == "during-post" and method == "POST") or ("{phase}" == "after-post" and method == "GET" and endpoint.endswith("/7")):
 pathlib.Path(os.environ["FAKE_GH_BARRIER"]).write_text(method)
 while True: time.sleep(1)
print(json.dumps(json.loads({json.dumps(json.dumps(obj))})))
'''); gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(log),
           "FAKE_GH_BARRIER": str(barrier)}
    command = ["python3", HELPER_PATH, "create-deploy-key", "--repo", "o/r", "--title", obj["title"],
               "--evidence-root", str(root), "--marker", str(marker)]
    process = subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    deadline = time.monotonic() + 5
    while not barrier.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(.01)
    assert barrier.exists(), process.communicate(timeout=1)
    os.killpg(process.pid, signal.SIGTERM); process.communicate(timeout=5)
    assert process.returncode != 0 and uncertain.exists() and not marker.exists()
    assert key not in log.read_text()

    # A complete but ambiguous list retains the diagnostic and never deletes.
    cleanup_bin = fake_gh(tmp_path, [(200, json.dumps([obj, deploy_key(8, "other", key)]))], tmp_path / "cleanup.log")
    cleanup_env = {**os.environ, "PATH": f"{cleanup_bin}:{os.environ['PATH']}",
                   "FAKE_GH_QUEUE": str(tmp_path / "responses.json"), "FAKE_GH_LOG": str(tmp_path / "cleanup.log")}
    cleanup = subprocess.run(["python3", HELPER_PATH, "cleanup-deploy-key-markers", "--repo", "o/r",
                              "--title", obj["title"], "--evidence-root", str(root), "--marker", str(marker)],
                             env=cleanup_env, text=True, capture_output=True)
    assert cleanup.returncode != 0 and uncertain.exists()
    assert "DELETE" not in (tmp_path / "cleanup.log").read_text()


def test_deploy_key_create_readback_and_exact_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned-deploy-key.json"
    obj = deploy_key(); api = FakeKeys(listed=[[], [obj], [obj], []], created=obj, readback=obj)
    assert helpers.create_deploy_key(
        api, "kubecrate-qa-run", obj["key"], repo="o/r", marker=marker,
        evidence_root=root) == 7
    assert marker.exists() and not marker.with_suffix(".json.uncertain").exists()
    helpers.cleanup_deploy_key_markers(
        api, repo="o/r", title="kubecrate-qa-run", marker=marker, evidence_root=root)
    assert ("delete", 7) in api.calls and not marker.exists()


@pytest.mark.parametrize("bad", [None, [], {"id": "7"}, {"id": 7, "title": "wrong"}])
def test_malformed_deploy_key_create_retains_crash_cleanup_intent(tmp_path: Path, bad) -> None:
    root = tmp_path / "evidence"; marker = root / "owned-deploy-key.json"
    api = FakeKeys(created=bad)
    with pytest.raises(AssertionError):
        helpers.create_deploy_key(
            api, "kubecrate-qa-run", public_key(), repo="o/r",
            marker=marker, evidence_root=root)
    assert not marker.exists() and marker.with_suffix(".json.uncertain").exists()


def test_interrupt_after_deploy_key_create_recovers_unique_exact_key(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned-deploy-key.json"
    key = public_key(); obj = deploy_key(key=key)
    root.mkdir(mode=0o700)
    helpers._create_json_marker_exclusive(
        marker.with_suffix(".json.uncertain"),
        {"state": "created-unverified", "repo": "o/r", "title": "kubecrate-qa-run",
         "fingerprint": helpers._public_key_fingerprint(key)}, evidence_root=root)
    api = FakeKeys(listed=[[obj], []], readback=obj)
    helpers.cleanup_deploy_key_markers(
        api, repo="o/r", title="kubecrate-qa-run", marker=marker, evidence_root=root)
    assert ("delete", 7) in api.calls and not marker.with_suffix(".json.uncertain").exists()


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


def blocking_fake_gh(tmp_path: Path, phase: str, ref: str, sha: str) -> tuple[Path, Path, Path]:
    bindir = tmp_path / "blocking-bin"; bindir.mkdir()
    barrier = tmp_path / "gh-barrier"; log = tmp_path / "blocking-gh.log"; count = tmp_path / "gh-count"
    gh = bindir / "gh"
    gh.write_text(f'''#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
log = pathlib.Path(os.environ["FAKE_GH_LOG"])
with log.open("a") as stream:
    stream.write(" ".join(sys.argv[1:]) + "\\n")
count = pathlib.Path(os.environ["FAKE_GH_COUNT"])
n = int(count.read_text()) + 1 if count.exists() else 1
count.write_text(str(n))
method = sys.argv[sys.argv.index("-X") + 1]
if method == "GET" and n == 1:
    print('{{"message":"Not Found"}}')
    print("gh: request failed (HTTP 404)", file=sys.stderr)
    raise SystemExit(1)
if ("{phase}" == "during-post" and method == "POST") or ("{phase}" == "before-readback" and method == "GET" and n == 3):
    pathlib.Path(os.environ["FAKE_GH_BARRIER"]).write_text(method)
    while True: time.sleep(1)
print(json.dumps({{"ref":"{ref}","object":{{"type":"commit","sha":"{sha}"}}}}))
''')
    gh.chmod(0o755)
    return bindir, barrier, log


@pytest.mark.parametrize("phase,signum", [("during-post", signal.SIGTERM), ("before-readback", signal.SIGINT)])
def test_actual_helper_cli_interruption_retains_durable_uncertainty_and_cleanup_fails_closed(
    tmp_path: Path, phase: str, signum: signal.Signals
) -> None:
    ref = "refs/heads/qa"; sha = "a" * 40; root = tmp_path / "evidence"; marker = root / "owned.json"
    uncertain = marker.with_suffix(".json.uncertain"); bindir, barrier, log = blocking_fake_gh(tmp_path, phase, ref, sha)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_LOG": str(log),
           "FAKE_GH_COUNT": str(tmp_path / "gh-count"), "FAKE_GH_BARRIER": str(barrier)}
    command = ["python3", HELPER_PATH, "create-ref", "--repo", "o/r", "--ref", ref, "--sha", sha,
               "--evidence-root", str(root), "--marker", str(marker)]
    process = subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not barrier.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert barrier.exists(), process.communicate(timeout=1)
        assert json.loads(uncertain.read_text()) == {
            "repo": "o/r", "ref": ref, "sha": sha, "state": "created-unverified"}
        assert stat.S_IMODE(uncertain.stat().st_mode) == 0o600
        os.killpg(process.pid, signum)
        process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    assert process.returncode != 0 and uncertain.exists() and not marker.exists()
    before = uncertain.read_bytes(); inode = uncertain.stat().st_ino
    cleanup = subprocess.run([
        "python3", HELPER_PATH, "cleanup-ref-markers", "--repo", "o/r", "--ref", ref, "--sha", sha,
        "--evidence-root", str(root), "--owned-marker", str(marker), "--uncertain-marker", str(uncertain),
        "--branch-created", "false"], env=env, text=True, capture_output=True, timeout=5)
    assert cleanup.returncode != 0
    assert uncertain.read_bytes() == before and uncertain.stat().st_ino == inode
    calls = log.read_text()
    assert "-X DELETE" not in calls
    assert calls.count("-X GET") == (1 if phase == "during-post" else 2)


@pytest.mark.parametrize("entry,kind", [
    ("uncertain", "same"), ("uncertain", "mismatch"), ("owned", "same"),
    ("uncertain", "malformed"), ("uncertain", "symlink"), ("owned", "wrong-mode"),
    ("owned", "directory"),
])
def test_create_cli_refuses_existing_evidence_without_api_or_overwrite(
    tmp_path: Path, entry: str, kind: str
) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700); owned = root / "owned.json"
    uncertain = owned.with_suffix(".json.uncertain"); target = uncertain if entry == "uncertain" else owned
    payload = {"repo": "o/r", "ref": "refs/heads/qa", "sha": "a" * 40,
               "state": "created-unverified" if entry == "uncertain" else "owned"}
    if kind == "mismatch": payload["sha"] = "b" * 40
    if kind == "malformed": target.write_text("{not-json"); target.chmod(0o600)
    elif kind == "symlink": target.symlink_to(tmp_path / "victim")
    elif kind == "wrong-mode": target.write_text(json.dumps(payload)); target.chmod(0o644)
    elif kind == "directory": target.mkdir(mode=0o700)
    else: target.write_text(json.dumps(payload)); target.chmod(0o600)
    before = os.lstat(target)
    content = None if target.is_dir() else (target.read_bytes() if not target.is_symlink() else os.readlink(target))
    responses = [(404, '{"message":"Not Found"}'),
                 (201, ref_obj("refs/heads/qa", "a" * 40)),
                 (200, ref_obj("refs/heads/qa", "a" * 40))]
    result = run_helper(tmp_path, responses, "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa",
                        "--sha", "a" * 40, "--evidence-root", str(root), "--marker", str(owned))
    after = os.lstat(target)
    assert result.returncode != 0 and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    after_content = None if target.is_dir() else (target.read_bytes() if not target.is_symlink() else os.readlink(target))
    assert after_content == content
    assert not (tmp_path / "gh.log").exists()


def test_exclusive_marker_publish_loses_race_without_overwrite(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json.uncertain"; raced = b"racing evidence\n"
    real_link_fd = helpers._link_fd

    def race_link(fd, directory_fd, name):
        raced_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                           dir_fd=directory_fd)
        os.write(raced_fd, raced); os.fsync(raced_fd); os.close(raced_fd)
        return real_link_fd(fd, directory_fd, name)

    monkeypatch.setattr(helpers, "_link_fd", race_link)
    with pytest.raises(FileExistsError):
        helpers._create_marker_exclusive(
            marker, "o/r", "refs/heads/qa", "a" * 40, "created-unverified", evidence_root=root)
    assert marker.read_bytes() == raced


def test_exclusive_marker_eexist_race_prevents_api_post_and_preserves_destination(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"
    uncertain = marker.with_suffix(".json.uncertain"); raced = b"racing evidence\n"
    real_link_fd = helpers._link_fd; raced_identity = []

    def race_link(fd, directory_fd, name):
        raced_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                           dir_fd=directory_fd)
        os.write(raced_fd, raced); os.fsync(raced_fd)
        raced_identity.append(os.fstat(raced_fd).st_ino)
        os.close(raced_fd)
        return real_link_fd(fd, directory_fd, name)

    monkeypatch.setattr(helpers, "_link_fd", race_link)
    api = FakeRefs([None], create=AssertionError("POST must not run"))
    with pytest.raises(FileExistsError):
        helpers.create_owned_ref(
            api, "refs/heads/qa", "a" * 40, repo="o/r", marker=marker,
            evidence_root=root)
    assert not any(call[0] == "create" for call in api.calls)
    assert uncertain.read_bytes() == raced
    assert uncertain.stat().st_ino == raced_identity[0]


def test_exclusive_marker_forces_mode_0600_under_hostile_umask(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; root.mkdir(mode=0o700)
    marker = root / "owned.json.uncertain"
    previous = os.umask(0o777)
    try:
        helpers._create_marker_exclusive(
            marker, "o/r", "refs/heads/qa", "a" * 40, "created-unverified", evidence_root=root)
    finally:
        os.umask(previous)
    info = os.lstat(marker)
    assert stat.S_ISREG(info.st_mode)
    assert info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1
    assert json.loads(marker.read_text()) == {
        "repo": "o/r", "ref": "refs/heads/qa", "sha": "a" * 40,
        "state": "created-unverified",
    }


def test_anonymous_marker_link_failure_closes_fd_and_leaves_no_entry(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json.uncertain"; captured = []

    def fail_link(fd, _directory_fd, _name):
        captured.append(fd)
        raise OSError(95, "linkat unavailable")

    monkeypatch.setattr(helpers, "_link_fd", fail_link)
    with pytest.raises(OSError, match="linkat unavailable"):
        helpers._create_marker_exclusive(
            marker, "o/r", "refs/heads/qa", "a" * 40, "created-unverified",
            evidence_root=root)
    assert not marker.exists()
    with pytest.raises(OSError):
        os.fstat(captured[0])


def test_anonymous_marker_open_failure_is_clear_and_fail_closed(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json.uncertain"
    real_open = helpers.os.open

    def reject_tmpfile(path, flags, *args, **kwargs):
        tmpfile = getattr(os, "O_TMPFILE", 0)
        if path == "." and tmpfile and flags & tmpfile == tmpfile and "dir_fd" in kwargs:
            raise OSError(95, "operation not supported")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(helpers.os, "open", reject_tmpfile)
    with pytest.raises(RuntimeError, match="anonymous O_TMPFILE marker creation unavailable"):
        helpers._create_marker_exclusive(
            marker, "o/r", "refs/heads/qa", "a" * 40, "created-unverified",
            evidence_root=root)
    assert not marker.exists()


def _anonymous_fd(root: Path) -> tuple[int, int]:
    root.mkdir(mode=0o700, exist_ok=True)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o600,
                 dir_fd=directory_fd)
    os.fchmod(fd, 0o600)
    return fd, directory_fd


def _force_proc_fallback(monkeypatch):
    real_linkat = helpers._LINKAT
    calls = []

    def linkat(source_fd, source, destination_fd, destination, flags):
        calls.append((source_fd, source, destination_fd, destination, flags))
        if flags == helpers._AT_EMPTY_PATH:
            ctypes.set_errno(errno.ENOENT)
            return -1
        return real_linkat(source_fd, source, destination_fd, destination, flags)

    monkeypatch.setattr(helpers, "_LINKAT", linkat)
    return calls


def test_proc_fallback_rejects_non_procfs_magic_before_link(monkeypatch, tmp_path: Path) -> None:
    fd, directory_fd = _anonymous_fd(tmp_path / "evidence")
    calls = _force_proc_fallback(monkeypatch)
    monkeypatch.setattr(helpers, "_fstatfs_magic", lambda _fd: 0xEF53)
    try:
        with pytest.raises(RuntimeError, match="procfs filesystem magic"):
            helpers._link_fd(fd, directory_fd, "marker")
        assert len(calls) == 1
        assert not (tmp_path / "evidence" / "marker").exists()
    finally:
        os.close(fd); os.close(directory_fd)


def test_proc_fallback_rejects_numeric_entry_that_is_not_magic_symlink(
    monkeypatch, tmp_path: Path
) -> None:
    fd, directory_fd = _anonymous_fd(tmp_path / "evidence")
    calls = _force_proc_fallback(monkeypatch)
    real_source = helpers._proc_source_info

    def regular_source(proc_fd, source):
        entry, target, followed = real_source(proc_fd, source)
        values = list(entry); values[0] = stat.S_IFREG | 0o600
        return os.stat_result(values), target, followed

    monkeypatch.setattr(helpers, "_proc_source_info", regular_source)
    try:
        with pytest.raises(RuntimeError, match="magic symlink"):
            helpers._link_fd(fd, directory_fd, "marker")
        assert len(calls) == 1
        assert not (tmp_path / "evidence" / "marker").exists()
    finally:
        os.close(fd); os.close(directory_fd)


def test_proc_fallback_rechecks_source_identity_immediately_before_link(
    monkeypatch, tmp_path: Path
) -> None:
    fd, directory_fd = _anonymous_fd(tmp_path / "evidence")
    calls = _force_proc_fallback(monkeypatch)
    real_source = helpers._proc_source_info; observations = 0

    def substitute_before_link(proc_fd, source):
        nonlocal observations
        observations += 1
        entry, target, followed = real_source(proc_fd, source)
        if observations == 2:
            values = list(followed); values[1] += 1
            followed = os.stat_result(values)
        return entry, target, followed

    monkeypatch.setattr(helpers, "_proc_source_info", substitute_before_link)
    try:
        with pytest.raises(AssertionError, match="inode identity"):
            helpers._link_fd(fd, directory_fd, "marker")
        assert len(calls) == 1
        assert not (tmp_path / "evidence" / "marker").exists()
    finally:
        os.close(fd); os.close(directory_fd)


@pytest.mark.parametrize("repoint_observation", [3, 4])
def test_proc_fallback_source_repoint_after_publication_fails_closed_and_retains_final(
    monkeypatch, tmp_path: Path, repoint_observation: int
) -> None:
    fd, directory_fd = _anonymous_fd(tmp_path / "evidence")
    calls = _force_proc_fallback(monkeypatch)
    real_source = helpers._proc_source_info; observations = 0

    def repoint_source(proc_fd, source):
        nonlocal observations
        observations += 1
        entry, target, followed = real_source(proc_fd, source)
        if observations == repoint_observation:
            values = list(followed); values[1] += 1
            followed = os.stat_result(values)
        return entry, target, followed

    monkeypatch.setattr(helpers, "_proc_source_info", repoint_source)
    try:
        with pytest.raises(AssertionError, match="inode identity"):
            helpers._link_fd(fd, directory_fd, "marker")
        assert len(calls) == 2
        final = os.lstat(tmp_path / "evidence" / "marker")
        assert (final.st_dev, final.st_ino) == (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
    finally:
        os.close(fd); os.close(directory_fd)


def test_direct_empty_path_success_bypasses_proc_fallback(monkeypatch, tmp_path: Path) -> None:
    fd, directory_fd = _anonymous_fd(tmp_path / "evidence")
    calls = []

    def direct_link(source_fd, source, destination_fd, destination, flags):
        calls.append(flags)
        return 0

    monkeypatch.setattr(helpers, "_LINKAT", direct_link)
    monkeypatch.setattr(helpers, "_fstatfs_magic",
                        lambda _fd: pytest.fail("procfs fallback was entered"))
    try:
        helpers._link_fd(fd, directory_fd, "marker")
        assert calls == [helpers._AT_EMPTY_PATH]
    finally:
        os.close(fd); os.close(directory_fd)


def test_extra_hard_link_during_publish_fails_without_post_and_retains_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"
    uncertain = marker.with_suffix(".json.uncertain"); extra = root / "attacker-link"
    real_link_fd = helpers._link_fd

    def add_link(fd, directory_fd, name):
        result = real_link_fd(fd, directory_fd, name)
        os.link(name, extra.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False)
        return result

    monkeypatch.setattr(helpers, "_link_fd", add_link)
    api = FakeRefs([None], create=AssertionError("POST must not run"))
    with pytest.raises(AssertionError, match="link count"):
        helpers.create_owned_ref(
            api, "refs/heads/qa", "a" * 40, repo="o/r", marker=marker,
            evidence_root=root)
    assert not any(call[0] == "create" for call in api.calls)
    assert uncertain.exists() and extra.exists()
    assert os.lstat(uncertain).st_ino == os.lstat(extra).st_ino
    assert os.lstat(uncertain).st_nlink == 2


def test_final_substitution_after_link_fails_without_post_or_touching_attacker_entry(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"
    uncertain = marker.with_suffix(".json.uncertain"); attacker = b"attacker destination\n"
    real_link_fd = helpers._link_fd

    def substitute_final(fd, directory_fd, name):
        result = real_link_fd(fd, directory_fd, name)
        os.unlink(name, dir_fd=directory_fd)
        attacker_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                              dir_fd=directory_fd)
        os.write(attacker_fd, attacker); os.close(attacker_fd)
        return result

    monkeypatch.setattr(helpers, "_link_fd", substitute_final)
    api = FakeRefs([None], create=AssertionError("POST must not run"))
    with pytest.raises(AssertionError):
        helpers.create_owned_ref(
            api, "refs/heads/qa", "a" * 40, repo="o/r", marker=marker,
            evidence_root=root)
    assert not any(call[0] == "create" for call in api.calls)
    assert uncertain.read_bytes() == attacker


def test_final_substitution_between_verifications_is_retained_and_never_unlinked(
    monkeypatch, tmp_path: Path
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json.uncertain"
    attacker = b"late attacker destination\n"; real_entry_info = helpers._entry_info
    final_reads = 0; unlinks_after_substitution = []
    real_unlink = helpers.os.unlink

    def substitute_on_second_observation(name, directory_fd):
        nonlocal final_reads
        if name == marker.name:
            final_reads += 1
            if final_reads == 2:
                real_unlink(name, dir_fd=directory_fd)
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                             dir_fd=directory_fd)
                os.write(fd, attacker); os.close(fd)
        return real_entry_info(name, directory_fd)

    def record_unlink(*args, **kwargs):
        unlinks_after_substitution.append((args, kwargs))
        return real_unlink(*args, **kwargs)

    monkeypatch.setattr(helpers, "_entry_info", substitute_on_second_observation)
    monkeypatch.setattr(helpers.os, "unlink", record_unlink)
    with pytest.raises(AssertionError, match="link count|inode identity"):
        helpers._create_marker_exclusive(
            marker, "o/r", "refs/heads/qa", "a" * 40, "created-unverified",
            evidence_root=root)
    assert marker.read_bytes() == attacker
    assert unlinks_after_substitution == []


def test_exclusive_publication_never_calls_pathname_unlink(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json.uncertain"
    monkeypatch.setattr(helpers.os, "unlink", lambda *a, **kw: pytest.fail("pathname unlink used"))
    helpers._create_marker_exclusive(
        marker, "o/r", "refs/heads/qa", "a" * 40, "created-unverified",
        evidence_root=root)
    assert marker.exists()


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
    # Every attempted POST is durably uncertain unless exact POST evidence and
    # authoritative GET jointly establish ownership.
    if len(responses) > 1:
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


@pytest.mark.parametrize("post_body", [
    ref_obj("refs/heads/other", "a" * 40),
    "[]",
    '"scalar"',
    "not-json",
])
def test_helper_cli_bad_nonempty_create_evidence_still_reads_back_but_never_owns(
    tmp_path: Path, post_body: str
) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    exact = ref_obj("refs/heads/qa", "a" * 40)
    result = run_helper(
        tmp_path,
        [(404, '{"message":"Not Found"}'), (201, post_body), (200, exact)],
        "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40,
        "--evidence-root", str(root), "--marker", str(marker),
    )
    assert result.returncode != 0 and not marker.exists() and uncertain.exists()
    log = (tmp_path / "gh.log").read_text()
    assert log.count("-X GET") == 2 and "-X DELETE" not in log


def test_exact_create_object_and_exact_readback_establish_ownership(tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; uncertain = marker.with_suffix(".json.uncertain")
    exact = ref_obj("refs/heads/qa", "a" * 40)
    result = run_helper(
        tmp_path, [(404, '{"message":"Not Found"}'), (201, exact), (200, exact)],
        "create-ref", "--repo", "o/r", "--ref", "refs/heads/qa", "--sha", "a" * 40,
        "--evidence-root", str(root), "--marker", str(marker),
    )
    assert result.returncode == 0 and marker.exists() and not uncertain.exists()
    assert (tmp_path / "gh.log").read_text().count("-X GET") == 2


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


def test_marker_publish_and_unlink_fsync_file_and_parent(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evidence"; marker = root / "owned.json"; events = []
    real_fsync, real_unlink = helpers.os.fsync, helpers.os.unlink
    monkeypatch.setattr(helpers.os, "fsync", lambda fd: (events.append(("fsync", stat.S_ISDIR(os.fstat(fd).st_mode))), real_fsync(fd))[1])
    monkeypatch.setattr(helpers.os, "unlink", lambda *a, **kw: (events.append(("unlink", False)), real_unlink(*a, **kw))[1])
    helpers._create_marker_exclusive(marker, "o/r", "refs/heads/qa", "a"*40, "owned", evidence_root=root)
    assert events[0] == ("fsync", False)
    assert events[1:] and all(event == ("fsync", True) for event in events[1:])
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


def test_production_cleanup_trap_deletes_created_key_after_sync_wait_failure(tmp_path: Path) -> None:
    repo = tmp_path / "sync-failure"; (repo / "scripts").mkdir(parents=True)
    shutil.copy2(LIFECYCLE, repo / "scripts/final-qa-lifecycle.sh")
    shutil.copy2(HELPER_PATH, repo / "scripts/final_qa_helpers.py")
    key = public_key(); obj = deploy_key(key=key); encoded = base64.b64encode(key.encode()).decode()
    runner = repo / "runner.sh"
    runner.write_text('''#!/usr/bin/env bash
set -Eeuo pipefail
REPO=o/r; QA_BRANCH=kubecrate-qa/test; CANDIDATE_SHA="$CANDIDATE_SHA"; CLUSTER=kubecrate-qa-test; CONTEXT=kind-kubecrate-qa-test
EVIDENCE="$EVIDENCE"; OWNED_REF_MARKER="$EVIDENCE/owned-ref.json"; UNCERTAIN_REF_MARKER="$OWNED_REF_MARKER.uncertain"
OWNED_KEY_MARKER="$EVIDENCE/owned-deploy-key.json"; KEY_TITLE=kubecrate-qa-run; KEY_ID=; PORT_FORWARD_PID=
BRANCH_CREATED=false; CLUSTER_CREATED=true; INITIAL_TREE="$(git write-tree)"; RED_STATE=none; EVIDENCE_READY=false
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
assert_context() { test "$(kubectl config current-context)" = "$CONTEXT"; }
source scripts/final-qa-lifecycle.sh
python3 scripts/final_qa_helpers.py prepare-evidence --evidence-root "$EVIDENCE"; EVIDENCE_READY=true
install_cleanup_traps
python3 scripts/final_qa_helpers.py create-ref --repo "$REPO" --ref "refs/heads/$QA_BRANCH" --sha "$CANDIDATE_SHA" --evidence-root "$EVIDENCE" --marker "$OWNED_REF_MARKER"
BRANCH_CREATED=true
assert_context
kubectl --context "$CONTEXT" get secret flux-system -n flux-system -o jsonpath='{.data.identity\\.pub}' |
  python3 scripts/final_qa_helpers.py write-public-key --evidence-root "$EVIDENCE"
KEY_ID="$(python3 scripts/final_qa_helpers.py create-deploy-key --repo "$REPO" --title "$KEY_TITLE" --evidence-root "$EVIDENCE" --marker "$OWNED_KEY_MARKER")"
python3 scripts/final_qa_helpers.py cleanup-private --evidence-root "$EVIDENCE"
kubectl --context "$CONTEXT" wait --for=condition=Ready helmrelease/flux-system-sync -n flux-system --timeout=180s
'''); runner.chmod(0o755)
    init_repo(repo, "sync lifecycle")
    subprocess.run(["git", "-C", repo, "add", "scripts", "runner.sh"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "--amend", "-qm", "sync lifecycle"], check=True)
    sha = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    evidence = tmp_path / "sync-evidence"; log = tmp_path / "sync.log"; deleted = tmp_path / "cluster-deleted"
    ref_json = ref_obj("refs/heads/kubecrate-qa/test", sha)
    bindir = fake_gh(tmp_path, [(404, '{"message":"Not Found"}'), (201, ref_json), (200, ref_json),
        (200, "[]"), (201, json.dumps(obj)), (200, json.dumps(obj)),
        (200, json.dumps([obj])), (200, json.dumps(obj)), (200, json.dumps([obj])), (204, ""),
        (404, '{"message":"Not Found"}'), (200, "[]"), (200, ref_json), (204, ""),
        (404, '{"message":"Not Found"}')], tmp_path / "gh.log")
    for name in ("kubectl", "kind"):
        path = bindir / name
        path.write_text(f'''#!/usr/bin/env bash
echo "{name} $*" >>"$CALL_LOG"
if [[ "{name}" == kubectl && "$*" == *"config current-context"* ]]; then echo kind-kubecrate-qa-test
elif [[ "{name}" == kubectl && "$*" == *"get secret flux-system"* ]]; then echo "$PUBLIC_KEY_B64"
elif [[ "{name}" == kubectl && "$*" == *"wait --for=condition=Ready helmrelease/flux-system-sync"* ]]; then exit 23
elif [[ "{name}" == kind && "$*" == "get clusters" ]]; then test -f "$CLUSTER_DELETED" || echo kubecrate-qa-test
elif [[ "{name}" == kind && "$*" == *"delete cluster"* ]]; then touch "$CLUSTER_DELETED"
fi
'''); path.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_GH_QUEUE": str(tmp_path / "responses.json"),
           "FAKE_GH_LOG": str(tmp_path / "gh.log"), "CALL_LOG": str(log), "PUBLIC_KEY_B64": encoded,
           "CLUSTER_DELETED": str(deleted), "CANDIDATE_SHA": sha, "EVIDENCE": str(evidence)}
    result = subprocess.run([runner], cwd=repo, env=env, text=True, capture_output=True)
    gh_calls = (tmp_path / "gh.log").read_text(); local_calls = log.read_text()
    assert result.returncode == 23, result.stderr
    assert "-X POST repos/o/r/keys" in gh_calls and "-X DELETE repos/o/r/keys/7" in gh_calls
    assert gh_calls.index("-X DELETE repos/o/r/keys/7") < gh_calls.index("-X DELETE repos/o/r/git/refs/heads/kubecrate-qa/test")
    assert local_calls.index("wait --for=condition=Ready helmrelease/flux-system-sync") < local_calls.index("kind delete cluster")
    assert not (evidence / "owned-deploy-key.json").exists()
    assert not (evidence / "owned-deploy-key.json.uncertain").exists()
    assert not (evidence / "owned-ref.json").exists()
    assert not (evidence / "private").exists() and deleted.exists()


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
