#!/usr/bin/env python3
"""Regression tests for Flux deploy-key preflight.

Covers the behavioural contract required by code-review: success, disabled
existing keys, HTTP 422 org-policy denial, auth/API errors, and malformed
output.  All tests use a deterministic mock gh runner — no network or real
GitHub calls.

The mock runner returns subprocess.CompletedProcess objects matching real
gh CLI output shapes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Import the module-under-test's functions.
# Python cannot directly import a module with hyphens in the filename,
# so we use importlib.
import importlib.util

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_PATH = REPO_ROOT / "scripts" / "preflight-flux-deploy-key.py"
_spec = importlib.util.spec_from_file_location(
    "preflight_flux_deploy_key", str(_MODULE_PATH)
)
assert _spec is not None, f"could not load {_MODULE_PATH}"
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)


# ---------------------------------------------------------------------------
# mock helpers
# ---------------------------------------------------------------------------


def _cp(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess matching real gh CLI output shapes."""
    return subprocess.CompletedProcess(
        args=["gh", "mock"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_auth_success() -> None:
    """gh auth status exits 0 → check_auth returns True."""
    gh = lambda args, **kw: _cp(returncode=0)
    assert pf.check_auth(gh) is True


def test_auth_failure() -> None:
    """gh auth status exits non-zero → check_auth returns False."""
    gh = lambda args, **kw: _cp(returncode=1, stderr="not logged in")
    assert pf.check_auth(gh) is False


def test_list_keys_empty() -> None:
    """No existing deploy keys → empty list."""
    gh = lambda args, **kw: _cp(stdout="[]")
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys == []


def test_list_keys_with_enabled_keys() -> None:
    """Existing enabled keys → returned as-is."""
    payload = [
        {"id": 1, "title": "qa-key", "enabled": True, "read_only": True},
        {"id": 2, "title": "ci-key", "enabled": True, "read_only": True},
    ]
    gh = lambda args, **kw: _cp(stdout=json.dumps(payload))
    keys = pf.list_deploy_keys("org/repo", gh)
    assert len(keys) == 2
    assert all(k["enabled"] for k in keys)


def test_list_keys_malformed_json() -> None:
    """Malformed JSON → None, no crash."""
    gh = lambda args, **kw: _cp(stdout="not json")
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys is None


def test_list_keys_api_error() -> None:
    """gh api exits non-zero → None, no crash."""
    gh = lambda args, **kw: _cp(returncode=1, stderr="Bad credentials")
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys is None


def test_list_keys_non_list_json() -> None:
    """JSON that isn't a list (e.g. dict) → None, no crash."""
    gh = lambda args, **kw: _cp(stdout=json.dumps({"error": "not a list"}))
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys is None


def test_list_keys_non_object_entry() -> None:
    """List entry that is not a dict → None (schema failure)."""
    gh = lambda args, **kw: _cp(stdout=json.dumps(["not-an-object"]))
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys is None


def test_list_keys_missing_enabled_field() -> None:
    """Dict entry without 'enabled' field → None (schema failure)."""
    gh = lambda args, **kw: _cp(
        stdout=json.dumps([{"id": 123, "title": "no-enabled"}])
    )
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys is None


def test_list_keys_non_boolean_enabled() -> None:
    """Dict entry with non-boolean 'enabled' → None (schema failure)."""
    gh = lambda args, **kw: _cp(
        stdout=json.dumps([{"id": 123, "enabled": "yes"}])
    )
    keys = pf.list_deploy_keys("org/repo", gh)
    assert keys is None


# ---------------------------------------------------------------------------
# disabled keys
# ---------------------------------------------------------------------------


def test_disabled_keys_none() -> None:
    """All keys enabled → returns 0."""
    keys = [{"id": 1, "enabled": True}]
    assert pf.check_disabled_keys(keys, "org/repo") == 0


def test_disabled_keys_some() -> None:
    """Some keys disabled → returns count of disabled."""
    keys = [
        {"id": 1, "title": "a", "enabled": True},
        {"id": 2, "title": "b", "enabled": False},
        {"id": 3, "title": "c", "enabled": False},
    ]
    assert pf.check_disabled_keys(keys, "org/repo") == 2


def test_disabled_keys_all() -> None:
    """All keys disabled → returns count."""
    keys = [
        {"id": 1, "title": "x", "enabled": False},
        {"id": 2, "title": "y", "enabled": False},
    ]
    assert pf.check_disabled_keys(keys, "org/repo") == 2


def test_disabled_keys_missing_enabled_field() -> None:
    """Keys without 'enabled' field are not counted as disabled."""
    keys = [{"id": 1, "title": "no-enabled-field"}]
    assert pf.check_disabled_keys(keys, "org/repo") == 0


# ---------------------------------------------------------------------------
# disposable create/read/delete capability probe
# ---------------------------------------------------------------------------


def _valid_key() -> str:
    return "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockedValidDisposableKeyMaterial preflight"


def _probe_gh(*responses):
    calls = []
    queue = list(responses)

    def gh(args, **kw):
        calls.append(tuple(args))
        assert queue, f"unexpected gh call: {args}"
        return queue.pop(0)

    return gh, calls


def _created(**overrides):
    body = {
        "id": 123,
        "title": "kubecrate-deploy-key-preflight",
        "read_only": True,
        "verified": True,
        "enabled": True,
    }
    body.update(overrides)
    return body


def test_lifecycle_probe_successful_create_read_delete() -> None:
    gh, calls = _probe_gh(
        _cp(stdout=json.dumps(_created())),
        _cp(stdout=json.dumps(_created())),
        _cp(),
        _cp(returncode=1, stderr="HTTP 404: Not Found"),
    )
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is False
    assert "create/read/delete" in detail
    assert any("repos/org/repo/keys/123" in call for call in calls)


@pytest.mark.parametrize("field", ["read_only", "verified", "enabled"])
def test_lifecycle_probe_rejects_false_metadata_and_cleans_up(field) -> None:
    gh, calls = _probe_gh(
        _cp(stdout=json.dumps(_created())),
        _cp(stdout=json.dumps(_created(**{field: False}))),
        _cp(),
        _cp(returncode=1, stderr="HTTP 404: Not Found"),
    )
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert field in detail
    assert any("DELETE" in call for call in calls)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 123, "title": "kubecrate-deploy-key-preflight", "verified": True, "enabled": True},
        _created(read_only="true"),
        _created(verified=1),
        _created(enabled="yes"),
        _created(id="123"),
        _created(title="wrong-key"),
    ],
)
def test_lifecycle_probe_rejects_missing_wrongly_typed_or_wrong_identity(payload) -> None:
    gh, calls = _probe_gh(
        _cp(stdout=json.dumps(_created())),
        _cp(stdout=json.dumps(payload)),
        _cp(),
        _cp(returncode=1, stderr="HTTP 404: Not Found"),
    )
    blocked, _ = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert any("DELETE" in call for call in calls)


