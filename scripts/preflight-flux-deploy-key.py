#!/usr/bin/env python3
"""Preflight: detect GitHub deploy-key blockers before Flux bootstrap.

This script runs before disposable-cluster creation. It checks whether the
target Git provider (GitHub) allows deploy-key registration for the configured
repository and whether any existing deploy keys are disabled.  It exits 0 when
the path is clear and non-zero when a blocker is detected.

It does not retrieve, print, or touch private key material.  It never creates
or deletes a deploy key: the POST capability probe uses an intentionally
invalid key that GitHub will always reject, and the response message
distinguishes org-policy denial from a normal invalid-key rejection.

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
) -> list[dict[str, Any]]:
    """Return deploy keys for the given GitHub repository."""
    result = gh(["api", f"repos/{repo}/keys", "--jq", "."])
    if result.returncode != 0:
        print(f"preflight: ERROR: could not list deploy keys for {repo}")
        print(f"preflight: stderr: {result.stderr.strip()}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


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


def check_org_deploy_key_policy(
    repo: str, gh: GhRunner = _default_gh_runner
) -> tuple[bool, str]:
    """Probe whether the GitHub org allows deploy-key creation.

    Sends a POST to repos/<repo>/keys with an intentionally invalid SSH key.
    GitHub will always reject the invalid key with HTTP 422, but the
    *reason* differs:

      - Org allows deploy keys  → message says "key is invalid" (or similar)
      - Org disallows deploy keys → message says "Deploy keys are not
        supported for this organization"

    Returns (blocked: bool, detail: str).

    This is safe: the probe key is not valid SSH material and GitHub will
    never accept it, even if the org policy allows deploy keys.
    """
    # Intentionally invalid key — base64-encoded garbage that is clearly
    # not a real SSH public key.  GitHub rejects it in every scenario.
    probe_title = "preflight-policy-probe"
    probe_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDPREFLIGHT_PROBE_DO_NOT_USE"

    result = gh(
        [
            "api",
            f"repos/{repo}/keys",
            "-X", "POST",
            "-f", f"title={probe_title}",
            "-f", f"key={probe_key}",
            "-f", "read_only=true",
            "--include",  # include response headers for status inspection
        ],
    )

    stdout = result.stdout
    stderr = result.stderr
    combined = stdout + stderr

    # Check if the response contains the org-policy-denial message.
    if "Deploy keys are not supported" in combined:
        org = repo.split("/")[0] if "/" in repo else repo
        return (
            True,
            f"org-level deploy-key policy is OFF — "
            f"GitHub returned HTTP 422 with message: "
            f"\"Deploy keys are not supported for this organization.\" "
            f"An org owner must enable deploy keys at "
            f"https://github.com/organizations/{org}/settings/member_privileges "
            f"before Flux bootstrap can register a deploy key.",
        )

    # An HTTP 422 that does NOT mention "not supported" is likely the
    # expected "key is invalid" rejection — the org allows deploy keys,
    # our probe was just garbage.
    if result.returncode != 0:
        # Could be a network/auth/rate-limit error, not a policy block.
        # We cannot definitively say the org allows keys, but we also have
        # no positive signal of a policy block.
        if "HTTP 422" in combined or "422" in combined:
            return (
                False,
                "org allows deploy-key creation "
                "(POST /keys returned HTTP 422 with invalid-key rejection, "
                "not an org-policy denial).",
            )
        # Unexpected failure (auth, network, API error).
        return (
            True,
            f"unexpected response from deploy-key API endpoint: "
            f"exit={result.returncode}. "
            f"Check gh auth scopes and repository access. "
            f"stderr: {stderr.strip()[:300]}",
        )

    # If we somehow got a 200/201 back, that would mean GitHub accepted our
    # deliberately-invalid key.  This should never happen with the current
    # GitHub API, but we handle it defensively.
    return (
        True,
        "unexpected success from deploy-key API: GitHub accepted an "
        "intentionally invalid probe key. This should never happen; "
        "the GitHub API behaviour may have changed. "
        "Investigate before proceeding.",
    )


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
    print(f"preflight: found {len(keys)} existing deploy key(s)")

    # 3. Check for disabled keys
    blockers += check_disabled_keys(keys, repo)

    # 4. Probe org deploy-key policy (non-destructive POST with invalid key)
    policy_blocked, policy_detail = check_org_deploy_key_policy(repo, gh)
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
