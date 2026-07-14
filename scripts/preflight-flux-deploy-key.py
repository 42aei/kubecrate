#!/usr/bin/env python3
"""Preflight: detect GitHub deploy-key blockers before Flux bootstrap.

This script runs before disposable-cluster creation. It checks whether the
target Git provider (GitHub) allows deploy-key registration for the configured
repository and whether any existing deploy keys are disabled.  It exits 0 when
the path is clear and non-zero when a blocker is detected.

It generates a temporary Ed25519 key pair, registers only its public key, and
performs a fail-closed create/read/delete/absence capability probe. Private key
material is confined to an automatically removed temporary directory and is
never printed.

Usage:
    python3 scripts/preflight-flux-deploy-key.py
    python3 scripts/preflight-flux-deploy-key.py --repo 42aei/kubecrate
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# gh runner abstraction — swappable for testing
# ---------------------------------------------------------------------------

GhRunner = Callable[..., subprocess.CompletedProcess[str]]


def _default_gh_runner(
    args: list[str], *, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Default gh CLI runner for production use."""
    return subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        input=stdin,
    )


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def check_auth(gh: GhRunner = _default_gh_runner) -> bool:
    """Return True if 'gh auth status' succeeds."""
    result = gh(["auth", "status"])
    return result.returncode == 0


def list_deploy_keys(
    repo: str, gh: GhRunner = _default_gh_runner
) -> list[dict[str, Any]] | None:
    """Return deploy keys for the given GitHub repository.

    Returns a list of key dicts on success (may be empty).  Returns None
    when key-list retrieval, JSON parsing, or response schema validation
    fails, so callers can distinguish a verified empty list from a
    retrieval/parse/schema failure.
    """
    result = gh(["api", f"repos/{repo}/keys", "--jq", "."])
    if result.returncode != 0:
        print(f"preflight: ERROR: could not list deploy keys for {repo}")
        print(f"preflight: stderr: {result.stderr.strip()}")
        return None
    try:
        keys = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"preflight: ERROR: deploy-key API returned non-JSON output")
        return None
    if not isinstance(keys, list):
        print(
            f"preflight: ERROR: deploy-key API returned unexpected type "
            f"{type(keys).__name__!r} (expected list)"
        )
        return None
    # Validate each entry: must be an object with a boolean "enabled" field.
    for i, entry in enumerate(keys):
        if not isinstance(entry, dict):
            print(
                f"preflight: ERROR: deploy-key entry {i} is not an object "
                f"(got {type(entry).__name__!r})"
            )
            return None
        if "enabled" not in entry:
            print(
                f"preflight: ERROR: deploy-key entry {i} missing required "
                f"'enabled' field"
            )
            return None
        if not isinstance(entry["enabled"], bool):
            print(
                f"preflight: ERROR: deploy-key entry {i} 'enabled' field "
                f"is not a boolean (got {type(entry['enabled']).__name__!r})"
            )
            return None
    return keys


def check_disabled_keys(
    keys: list[dict[str, Any]], repo: str
) -> int:
    """Check for disabled deploy keys. Returns count of disabled keys."""
    disabled = [k for k in keys if k.get("enabled") is False]
    if not disabled:
        return 0

    print(f"preflight: BLOCKER: {len(disabled)} disabled deploy key(s) on {repo}:")
    for k in disabled:
        print(
            f"  - id={k.get('id')} title={k.get('title')!r} "
            f"enabled={k.get('enabled')}"
        )
    print()
    print(
        "preflight: All deploy keys on this repository are disabled. "
        "This typically means the GitHub organization has deploy keys "
        "turned OFF under Member privileges."
    )
    print(
        "preflight: Settings page: "
        "https://github.com/organizations/<org>/settings/member_privileges"
    )
    print(
        "preflight: Fix: an org owner must enable the 'Deploy keys' setting, "
        "then re-enable the needed key(s)."
    )
    print("preflight: Docs: docs/flux-deploy-key-operator-guide.md")
    return len(disabled)