def test_lifecycle_probe_rejects_arbitrary_422() -> None:
    gh, calls = _probe_gh(_cp(returncode=1, stderr="HTTP 422: Validation Failed"))
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert "422" in detail
    assert not any("DELETE" in call for call in calls)


def test_lifecycle_probe_rejects_malformed_create_response() -> None:
    gh, _ = _probe_gh(_cp(stdout="not-json"))
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert "malformed" in detail


def test_lifecycle_probe_create_failure() -> None:
    gh, calls = _probe_gh(_cp(returncode=1, stderr="HTTP 500"))
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert "creation failed" in detail
    assert not any("DELETE" in call for call in calls)


def test_lifecycle_probe_delete_failure() -> None:
    gh, _ = _probe_gh(
        _cp(stdout=json.dumps(_created())),
        _cp(stdout=json.dumps(_created())),
        _cp(returncode=1, stderr="HTTP 500"),
    )
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert "cleanup deletion failed" in detail


def test_lifecycle_probe_post_delete_key_still_present() -> None:
    gh, _ = _probe_gh(
        _cp(stdout=json.dumps(_created())),
        _cp(stdout=json.dumps(_created())),
        _cp(),
        _cp(stdout=json.dumps(_created())),
    )
    blocked, detail = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert "still present" in detail


