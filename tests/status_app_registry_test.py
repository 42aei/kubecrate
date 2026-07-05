#!/usr/bin/env python3
"""Focused local checks for kubecrate-status check registry and module seams."""

import json
import os
import pathlib
import tempfile
import types
from typing import Any, cast
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONFIG = REPO_ROOT / "application-services/kubecrate-status/base/app-config.yaml"
CHECK_MODULES_CONFIG = REPO_ROOT / "application-services/kubecrate-status/base/check-modules-config.yaml"
STATUS_CONFIG = REPO_ROOT / "application-services/kubecrate-status/base/status-config.yaml"


def literal_block(path, key):
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = f"  {key}: |"
    try:
        start = lines.index(marker) + 1
    except ValueError as exc:
        raise AssertionError(f"{marker!r} not found in {path}") from exc
    block = []
    for line in lines[start:]:
        if line and not line.startswith("    "):
            break
        block.append(line[4:] if line.startswith("    ") else "")
    return "\n".join(block) + "\n"


def load_check_module_sources():
    sources = {}
    lines = CHECK_MODULES_CONFIG.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("  ") and line.endswith(".py: |"):
            key = line.strip()[:-3]
            block = []
            for block_line in lines[index + 1:]:
                if block_line and not block_line.startswith("    "):
                    break
                block.append(block_line[4:] if block_line.startswith("    ") else "")
            sources[key] = "\n".join(block) + "\n"
    return sources


def load_status_app():
    source = literal_block(APP_CONFIG, "app.py")
    with tempfile.TemporaryDirectory() as module_dir:
        for name, module_source in load_check_module_sources().items():
            (pathlib.Path(module_dir) / name).write_text(module_source, encoding="utf-8")
        previous_modules_dir = os.environ.get("KUBECRATE_STATUS_CHECK_MODULES")
        os.environ["KUBECRATE_STATUS_CHECK_MODULES"] = module_dir
        try:
            module = types.ModuleType("kubecrate_status_app_under_test")
            module.__file__ = str(APP_CONFIG)
            exec(compile(source, str(APP_CONFIG), "exec"), module.__dict__)
            return module
        finally:
            if previous_modules_dir is None:
                os.environ.pop("KUBECRATE_STATUS_CHECK_MODULES", None)
            else:
                os.environ["KUBECRATE_STATUS_CHECK_MODULES"] = previous_modules_dir


def load_status_config():
    return json.loads(literal_block(STATUS_CONFIG, "config.json"))


def ready_resource(message="Ready"):
    return {"status": {"conditions": [{"type": "Ready", "status": "True", "reason": "Ready", "message": message}]}}


