#!/usr/bin/env python3
"""Focused semantic checks for additive Kyverno policy composition."""

import runpy
from pathlib import Path

import yaml
from celpy import Environment
from celpy.adapter import json_to_cel

ROOT = Path(__file__).resolve().parent.parent
CONFIGMAP = ROOT / "application-services/cratecheck/base/configmap.yaml"
RBAC = ROOT / "application-services/cratecheck/base/clusterrole.yaml"
POLICY = ROOT / "clusters/kind-dev-misc-local/platform-services/kyverno/smoke-policy/require-ns-label-policy.yaml"
FIXTURE = ROOT / "clusters/kind-dev-misc-local/platform-services/kyverno/smoke/smoke-allowed-namespace.yaml"
ENTRYPOINT = ROOT / "clusters/kind-dev-misc-local/entrypoint"
MANIFEST_VALIDATOR = ROOT / "scripts/validate-kubernetes-manifests.py"
RUNNER = ROOT / "scripts/direct-kind-flux-e2e.sh"

KYVERNO_IDS = {
    "kyverno-helmrelease-ready",
    "kyverno-clusterpolicy-ready",
    "kyverno-smoke-namespace-exists",
}
PRESERVED_IDS = {
    "cratecheck-deployment-ready",
    "eso-helmrelease-ready",
    "envoy-httproute-ready",
    "cert-manager-tls-certificate-ready",
}
KYVERNO_KUSTOMIZE_ROOTS = {
    "platform-services/kyverno/base",
    "clusters/kind-dev-misc-local/platform-services/kyverno",
    "clusters/kind-dev-misc-local/platform-services/kyverno/smoke-policy",
    "clusters/kind-dev-misc-local/platform-services/kyverno/smoke",
}
DENIAL_MESSAGE = "Namespace requires kubecrate.io/validated=true"


def configured_checks() -> dict[str, dict]:
    configmap = yaml.safe_load(CONFIGMAP.read_text())
    status = yaml.safe_load(configmap["data"]["status.yaml"])
    return {check["id"]: check for check in status["checks"]}


def evaluate(expression: str, resource: dict) -> bool:
    environment = Environment()
    program = environment.program(environment.compile(expression))
    return bool(program.evaluate({"object": json_to_cel(resource)}))


def test_kyverno_checks_are_additive_and_behavioral() -> None:
    checks = configured_checks()
    assert KYVERNO_IDS | PRESERVED_IDS <= checks.keys()

    ready = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}
    not_ready = {"status": {"conditions": [{"type": "Ready", "status": "False"}]}}
    for check_id in {"kyverno-helmrelease-ready", "kyverno-clusterpolicy-ready"}:
        expression = checks[check_id]["expression"]
        assert evaluate(expression, ready)
        assert not evaluate(expression, not_ready)
        assert not evaluate(expression, {})

    namespace_expression = checks["kyverno-smoke-namespace-exists"]["expression"]
    assert evaluate(namespace_expression, {
        "metadata": {
            "name": "kyverno-smoke-allowed",
            "labels": {"kubecrate.io/validated": "true"},
        }
    })
    assert not evaluate(namespace_expression, {
        "metadata": {"name": "kyverno-smoke-allowed", "labels": {}}
    })


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


def test_policy_is_narrow_and_fixture_is_a_real_allowed_consumer() -> None:
    policy = yaml.safe_load(POLICY.read_text())
    assert policy["spec"]["validationFailureAction"] == "Enforce"
    assert len(policy["spec"]["rules"]) == 1
    rule = policy["spec"]["rules"][0]
    assert rule["match"]["any"] == [{
        "resources": {"kinds": ["Namespace"], "names": ["kyverno-smoke-*"]}
    }]
    assert rule["validate"]["message"] == DENIAL_MESSAGE
    assert f'KYVERNO_DENIAL_REASON="{DENIAL_MESSAGE}"' in RUNNER.read_text()
    assert rule["validate"]["pattern"]["metadata"]["labels"] == {
        "kubecrate.io/validated": "true"
    }

    fixture = yaml.safe_load(FIXTURE.read_text())
    assert fixture["kind"] == "Namespace"
    assert fixture["metadata"]["name"] == "kyverno-smoke-allowed"
    assert fixture["metadata"]["labels"]["kubecrate.io/validated"] == "true"
    assert fixture["metadata"]["labels"]["kubecrate.io/workload-category"] == "application-services"


def test_entrypoint_orders_controller_policy_and_consumer_on_current_source() -> None:
    controller = yaml.safe_load((ENTRYPOINT / "kyverno-kustomization.yaml").read_text())
    policy = yaml.safe_load((ENTRYPOINT / "kyverno-smoke-policy-kustomization.yaml").read_text())
    consumer = yaml.safe_load((ENTRYPOINT / "kyverno-smoke-kustomization.yaml").read_text())
    for resource in (controller, policy, consumer):
        assert resource["spec"]["sourceRef"] == {
            "kind": "GitRepository", "name": "flux-system-sync"
        }
    assert policy["spec"]["dependsOn"] == [{"name": "kyverno"}]
    assert consumer["spec"]["dependsOn"] == [{"name": "kyverno-smoke-policy"}]


def test_all_kyverno_roots_are_authoritatively_validated() -> None:
    validator = runpy.run_path(str(MANIFEST_VALIDATOR))
    assert KYVERNO_KUSTOMIZE_ROOTS <= set(validator["KUSTOMIZE_ROOTS"])
