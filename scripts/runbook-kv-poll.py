#!/usr/bin/env python3
"""Shared Kyverno runbook polling helpers extracted from the runbook.

Provides the core CrateCheck /status.json polling logic used across the runbook's
green, controlled-red, and restored-green phases. Designed to be:

  - imported as a module by validate-cratecheck.py for fixture-based testing
  - called as a CLI with --fixture <json-file> for executable validation

Usage (CLI):
  python3 scripts/runbook-kv-poll.py --fixture tests/fixtures/kv-all-green.json --mode green
  python3 scripts/runbook-kv-poll.py --fixture tests/fixtures/kv-controlled-red.json --mode red
  python3 scripts/runbook-kv-poll.py --fixture tests/fixtures/kv-all-green.json --mode restored-green

Exit codes:
  0 - polling succeeded (all required checks reached expected state)
  1 - polling failed (checks did not reach expected state)
  2 - usage error
"""

import argparse
import json
import sys
import time
from pathlib import Path

TARGET_IDS = {
    "kyverno-helmrelease-ready",
    "kyverno-clusterpolicy-ready",
    "kyverno-smoke-namespace-exists",
}

RED_TARGET_ID = "kyverno-clusterpolicy-ready"
UNAFFECTED_IDS = {"kyverno-helmrelease-ready", "kyverno-smoke-namespace-exists"}


def load_fixture(path: str) -> dict:
    """Load a fixture JSON file representing a /status.json response."""
    with open(path) as f:
        return json.load(f)


def build_check_map(payload: dict) -> dict:
    """Build {check_id: check_dict} from a /status.json payload."""
    return {c["id"]: c for c in payload.get("checks", [])}


def poll_all_green(
    fixture: dict,
    deadline: float | None = None,
    poll_interval: float = 5.0,
) -> tuple[bool, dict]:
    """Poll until all TARGET_IDS are green (or deadline expires).

    Returns (all_green: bool, final_check_map: dict).
    """
    if deadline is None:
        deadline = time.time() + 60

    while time.time() < deadline:
        checks = build_check_map(fixture)

        if not TARGET_IDS.issubset(checks.keys()):
            missing = TARGET_IDS - set(checks.keys())
            _log_state(checks, note=f"MISSING checks: {sorted(missing)}")
            return (False, checks)

        all_ok = True
        for cid in sorted(TARGET_IDS):
            state = checks[cid]["state"]
            summary = checks[cid].get("summary", "")
            _log_check(state, cid, summary)
            if state != "green":
                all_ok = False

        if all_ok:
            return (True, checks)
        return (False, checks)

    return (False, build_check_map(fixture))


def poll_exact_red(
    fixture: dict,
    deadline: float | None = None,
    poll_interval: float = 5.0,
) -> tuple[bool, bool, dict]:
    """Poll until RED_TARGET_ID is red AND all UNAFFECTED_IDS are green.

    Returns (target_is_red: bool, unaffected_ok: bool, check_map: dict).
    """
    if deadline is None:
        deadline = time.time() + 60

    while time.time() < deadline:
        checks = build_check_map(fixture)

        # All three checks must be present
        cp = checks.get(RED_TARGET_ID)
        hr = checks.get("kyverno-helmrelease-ready")
        ns = checks.get("kyverno-smoke-namespace-exists")

        if cp is None or hr is None or ns is None:
            _log_state(checks, note="MISSING one or more Kyverno checks")
            return (False, False, checks)

        cp_is_red = cp["state"] == "red"
        unaffected_ok = (
            hr["state"] == "green" and ns["state"] == "green"
        )

        _log_check(cp["state"], RED_TARGET_ID, cp.get("summary", ""))
        _log_check(hr["state"], "kyverno-helmrelease-ready", hr.get("summary", ""))
        _log_check(ns["state"], "kyverno-smoke-namespace-exists", ns.get("summary", ""))

        if cp_is_red and unaffected_ok:
            return (True, True, checks)
        return (cp_is_red, unaffected_ok, checks)

    checks = build_check_map(fixture)
    cp = checks.get(RED_TARGET_ID)
    hr = checks.get("kyverno-helmrelease-ready")
    ns = checks.get("kyverno-smoke-namespace-exists")
    return (
        cp is not None and cp["state"] == "red",
        hr is not None and ns is not None
        and hr["state"] == "green" and ns["state"] == "green",
        checks,
    )