class StatusCheckRegistryTest(unittest.TestCase):
    def setUp(self):
        self.app = load_status_app()

    def base_check(self, **overrides):
        check = {
            "id": "test-check",
            "name": "Test check",
            "type": "layered",
            "enabled": True,
            "capability": "Test capability.",
            "area": "test area",
            "troubleshooting": "inspect test fixture",
            "successSummary": "Test check is green.",
            "failureSummaryPrefix": "Test check is not green: ",
            "diagnosticLayers": [],
        }
        check.update(overrides)
        return check

    def test_check_registry_exposes_stable_extension_points(self):
        self.assertIn("secret_loading", self.app.CHECK_REGISTRY)
        self.assertIn("ingress_reachability", self.app.CHECK_REGISTRY)
        self.assertIn("layered", self.app.CHECK_REGISTRY)
        for layer_type in ("condition", "target_secret", "volume_mount", "file", "service_endpoints", "http_probe", "gateway_listener", "httproute_attachment"):
            self.assertIn(layer_type, self.app.LAYER_REGISTRY)

    def test_check_modules_live_in_separate_configmap_fragments(self):
        sources = load_check_module_sources()

        self.assertEqual(set(sources), {"kubernetes_layers.py", "network_layers.py"})
        self.assertIn('@register_layer("target_secret")', sources["kubernetes_layers.py"])
        self.assertIn('@register_layer("gateway_listener")', sources["network_layers.py"])
        self.assertIn("load_check_modules()", literal_block(APP_CONFIG, "app.py"))

    def test_disabled_check_is_reserved_without_calling_unknown_handler(self):
        result = self.app.evaluate_check(self.base_check(type="future_slice_handler", enabled=False, summary="Reserved for later."))

        self.assertEqual(result["id"], "test-check")
        self.assertEqual(result["state"], "not_configured")
        self.assertFalse(result["enabled"])
        self.assertEqual(result["summary"], "Reserved for later.")

    def test_unknown_enabled_check_type_is_clear_yellow_not_payload_crash(self):
        result = self.app.evaluate_check(self.base_check(type="future_slice_handler"))

        self.assertEqual(result["state"], "yellow")
        self.assertTrue(result["enabled"])
        self.assertIn("future_slice_handler", result["summary"])
        self.assertIn("registeredCheckTypes", result["observed"])

    def test_layered_check_can_be_enabled_independently(self):
        fixture = {
            "/apis/example.io/v1/namespaces/test/widgets/example": ready_resource("Widget is ready."),
        }
        cast(Any, self.app).api_get = lambda path: fixture[path]
        check = self.base_check(diagnosticLayers=[{
            "id": "widgetReady",
            "name": "Widget ready",
            "failureArea": "widget readiness",
            "type": "condition",
            "apiPath": "/apis/example.io/v1/namespaces/test/widgets/example",
            "conditionType": "Ready",
            "observedFields": {"ready": "status.conditions[type=Ready].status"},
        }])

        result = self.app.evaluate_check(check)

        self.assertEqual(result["state"], "green")
        self.assertEqual(result["summary"], "Test check is green.")
        self.assertEqual(result["observed"]["layers"]["widgetReady"]["state"], "green")

    def test_unknown_layer_type_is_visible_without_crashing_layered_check(self):
        check = self.base_check(diagnosticLayers=[{
            "id": "futureLayer",
            "name": "Future layer",
            "failureArea": "future layer",
            "type": "future_layer",
        }])

        result = self.app.evaluate_check(check)

        self.assertEqual(result["state"], "yellow")
        layer = result["observed"]["layers"]["futureLayer"]
        self.assertEqual(layer["state"], "yellow")
        self.assertIn("future_layer", layer["summary"])

    def test_status_config_preserves_reserved_capability_check_ids(self):
        config = load_status_config()
        checks = {check["id"]: check for check in config["checks"]}

        for check_id in ("secret-loading", "ingress-reachability", "certificate-tls-status", "policy-behavior", "observability-signal-path"):
            self.assertIn(check_id, checks)
            self.assertFalse(checks[check_id]["enabled"])
            self.assertEqual(checks[check_id]["type"], "not_configured")

    def test_status_payload_contract_stays_stable_for_reserved_and_unknown_checks(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        config_path = pathlib.Path(tempdir.name) / "config.json"
        config_path.write_text(json.dumps({
            "app": "kubecrate-status",
            "version": "v0.test",
            "checks": [
                self.base_check(type="not_configured", enabled=False, summary="Reserved."),
                self.base_check(id="unknown", type="future_slice_handler"),
            ],
        }), encoding="utf-8")
        cast(Any, self.app).CONFIG_PATH = str(config_path)

        payload = self.app.status_payload()

        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["enabled"], 1)
        self.assertEqual(payload["summary"]["not_configured"], 1)
        self.assertEqual(payload["summary"]["yellow"], 1)
        for field in ("app", "version", "overallStatus", "healthScore", "generatedAt", "source", "title", "description", "summary", "checks"):
            self.assertIn(field, payload)
        for check in payload["checks"]:
            for field in ("id", "name", "capability", "area", "enabled", "troubleshooting", "state", "summary"):
                self.assertIn(field, check)


if __name__ == "__main__":
    unittest.main(verbosity=2)
