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
# org-policy capability probe
# ---------------------------------------------------------------------------


def test_policy_allows_keys() -> None:
    """POST returns 422 with 'key is invalid' → org allows deploy keys."""
    gh = lambda args, **kw: _cp(
        returncode=1,
        stderr=(
            "HTTP 422: Validation Failed\n"
            "key is invalid. Please verify the public key and try again.\n"
        ),
    )
    blocked, detail = pf.check_org_deploy_key_policy("org/repo", gh)
    assert blocked is False
    assert "allows deploy-key creation" in detail


def test_policy_disallows_keys() -> None:
    """POST returns 422 with 'Deploy keys are not supported' → org blocks."""
    gh = lambda args, **kw: _cp(
        returncode=1,
        stderr=(
            "HTTP 422: Validation Failed\n"
            "Deploy keys are not supported for this organization. "
            "To enable deploy keys, an organization owner must enable "
            "them in the organization's member privileges.\n"
        ),
    )
    blocked, detail = pf.check_org_deploy_key_policy("42aei/kubecrate", gh)
    assert blocked is True
    assert "org-level deploy-key policy is OFF" in detail
    assert "organizations/42aei/settings/member_privileges" in detail


def test_policy_disallows_keys_stdout() -> None:
    """Policy-denial message in stdout (some gh versions put it there)."""
    gh = lambda args, **kw: _cp(
        returncode=1,
        stdout=(
            '{"message":"Deploy keys are not supported for this organization."}'
        ),
    )
    blocked, _ = pf.check_org_deploy_key_policy("org/repo", gh)
    assert blocked is True


def test_policy_combined_output() -> None:
    """Policy-denial message split across stdout + stderr."""
    gh = lambda args, **kw: _cp(
        returncode=1,
        stdout="HTTP/1.1 422 Unprocessable Entity\n",
        stderr=(
            '{"message":"Deploy keys are not supported for this '
            "organization.\"}\\n"
        ),
    )
    blocked, _ = pf.check_org_deploy_key_policy("org/repo", gh)
    assert blocked is True


def test_policy_api_auth_error() -> None:
    """Non-422 API error → blocked with unexpected-response message."""
    gh = lambda args, **kw: _cp(
        returncode=1,
        stderr="gh auth: bad credentials (HTTP 401)",
    )
    blocked, detail = pf.check_org_deploy_key_policy("org/repo", gh)
    assert blocked is True
    assert "unexpected response from deploy-key API" in detail


def test_policy_unexpected_success() -> None:
    """API returns 200/201 for an invalid key → blocked defensively."""
    gh = lambda args, **kw: _cp(
        returncode=0,
        stdout=json.dumps({"id": 999, "key": "...", "title": "preflight-policy-probe"}),
    )
    blocked, detail = pf.check_org_deploy_key_policy("org/repo", gh)
    assert blocked is True
    assert "unexpected success" in detail


# ---------------------------------------------------------------------------
# full main() integration
# ---------------------------------------------------------------------------


def test_main_all_clear() -> None:
    """Auth ok, no keys, policy allows → exit 0."""
    call_seq = []

    def gh(args, **kw):
        call_seq.append(tuple(args))
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(
                returncode=1,
                stderr="HTTP 422: key is invalid\n",
            )
        return _cp(stdout="[]")

    rc = pf.main(gh, argv=[])
    assert rc == 0


def test_main_auth_fails() -> None:
    """Auth fails → non-zero exit."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=1, stderr="not authenticated")
        return _cp(stdout="[]")

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_disabled_keys_blocker() -> None:
    """Existing disabled keys → non-zero exit."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout=json.dumps([
            {"id": 1, "title": "old", "enabled": False},
        ]))

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_policy_blocks() -> None:
    """Org policy blocks keys → non-zero exit."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(
                returncode=1,
                stderr="Deploy keys are not supported for this organization.",
            )
        return _cp(stdout="[]")

    rc = pf.main(gh, argv=[])
    assert rc != 0


def test_main_zero_keys_policy_allows() -> None:
    """Zero existing keys but org policy allows → exit 0 (not a false pass)."""
    def gh(args, **kw):
        if args[:2] == ["auth", "status"]:
            return _cp(returncode=0)
        if "POST" in args:
            return _cp(returncode=1, stderr="HTTP 422: key is invalid\n")
        return _cp(stdout="[]")

    rc = pf.main(gh, argv=[])
    assert rc == 0


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