def poll_restored_green(
    fixture: dict,
    deadline: float | None = None,
    poll_interval: float = 5.0,
) -> tuple[bool, dict]:
    """Poll after restoration until all TARGET_IDS are green.

    Returns (all_green: bool, check_map: dict).
    """
    return poll_all_green(fixture, deadline, poll_interval)


def poll_general_state(
    fixture: dict,
    expected_states: dict[str, str],
    deadline: float | None = None,
    poll_interval: float = 5.0,
) -> tuple[bool, dict]:
    """Poll until checks match expected states.

    expected_states is {check_id: expected_state}.

    Returns (all_matched: bool, check_map: dict).
    """
    if deadline is None:
        deadline = time.time() + 60

    while time.time() < deadline:
        checks = build_check_map(fixture)

        all_matched = True
        for cid, expected in expected_states.items():
            c = checks.get(cid)
            actual = c["state"] if c else "MISSING"
            summary = c.get("summary", "") if c else ""
            _log_check(actual, cid, summary)
            if actual != expected:
                all_matched = False

        if all_matched:
            return (True, checks)
        return (False, checks)

    return (False, build_check_map(fixture))


def _log_check(state: str, check_id: str, summary: str = "") -> None:
    """Print a single check line in runbook format."""
    print(f"  {state:>8} {check_id}: {summary}")


def _log_state(checks: dict, note: str = "") -> None:
    """Log all target checks with an optional note."""
    for cid in sorted(TARGET_IDS):
        c = checks.get(cid)
        state = c["state"] if c else "MISSING"
        summary = c.get("summary", "") if c else ""
        print(f"  {state:>8} {cid}: {summary}")
    if note:
        print(f"  NOTE: {note}")


def cmd_poll() -> int:
    """CLI entry point for fixture-based polling."""
    parser = argparse.ArgumentParser(
        description="Runbook Kyverno polling against a fixture /status.json",
    )
    parser.add_argument(
        "--fixture", required=True, type=str,
        help="Path to fixture JSON file (simulated /status.json)",
    )
    parser.add_argument(
        "--mode", required=True,
        choices=["green", "red", "restored-green", "controlled-red"],
        help="Polling mode",
    )
    parser.add_argument(
        "--deadline-offset", type=float, default=60.0,
        help="Deadline offset in seconds from now (default: 60)",
    )
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    deadline = time.time() + args.deadline_offset

    if args.mode == "green":
        all_ok, checks = poll_all_green(fixture, deadline)
        if all_ok:
            print("\nAll Kyverno CrateCheck checks are green.")
            return 0
        else:
            print("\nFAIL: Kyverno CrateCheck checks did not reach green.")
            return 1

    elif args.mode in ("red", "controlled-red"):
        target_is_red, unaffected_ok, checks = poll_exact_red(fixture, deadline)
        if target_is_red and unaffected_ok:
            print("\nPASS: red test — ClusterPolicy red, HelmRelease+smoke namespace unaffected green.")
            return 0
        else:
            if not target_is_red:
                print("\nFAIL: kyverno-clusterpolicy-ready did not turn red.")
            if not unaffected_ok:
                print("\nFAIL: unaffected Kyverno checks are not green.")
            return 1

    elif args.mode == "restored-green":
        all_ok, checks = poll_restored_green(fixture, deadline)
        if all_ok:
            print("\nAll Kyverno CrateCheck checks are green after restoration.")
            return 0
        else:
            print("\nFAIL: Kyverno checks did not return to green after restoration.")
            return 1

    return 2


if __name__ == "__main__":
    sys.exit(cmd_poll())
