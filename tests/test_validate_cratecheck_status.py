#!/usr/bin/env python3
"""Focused contract tests for the direct E2E CrateCheck JSON validator."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate-cratecheck-status.py"
SPEC = importlib.util.spec_from_file_location("validate_cratecheck_status", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def payload(*, changed: set[str] | None = None) -> dict:
    changed = changed or set()
    checks = [
        {"id": check_id, "status": "red" if check_id in changed else "green"}
        for check_id in sorted(MODULE.EXPECTED_IDS)
    ]
    red = len(changed)
    green = len(checks) - red
    return {
        "status": "red" if red else "green",
        "summary": {"green": green, "red": red, "yellow": 0, "unknown": 0, "total": len(checks)},
        "checks": checks,
    }


def test_green_requires_every_exact_enabled_check() -> None:
    MODULE.validate_status(payload(), "green")
    missing = payload()
    missing["checks"].pop()
    with pytest.raises(AssertionError):
        MODULE.validate_status(missing, "green")


def test_eso_red_requires_both_source_dependent_eso_checks() -> None:
    MODULE.validate_status(payload(changed=set(MODULE.RED_IDS["eso-red"])), "eso-red")
    with pytest.raises(AssertionError):
        MODULE.validate_status(payload(changed={"eso-externalsecret-ready"}), "eso-red")


def test_eso_red_rejects_unrelated_check_failure() -> None:
    with pytest.raises(AssertionError):
        MODULE.validate_status(payload(changed={"cratecheck-deployment-ready"}), "eso-red")


def test_envoy_red_changes_only_route_check() -> None:
    MODULE.validate_status(payload(changed={"envoy-httproute-ready"}), "envoy-red")
    with pytest.raises(AssertionError):
        MODULE.validate_status(
            payload(changed={"envoy-httproute-ready", "envoy-gateway-ready"}),
            "envoy-red",
        )


@pytest.mark.parametrize("status", ["yellow", "unknown"])
def test_eso_red_rejects_non_red_intended_state(status: str) -> None:
    invalid = payload(changed=set(MODULE.RED_IDS["eso-red"]))
    invalid["checks"][next(
        index for index, check in enumerate(invalid["checks"])
        if check["id"] == "eso-projected-secret-exists"
    )]["status"] = status
    invalid["summary"]["red"] -= 1
    invalid["summary"][status] += 1
    with pytest.raises(AssertionError):
        MODULE.validate_status(invalid, "eso-red")


def test_summary_must_match_exact_check_states() -> None:
    invalid = payload()
    invalid["summary"]["green"] -= 1
    with pytest.raises(AssertionError):
        MODULE.validate_status(invalid, "green")
