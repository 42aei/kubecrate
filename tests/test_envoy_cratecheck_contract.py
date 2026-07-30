#!/usr/bin/env python3
"""Focused static and CEL checks for the Envoy Gateway CrateCheck contract."""

from pathlib import Path

import yaml
from celpy import Environment
from celpy.adapter import json_to_cel

ROOT = Path(__file__).resolve().parent.parent
CONFIGMAP = ROOT / "application-services" / "cratecheck" / "base" / "configmap.yaml"
ENVOY_VALUES = ROOT / "compositions" / "vanilla" / "platform-services" / "envoy-gateway" / "helm-values.yaml"


def configured_checks() -> dict[str, dict]:
    configmap = yaml.safe_load(CONFIGMAP.read_text())
    status = yaml.safe_load(configmap["data"]["status.yaml"])
    return {check["id"]: check for check in status["checks"]}


def evaluate(expression: str, resource: dict) -> bool:
    environment = Environment()
    program = environment.program(environment.compile(expression))
    return bool(program.evaluate({"object": json_to_cel(resource)}))


def test_envoy_base_check_accepts_only_ready_helmrelease() -> None:
    checks = configured_checks()
    assert "envoy-helmrelease-ready" in checks
    assert "envoy-httproute-ready" in checks
    expression = checks["envoy-helmrelease-ready"]["expression"]
    assert evaluate(expression, {"status": {"conditions": [{"type": "Ready", "status": "True"}]}})
    assert not evaluate(expression, {"status": {"conditions": [{"type": "Ready", "status": "False"}]}})
    assert not evaluate(expression, {})


def test_envoy_base_does_not_ship_kind_nodeport_smoke_fixture() -> None:
    values = yaml.safe_load(ENVOY_VALUES.read_text())
    assert isinstance(values, dict)
    assert not (ROOT / "compositions/vanilla/platform-services/envoy-gateway/smoke").exists()