def test_lifecycle_probe_cleanup_attempted_after_read_failure() -> None:
    gh, calls = _probe_gh(
        _cp(stdout=json.dumps(_created())),
        _cp(returncode=1, stderr="HTTP 503"),
        _cp(),
        _cp(returncode=1, stderr="HTTP 404: Not Found"),
    )
    blocked, _ = pf.check_deploy_key_lifecycle(
        "org/repo", gh, public_key_factory=_valid_key
    )
    assert blocked is True
    assert any("DELETE" in call for call in calls)


# ---------------------------------------------------------------------------
# full main() integration
# ---------------------------------------------------------------------------


def _main_gh(args, **kw):
    if args[:2] == ["auth", "status"]:
        return _cp()
    if args == ["api", "repos/42aei/kubecrate/keys", "--jq", "."]:
        return _cp(stdout="[]")
    if "POST" in args:
        return _cp(stdout=json.dumps(_created()))
    if "DELETE" in args:
        return _cp()
    if "repos/42aei/kubecrate/keys/123" in args:
        read_calls = getattr(_main_gh, "read_calls", 0)
        _main_gh.read_calls = read_calls + 1
        if read_calls == 0:
            return _cp(stdout=json.dumps(_created()))
        return _cp(returncode=1, stderr="HTTP 404: Not Found")
    raise AssertionError(args)


def test_main_all_clear(monkeypatch) -> None:
    monkeypatch.setattr(pf, "generate_disposable_public_key", _valid_key)
    _main_gh.read_calls = 0
    assert pf.main(_main_gh, argv=[]) == 0


def test_main_auth_fails(monkeypatch) -> None:
    monkeypatch.setattr(pf, "generate_disposable_public_key", _valid_key)

    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=1)
        return _main_gh(args, **kw)

    _main_gh.read_calls = 0
    assert pf.main(gh, argv=[]) != 0


def test_main_disabled_keys_blocker(monkeypatch) -> None:
    monkeypatch.setattr(pf, "generate_disposable_public_key", _valid_key)

    def gh(args, **kw):
        if args == ["api", "repos/42aei/kubecrate/keys", "--jq", "."]:
            return _cp(stdout=json.dumps([{"id": 1, "enabled": False}]))
        return _main_gh(args, **kw)

    _main_gh.read_calls = 0
    assert pf.main(gh, argv=[]) != 0


# ---------------------------------------------------------------------------
# main-level fail-closed regression tests (P1)
# ---------------------------------------------------------------------------


def test_main_list_keys_api_error() -> None:
    """list_deploy_keys API error → non-zero exit (fail closed)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        # Simulate API error on deploy-key list
        return _cp(returncode=1, stderr="Bad credentials")

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_list_keys_malformed_json() -> None:
    """list_deploy_keys returns malformed JSON → non-zero exit (fail closed)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout="not valid json {{{")

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_list_keys_unexpected_shape() -> None:
    """list_deploy_keys returns dict instead of list → non-zero exit (fail closed)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout=json.dumps({"message": "unexpected response"}))

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_list_keys_non_object_entry() -> None:
    """list_deploy_keys list entry is not an object → non-zero exit (fail closed)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout=json.dumps(["not-an-object"]))

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_list_keys_missing_enabled_field() -> None:
    """list_deploy_keys entry missing 'enabled' → non-zero exit (fail closed)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout=json.dumps([{"id": 123, "title": "no-enabled"}]))

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_list_keys_non_boolean_enabled() -> None:
    """list_deploy_keys entry 'enabled' not boolean → non-zero exit (fail closed)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout=json.dumps([{"id": 123, "enabled": "yes"}]))

    rc = pf.main(gh, argv=[])
    assert rc != 0


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# Makefile dependency ordering regression test (P1)
# ---------------------------------------------------------------------------


def test_makefile_ordering_preflight_before_create() -> None:
    """make -n kind-unique-create prints preflight before kind create cluster."""
    import subprocess as _sp

    result = _sp.run(
        ["make", "-n", "kind-unique-create"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    output = result.stdout

    preflight_idx = output.find("preflight-flux-deploy-key.py")
    create_idx = output.find("kind create cluster")

    assert preflight_idx != -1, (
        "preflight script not found in make -n output"
    )
    assert create_idx != -1, (
        "kind create cluster not found in make -n output"
    )
    assert preflight_idx < create_idx, (
        "preflight must appear before kind create cluster in make -n output, "
        f"but preflight at {preflight_idx} > create at {create_idx}"
    )
