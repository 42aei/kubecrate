#!/usr/bin/env python3
"""Behavioral tests for exact-tree final-QA safety helpers."""

import importlib.util
import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER_PATH = ROOT / "scripts" / "final_qa_helpers.py"
SCRIPT = ROOT / "scripts" / "final-qa-exact-tree.sh"

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
    assert suspend < text.index("RED_STATE=suspended", suspend) < delete
    assert delete < text.index("RED_STATE=source_deleted", delete)
    cleanup = text[text.index("cleanup()") : text.index("trap cleanup EXIT")]
    assert cleanup.index("restore_if_needed") < cleanup.index("kind delete cluster")


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
