#!/usr/bin/env python3
"""Focused local checks for kubecrate-status secret-loading diagnostics.

These tests execute the Python application embedded in the kubecrate-status
ConfigMap and simulate Kubernetes API responses so the ESO smoke-path status
logic can be validated without a live cluster.
"""

import json
import os
import pathlib
import tempfile
import types
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_CONFIG = REPO_ROOT / "application-services/kubecrate-status/base/app-config.yaml"
CHECK_MODULES_CONFIG = REPO_ROOT / "application-services/kubecrate-status/base/check-modules-config.yaml"
STATUS_CONFIG = REPO_ROOT / "clusters/kind-dev-misc-local/application-services/kubecrate-status/status-config-eso-secret-loading.yaml"
KIND_STATUS_KUSTOMIZATION = REPO_ROOT / "clusters/kind-dev-misc-local/application-services/kubecrate-status/kustomization.yaml"
HELM_RELEASE = REPO_ROOT / "platform-services/external-secrets-operator/base/helm-release.yaml"


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
            module = types.ModuleType("kubecrate_status_app_under_test")  # type: ignore[var-annotated]
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


def secret_loading_check_config():
    config = load_status_config()
    return next(check for check in config["checks"] if check["id"] == "secret-loading")


def ready_resource(message="Ready"):
    return {"status": {"conditions": [{"type": "Ready", "status": "True", "reason": "Ready", "message": message}]}}


def not_ready_resource(reason, message):
    return {"status": {"conditions": [{"type": "Ready", "status": "False", "reason": reason, "message": message}]}}


class SecretLoadingDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.app = load_status_app()
        self.check = secret_loading_check_config()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.mount = pathlib.Path(self.tempdir.name) / "eso-smoke"
        self.secret_file = self.mount / "smoke-test"
        for layer in self.check["diagnosticLayers"]:
            if layer["id"] == "applicationVolumeWiring":
                layer["path"] = str(self.mount)
            if layer["id"] == "applicationReadBehavior":
                layer["path"] = str(self.secret_file)

    def api_fixture(self, overrides=None):
        fixture = {
            "/apis/helm.toolkit.fluxcd.io/v2/namespaces/core-external-secrets-operator/helmreleases/external-secrets": ready_resource("ESO HelmRelease is ready."),
            "/apis/external-secrets.io/v1/namespaces/kubecrate-status/secretstores/eso-smoke-kubernetes-store": ready_resource("SecretStore is ready."),
            "/apis/external-secrets.io/v1/namespaces/kubecrate-status/externalsecrets/eso-smoke-projection": ready_resource("ExternalSecret is ready."),
            "/api/v1/namespaces/kubecrate-status/secrets/eso-smoke-projected": {
                "metadata": {"namespace": "kubecrate-status", "name": "eso-smoke-projected"},
                "data": {"smoke-test": "a3ViZWNyYXRlLWVzby1zbW9rZS1vaw=="},
            },
        }
        fixture.update(overrides or {})
        return fixture

    def install_fake_api(self, fixture):
        def fake_api_get(path):
            value = fixture[path]
            if isinstance(value, BaseException):
                raise value
            return value
        setattr(self.app, "api_get", fake_api_get)

    def make_http_error(self, code):
        return self.app.urllib.error.HTTPError("https://kubernetes.example.invalid", code, "simulated", hdrs=None, fp=None)

    def assert_layer_state(self, result, layer_id, expected_state):
        layer = result["observed"]["layers"][layer_id]
        self.assertEqual(layer["state"], expected_state, layer)
        return layer

    def test_secret_loading_green_requires_upstream_target_mount_and_app_read(self):
        self.install_fake_api(self.api_fixture())
        self.mount.mkdir()
        self.secret_file.write_text("kubecrate-eso-smoke-ok", encoding="utf-8")

        result = self.app.secret_loading_check(self.check)

        self.assertEqual(result["state"], "green")
        self.assertIn("reconciled, mounted, and readable", result["summary"])
        for layer_id in (
            "esoControllerHealth",
            "secretStoreReadiness",
            "externalSecretReadiness",
            "targetSecretCreation",
            "applicationVolumeWiring",
            "applicationReadBehavior",
        ):
            self.assert_layer_state(result, layer_id, "green")

    def test_target_secret_missing_is_non_green_and_diagnostic(self):
        self.install_fake_api(self.api_fixture({
            "/api/v1/namespaces/kubecrate-status/secrets/eso-smoke-projected": self.make_http_error(404),
        }))
        self.mount.mkdir()
        self.secret_file.write_text("kubecrate-eso-smoke-ok", encoding="utf-8")

        result = self.app.secret_loading_check(self.check)

        self.assertEqual(result["state"], "yellow")
        target = self.assert_layer_state(result, "targetSecretCreation", "yellow")
        self.assertIn("target Secret creation", result["summary"])
        self.assertIn("does not exist", target["summary"])

    def test_missing_application_volume_wiring_is_non_green(self):
        self.install_fake_api(self.api_fixture())

        result = self.app.secret_loading_check(self.check)

        self.assertEqual(result["state"], "yellow")
        volume = self.assert_layer_state(result, "applicationVolumeWiring", "yellow")
        read = self.assert_layer_state(result, "applicationReadBehavior", "yellow")
        self.assertIn("application env/volume wiring", result["summary"])
        self.assertIn("application read behavior", result["summary"])
        self.assertFalse(volume["observed"]["mounted"])
        self.assertFalse(read["observed"]["readable"])

    def test_unreadable_application_secret_file_is_non_green(self):
        self.install_fake_api(self.api_fixture())
        self.mount.mkdir()
        self.secret_file.mkdir()

        result = self.app.secret_loading_check(self.check)

        self.assertEqual(result["state"], "red")
        read = self.assert_layer_state(result, "applicationReadBehavior", "red")
        self.assertIn("application read behavior", result["summary"])
        self.assertIn("IsADirectoryError", read["summary"])

    def test_upstream_red_blocks_top_level_green_even_when_application_read_is_green(self):
        self.install_fake_api(self.api_fixture({
            "/apis/external-secrets.io/v1/namespaces/kubecrate-status/secretstores/eso-smoke-kubernetes-store": not_ready_resource("InvalidProviderConfig", "SecretStore cannot authenticate to the Kubernetes provider."),
        }))
        self.mount.mkdir()
        self.secret_file.write_text("kubecrate-eso-smoke-ok", encoding="utf-8")

        result = self.app.secret_loading_check(self.check)

        self.assertEqual(result["state"], "red")
        self.assert_layer_state(result, "applicationReadBehavior", "green")
        self.assert_layer_state(result, "secretStoreReadiness", "red")
        self.assertIn("SecretStore or ClusterSecretStore readiness", result["summary"])
        self.assertIn("cannot authenticate", result["summary"])

    def test_status_ui_renders_secret_loading_non_green_without_contract_regression(self):
        payload = {
            "app": "kubecrate-status",
            "version": "v0.test",
            "overallStatus": "yellow",
            "healthScore": 0,
            "generatedAt": "2026-01-01T00:00:00+00:00",
            "source": "unit-test",
            "title": "Kubecrate status",
            "description": "test payload",
            "summary": {"green": 0, "red": 0, "yellow": 1, "not_configured": 0, "enabled": 1, "total": 1},
            "checks": [{
                "id": "secret-loading",
                "name": "Secret loading",
                "capability": self.check["capability"],
                "area": self.check["area"],
                "enabled": True,
                "troubleshooting": self.check["troubleshooting"],
                "state": "yellow",
                "summary": "Secret-loading is not green; likely failure areas: application env/volume wiring.",
                "observed": {"layers": {"applicationVolumeWiring": {"state": "yellow"}}},
            }],
        }

        html = self.app.render_html(payload)

        self.assertIn("Secret loading", html)
        self.assertIn("Warning", html)
        self.assertIn("/status.json", html)
        self.assertIn("application env/volume wiring", html)
        for field in ("app", "version", "overallStatus", "checks"):
            self.assertIn(field, payload)


class ManifestAlignmentTest(unittest.TestCase):
    def test_status_config_eso_helmrelease_api_path_matches_rendered_name(self):
        check = secret_loading_check_config()
        eso_layer = next(layer for layer in check["diagnosticLayers"] if layer["id"] == "esoControllerHealth")
        helm_release_text = HELM_RELEASE.read_text(encoding="utf-8")

        self.assertIn("kind: HelmRelease", helm_release_text)
        self.assertIn("  name: external-secrets\n", helm_release_text)
        self.assertIn("  namespace: core-external-secrets-operator\n", helm_release_text)
        self.assertEqual(
            eso_layer["apiPath"],
            "/apis/helm.toolkit.fluxcd.io/v2/namespaces/core-external-secrets-operator/helmreleases/external-secrets",
        )

    def test_eso_status_wiring_lives_in_kind_binding_not_generic_base(self):
        kustomization_text = KIND_STATUS_KUSTOMIZATION.read_text(encoding="utf-8")

        self.assertIn("status-config-eso-secret-loading.yaml", kustomization_text)
        self.assertIn("deployment-eso-secret-volume-patch.yaml", kustomization_text)
        self.assertIn("rbac-eso-secret-loading-patch.yaml", kustomization_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

