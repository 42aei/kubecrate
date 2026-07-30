#!/usr/bin/env python3
"""Focused semantic checks for Kubecrate's Kyverno base contract."""

import runpy
from pathlib import Path

import yaml
from celpy import Environment
from celpy.adapter import json_to_cel

ROOT = Path(__file__).resolve().parent.parent
CONFIGMAP = ROOT / "application-services/cratecheck/base/configmap.yaml"
RBAC = ROOT / "application-services/cratecheck/base/clusterrole.yaml"
ENTRYPOINT = ROOT / "compositions/vanilla/entrypoint"
MANIFEST_VALIDATOR = ROOT / "scripts/validate-kubernetes-manifests.py"

PRESERVED_IDS = {
    "cratecheck-deployment-ready",
    "eso-helmrelease-ready",
    "cert-manager-tls-certificate-ready",
    "kyverno-helmrelease-ready",
}
REMOVED_KIND_SMOKE_IDS = {
    "kyverno-clusterpolicy-ready",
    "kyverno-smoke-namespace-exists",
}
KYVERNO_KUSTOMIZE_ROOTS = {
    "platform-services/kyverno/base",
    "compositions/vanilla/platform-services/kyverno",
}


def configured_checks() -> dict[str, dict]:
    configmap = yaml.safe_load(CONFIGMAP.read_text())
    status = yaml.safe_load(configmap["data"]["status.yaml"])
    return {check["id"]: check for check in status["checks"]}


def evaluate(expression: str, resource: dict) -> bool:
    environment = Environment()
    program = environment.program(environment.compile(expression))
    return bool(program.evaluate({"object": json_to_cel(resource)}))


def test_kyverno_base_check_is_additive_and_behavioral() -> None:
    checks = configured_checks()
    assert PRESERVED_IDS <= checks.keys()
    assert REMOVED_KIND_SMOKE_IDS <= checks.keys()

    ready = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}
    not_ready = {"status": {"conditions": [{"type": "Ready", "status": "False"}]}}
    expression = checks["kyverno-helmrelease-ready"]["expression"]
    assert evaluate(expression, ready)
    assert not evaluate(expression, not_ready)
    assert not evaluate(expression, {})


def test_kyverno_rbac_is_read_only_and_exact() -> None:
    role = yaml.safe_load(RBAC.read_text())
    kyverno_rules = [
        rule for rule in role["rules"] if "kyverno.io" in rule.get("apiGroups", [])
    ]
    assert kyverno_rules == [{
        "apiGroups": ["kyverno.io"],
        "resources": ["clusterpolicies"],
        "verbs": ["get"],
    }]


def test_entrypoint_contains_controller_without_kind_smoke_fixtures() -> None:
    controller = yaml.safe_load((ENTRYPOINT / "kyverno-kustomization.yaml").read_text())
    assert controller["spec"]["sourceRef"] == {
        "kind": "GitRepository", "name": "flux-system-sync"
    }
    assert not (ENTRYPOINT / "kyverno-smoke-policy-kustomization.yaml").exists()
    assert not (ENTRYPOINT / "kyverno-smoke-kustomization.yaml").exists()
    assert not (ROOT / "compositions/vanilla/platform-services/kyverno/smoke-policy").exists()
    assert not (ROOT / "compositions/vanilla/platform-services/kyverno/smoke").exists()


def test_all_kyverno_base_roots_are_authoritatively_validated() -> None:
    validator = runpy.run_path(str(MANIFEST_VALIDATOR))
    assert KYVERNO_KUSTOMIZE_ROOTS <= set(validator["KUSTOMIZE_ROOTS"])
