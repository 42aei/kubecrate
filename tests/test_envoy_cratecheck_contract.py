#!/usr/bin/env python3
"""Focused static and CEL checks for the Envoy Gateway CrateCheck contract."""

from pathlib import Path

import yaml
from celpy import Environment
from celpy.adapter import json_to_cel

ROOT = Path(__file__).resolve().parent.parent
CONFIGMAP = ROOT / "application-services" / "cratecheck" / "base" / "configmap.yaml"
ENVOYPROXY = (
    ROOT / "clusters" / "kind-dev-misc-local" / "platform-services"
    / "envoy-gateway" / "smoke" / "smoke-envoyproxy.yaml"
)


def route_expression() -> str:
    configmap = yaml.safe_load(CONFIGMAP.read_text())
    status = yaml.safe_load(configmap["data"]["status.yaml"])
    return next(
        check["expression"] for check in status["checks"]
        if check["id"] == "envoy-httproute-ready"
    )


def evaluate(expression: str, resource: dict) -> bool:
    environment = Environment()
    program = environment.program(environment.compile(expression))
    return bool(program.evaluate({"object": json_to_cel(resource)}))


def healthy_parent() -> dict:
    return {
        "parentRef": {
            "group": "gateway.networking.k8s.io",
            "kind": "Gateway",
            "name": "kubecrate-envoy-smoke",
            "namespace": "core-envoy-gateway",
            "sectionName": "http",
        },
        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
        "conditions": [
            {"type": "Accepted", "status": "True"},
            {"type": "ResolvedRefs", "status": "True"},
        ],
    }


def test_route_cel_accepts_only_exact_healthy_parent() -> None:
    expression = route_expression()
    parent = healthy_parent()
    assert evaluate(expression, {"status": {"parents": [parent]}})

    wrong_controller = {**parent, "controllerName": "example.invalid/controller"}
    assert not evaluate(expression, {"status": {"parents": [wrong_controller]}})

    unresolved = {
        **parent,
        "conditions": [
            {"type": "Accepted", "status": "True"},
            {"type": "ResolvedRefs", "status": "False"},
        ],
    }
    assert not evaluate(expression, {"status": {"parents": [unresolved]}})


def test_envoyproxy_has_deterministic_http_nodeport_patch() -> None:
    resource = yaml.safe_load(ENVOYPROXY.read_text())
    service = resource["spec"]["provider"]["kubernetes"]["envoyService"]
    assert service["type"] == "NodePort"
    assert service["patch"]["value"]["spec"]["ports"] == [
        {"name": "http", "port": 80, "nodePort": 30080}
    ]
