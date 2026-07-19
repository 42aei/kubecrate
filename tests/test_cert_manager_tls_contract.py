#!/usr/bin/env python3
"""Focused semantic and CEL checks for cert-manager TLS composition."""

import runpy
from pathlib import Path

import yaml
from celpy import Environment
from celpy.adapter import json_to_cel

ROOT = Path(__file__).resolve().parent.parent
CONFIGMAP = ROOT / "application-services/cratecheck/base/configmap.yaml"
RBAC = ROOT / "application-services/cratecheck/base/clusterrole.yaml"
GATEWAY = ROOT / "clusters/kind-dev-misc-local/platform-services/envoy-gateway/smoke/smoke-gateway.yaml"
ROUTE = ROOT / "clusters/kind-dev-misc-local/platform-services/envoy-gateway/smoke/smoke-httproute.yaml"
REFERENCE_GRANT = ROOT / "clusters/kind-dev-misc-local/platform-services/envoy-gateway/smoke/smoke-referencegrant.yaml"
CERTIFICATES = ROOT / "clusters/kind-dev-misc-local/platform-services/cert-manager/local-issuer/local-ca-issuer.yaml"
MANIFEST_VALIDATOR = ROOT / "scripts/validate-kubernetes-manifests.py"

CERT_MANAGER_IDS = {
    "cert-manager-helmrelease-ready",
    "cert-manager-selfsigned-issuer-ready",
    "cert-manager-ca-certificate-ready",
    "cert-manager-ca-issuer-ready",
    "cert-manager-tls-certificate-ready",
    "cert-manager-tls-secret-exists",
}
CERT_MANAGER_KUSTOMIZE_ROOTS = {
    "platform-services/cert-manager/base",
    "clusters/kind-dev-misc-local/platform-services/cert-manager",
    "clusters/kind-dev-misc-local/platform-services/cert-manager/local-issuer",
}


def checks() -> dict[str, dict]:
    configmap = yaml.safe_load(CONFIGMAP.read_text())
    status = yaml.safe_load(configmap["data"]["status.yaml"])
    return {check["id"]: check for check in status["checks"]}


def evaluate(expression: str, resource: dict) -> bool:
    environment = Environment()
    program = environment.program(environment.compile(expression))
    return bool(program.evaluate({"object": json_to_cel(resource)}))


def test_cert_manager_checks_preserve_existing_contract_and_evaluate_ready_state() -> None:
    configured = checks()
    assert CERT_MANAGER_IDS <= configured.keys()
    assert {"eso-helmrelease-ready", "envoy-httproute-ready"} <= configured.keys()
    ready = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}
    not_ready = {"status": {"conditions": [{"type": "Ready", "status": "False"}]}}
    for check_id in CERT_MANAGER_IDS - {"cert-manager-tls-secret-exists"}:
        expression = configured[check_id]["expression"]
        assert evaluate(expression, ready)
        assert not evaluate(expression, not_ready)
        assert not evaluate(expression, {})
    secret_expression = configured["cert-manager-tls-secret-exists"]["expression"]
    assert evaluate(secret_expression, {"metadata": {"name": "cratecheck-tls"}})
    assert not evaluate(secret_expression, {"metadata": {"name": "other"}})


def test_cert_manager_rbac_is_read_only_and_exact() -> None:
    role = yaml.safe_load(RBAC.read_text())
    cert_rules = [rule for rule in role["rules"] if "cert-manager.io" in rule.get("apiGroups", [])]
    assert cert_rules == [{
        "apiGroups": ["cert-manager.io"],
        "resources": ["clusterissuers", "certificates"],
        "verbs": ["get"],
    }]


def test_cert_manager_roots_are_in_authoritative_manifest_validation() -> None:
    validator = runpy.run_path(str(MANIFEST_VALIDATOR))
    assert CERT_MANAGER_KUSTOMIZE_ROOTS <= set(validator["KUSTOMIZE_ROOTS"])


def test_issued_certificate_is_bound_to_envoy_https() -> None:
    certificates = list(yaml.safe_load_all(CERTIFICATES.read_text()))
    tls_certificate = next(item for item in certificates if item["kind"] == "Certificate" and item["metadata"]["name"] == "cratecheck-tls")
    assert tls_certificate["metadata"]["namespace"] == "cratecheck"
    assert tls_certificate["spec"]["dnsNames"] == ["cratecheck.local"]
    assert tls_certificate["spec"]["secretName"] == "cratecheck-tls"

    gateway = yaml.safe_load(GATEWAY.read_text())
    https = next(listener for listener in gateway["spec"]["listeners"] if listener["name"] == "https")
    assert https["protocol"] == "HTTPS" and https["port"] == 443
    assert https["tls"]["certificateRefs"] == [{
        "group": "", "kind": "Secret", "name": "cratecheck-tls", "namespace": "cratecheck"
    }]

    route = yaml.safe_load(ROUTE.read_text())
    assert {parent["sectionName"] for parent in route["spec"]["parentRefs"]} == {"http", "https"}
    grant = yaml.safe_load(REFERENCE_GRANT.read_text())
    assert grant["metadata"]["namespace"] == "cratecheck"
    assert grant["spec"]["to"] == [{"group": "", "kind": "Secret", "name": "cratecheck-tls"}]