def generate_disposable_public_key() -> str:
    """Generate a valid public key while destroying private material on return."""
    with tempfile.TemporaryDirectory(prefix="kubecrate-deploy-key-preflight-") as tmp:
        key_path = Path(tmp) / "id_ed25519"
        result = subprocess.run(
            [
                "ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                "-C", "kubecrate-deploy-key-preflight", "-f", str(key_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("ssh-keygen failed while creating disposable probe key")
        return key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()


def _parse_object(result: subprocess.CompletedProcess[str], phase: str) -> dict[str, Any]:
    if result.returncode != 0:
        raise RuntimeError(
            f"{phase} failed (exit={result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"malformed {phase} response: expected JSON object") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"malformed {phase} response: expected JSON object")
    return payload


def _validate_probe_key(payload: dict[str, Any], key_id: int, title: str) -> None:
    if type(payload.get("id")) is not int or payload["id"] != key_id:
        raise RuntimeError("created key identity mismatch: id")
    if payload.get("title") != title:
        raise RuntimeError("created key identity mismatch: title")
    for field in ("read_only", "verified", "enabled"):
        if type(payload.get(field)) is not bool:
            raise RuntimeError(f"created key {field} is missing or not a boolean")
        if payload[field] is not True:
            raise RuntimeError(f"created key {field} is not true")


def check_deploy_key_lifecycle(
    repo: str,
    gh: GhRunner = _default_gh_runner,
    public_key_factory: Callable[[], str] | None = None,
) -> tuple[bool, str]:
    """Create, read, delete, and prove absence of one captured disposable key."""
    if public_key_factory is None:
        public_key_factory = generate_disposable_public_key
    title = "kubecrate-deploy-key-preflight"
    key_id: int | None = None
    deleted = False
    failure: str | None = None
    try:
        public_key = public_key_factory()
        created = _parse_object(
            gh([
                "api", f"repos/{repo}/keys", "-X", "POST",
                "-f", f"title={title}", "-f", f"key={public_key}",
                "-F", "read_only=true",
            ]),
            "deploy-key creation",
        )
        created_id = created.get("id")
        if type(created_id) is not int:
            raise RuntimeError("malformed deploy-key creation response: integer id required")
        key_id = created_id
        _validate_probe_key(created, key_id, title)

        read_back = _parse_object(
            gh(["api", f"repos/{repo}/keys/{key_id}"]), "deploy-key read"
        )
        _validate_probe_key(read_back, key_id, title)
    except (RuntimeError, OSError) as exc:
        failure = str(exc)
    finally:
        if key_id is not None:
            deletion = gh(["api", f"repos/{repo}/keys/{key_id}", "-X", "DELETE"])
            if deletion.returncode != 0:
                failure = (
                    f"cleanup deletion failed for captured key id {key_id}: "
                    f"{deletion.stderr.strip()[:300]}"
                )
            else:
                deleted = True

    if key_id is not None and deleted:
        absence = gh(["api", f"repos/{repo}/keys/{key_id}"])
        combined = absence.stdout + absence.stderr
        if absence.returncode == 0:
            failure = f"deleted key id {key_id} is still present"
        elif "404" not in combined and "Not Found" not in combined:
            failure = (
                f"could not verify absence of deleted key id {key_id}: "
                f"{combined.strip()[:300]}"
            )

    if failure is not None:
        return True, failure
    return False, "disposable deploy-key create/read/delete/absence probe passed"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(gh: GhRunner = _default_gh_runner, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight check for Flux deploy-key readiness"
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("KUBECRATE_GIT_REPO", "42aei/kubecrate"),
        help="GitHub repository in owner/repo format",
    )
    args = parser.parse_args(argv)

    repo = args.repo
    blockers = 0
    org = repo.split("/")[0] if "/" in repo else repo

    print(f"preflight: checking deploy-key readiness for {repo}")

    # 1. Verify gh is authenticated
    if not check_auth(gh):
        print("preflight: BLOCKER: gh CLI is not authenticated.")
        print("preflight: Run 'gh auth login' or set GH_TOKEN.")
        blockers += 1
    else:
        print("preflight: gh authenticated")

    # 2. List deploy keys
    keys = list_deploy_keys(repo, gh)
    if keys is None:
        blockers += 1
        print(
            "preflight: BLOCKER: deploy-key list retrieval failed — "
            "cannot verify existing keys"
        )
    else:
        print(f"preflight: found {len(keys)} existing deploy key(s)")

    # 3. Check for disabled keys (only when key list succeeded)
    if keys is not None:
        blockers += check_disabled_keys(keys, repo)

    # 4. Prove disposable key create/read/delete capability and absence.
    policy_blocked, policy_detail = check_deploy_key_lifecycle(repo, gh)
    if policy_blocked:
        print(f"preflight: BLOCKER: {policy_detail}")
        blockers += 1
    else:
        print(f"preflight: {policy_detail}")

    # 5. Summary
    print()
    if blockers == 0:
        print(f"preflight: PASS — no deploy-key blockers for {repo}")
        return 0
    else:
        print(f"preflight: FAIL — {blockers} blocker(s) detected")
        print(
            "preflight: See docs/flux-deploy-key-operator-guide.md "
            "for resolution steps."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
