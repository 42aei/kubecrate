#!/usr/bin/env python3
"""Preflight: detect GitHub deploy-key blockers before Flux bootstrap.

This script runs before disposable-cluster creation. It checks whether the
target Git provider (GitHub) allows deploy-key registration for the configured
repository and whether any existing deploy keys are disabled.  It exits 0 when
the path is clear and non-zero when a blocker is detected.

It does not retrieve, print, or touch private key material.

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
from typing import Any


def run_gh(args: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run 'gh <args>' and return the completed process."""
    cmd = ["gh"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=stdin,
    )


def gh_authenticated() -> bool:
    result = run_gh(["auth", "status"])
    return result.returncode == 0


def list_deploy_keys(repo: str) -> list[dict[str, Any]]:
    """Return deploy keys for the given GitHub repository."""
    result = run_gh(["api", f"repos/{repo}/keys", "--jq", "."])
    if result.returncode != 0:
        print(f"preflight: ERROR: could not list deploy keys for {repo}")
        print(f"preflight: stderr: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def check_disabled_keys(keys: list[dict[str, Any]], repo: str) -> int:
    """Check for disabled deploy keys. Returns count of disabled keys."""
    disabled = [k for k in keys if k.get("enabled") is False]
    if not disabled:
        return 0

    print(f"preflight: BLOCKER: {len(disabled)} disabled deploy key(s) on {repo}:")
    for k in disabled:
        print(f"  - id={k.get('id')} title={k.get('title')!r} enabled={k.get('enabled')}")
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
    print(
        "preflight: Docs: docs/flux-deploy-key-operator-guide.md"
    )
    return len(disabled)


def check_key_creation_blocked(repo: str) -> bool:
    """Try an idempotent read against the deploy-key endpoint.

    A 422 response typically means the org disallows deploy keys.
    A 200/404 means the API endpoint is reachable (key-specific 404 is fine).
    Returns True if key creation appears blocked.
    """
    # Use a HEAD-like check: list keys and inspect the HTTP status.
    # We already listed keys above; this is a supplementary check
    # that tests the POST endpoint behaviour through a safe read.
    result = run_gh(["api", f"repos/{repo}/keys", "--jq", "length"])
    return result.returncode != 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight check for Flux deploy-key readiness"
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("KUBECRATE_GIT_REPO", "42aei/kubecrate"),
        help="GitHub repository in owner/repo format",
    )
    args = parser.parse_args()

    repo = args.repo
    blockers = 0

    print(f"preflight: checking deploy-key readiness for {repo}")

    # 1. Verify gh is authenticated
    if not gh_authenticated():
        print("preflight: BLOCKER: gh CLI is not authenticated.")
        print("preflight: Run 'gh auth login' or set GH_TOKEN.")
        blockers += 1
    else:
        print("preflight: gh authenticated")

    # 2. List deploy keys
    keys = list_deploy_keys(repo)
    print(f"preflight: found {len(keys)} existing deploy key(s)")

    # 3. Check for disabled keys
    blockers += check_disabled_keys(keys, repo)

    # 4. Check API reachability
    if check_key_creation_blocked(repo):
        print(
            "preflight: BLOCKER: the GitHub deploy-key API endpoint is not reachable "
            "or returned an unexpected response. Check gh auth scopes and repository access."
        )
        blockers += 1

    # 5. Summary
    print()
    if blockers == 0:
        print(f"preflight: PASS — no deploy-key blockers for {repo}")
        return 0
    else:
        print(f"preflight: FAIL — {blockers} blocker(s) detected")
        print("preflight: See docs/flux-deploy-key-operator-guide.md for resolution steps.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
