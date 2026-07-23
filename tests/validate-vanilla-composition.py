#!/usr/bin/env python3
"""Validate the public Vanilla composition contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
VANILLA = ROOT / "compositions" / "vanilla"
KIND_ENTRYPOINT = ROOT / "clusters" / "kind-dev-misc-local" / "entrypoint"
FLUX_VALUES_SYNC = ROOT / "clusters" / "kind-dev-misc-local" / "platform-services" / "flux" / "helm-values-sync.yaml"

EXPECTED_CHILD_PATHS = {
    "external-secrets-operator": "./compositions/vanilla/platform-services/external-secrets-operator",
    "external-secrets-operator-smoke": "./compositions/vanilla/platform-services/external-secrets-operator/smoke",
    "cratecheck": "./compositions/vanilla/application-services/cratecheck",
    "envoy-gateway": "./compositions/vanilla/platform-services/envoy-gateway",
    "envoy-gateway-smoke": "./compositions/vanilla/platform-services/envoy-gateway/smoke",
    "cert-manager": "./compositions/vanilla/platform-services/cert-manager",
    "cert-manager-local-issuer": "./compositions/vanilla/platform-services/cert-manager/local-issuer",
    "kyverno": "./compositions/vanilla/platform-services/kyverno",
    "kyverno-smoke-policy": "./compositions/vanilla/platform-services/kyverno/smoke-policy",
    "kyverno-smoke": "./compositions/vanilla/platform-services/kyverno/smoke",
}
PLATFORM_SERVICES = {
    "external-secrets-operator",
    "external-secrets-operator-smoke",
    "envoy-gateway",
    "envoy-gateway-smoke",
    "cert-manager",
    "cert-manager-local-issuer",
    "kyverno",
    "kyverno-smoke-policy",
}
APPLICATION_SERVICES = {"cratecheck", "kyverno-smoke"}
FORBIDDEN_SOURCE_REFS = {"main", "master", "v1", "latest"}


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def assert_vanilla_entrypoint_contract() -> None:
    entrypoint = load_yaml(VANILLA / "entrypoint" / "kustomization.yaml")
    assert entrypoint["kind"] == "Kustomization"
    resources = set(entrypoint.get("resources", []))
    assert resources == {f"./{name}-kustomization.yaml" for name in EXPECTED_CHILD_PATHS}

    for name, expected_path in EXPECTED_CHILD_PATHS.items():
        resource = load_yaml(VANILLA / "entrypoint" / f"{name}-kustomization.yaml")
        assert resource["apiVersion"] == "kustomize.toolkit.fluxcd.io/v1", name
        assert resource["kind"] == "Kustomization", name
        assert resource["metadata"]["name"] == name
        assert resource["metadata"]["namespace"] == "flux-system"
        assert resource["spec"]["path"] == expected_path
        assert resource["spec"]["sourceRef"] == {
            "kind": "GitRepository",
            "name": "flux-system-sync",
        }
        category = resource["metadata"]["labels"]["kubecrate.io/workload-category"]
        if name in PLATFORM_SERVICES:
            assert category == "platform-services", name
        elif name in APPLICATION_SERVICES:
            assert category == "application-services", name
        else:  # pragma: no cover - protects future edits to constants
            raise AssertionError(f"unclassified Vanilla child: {name}")


def assert_kind_reference_consumes_vanilla() -> None:
    wrapper = load_yaml(KIND_ENTRYPOINT / "kustomization.yaml")
    resources = set(wrapper.get("resources", []))
    assert "../../../compositions/vanilla/entrypoint" in resources
    for name in EXPECTED_CHILD_PATHS:
        assert f"./{name}-kustomization.yaml" not in resources
        assert not (KIND_ENTRYPOINT / f"{name}-kustomization.yaml").exists()

    assert not (ROOT / "clusters/kind-dev-misc-local/application-services/cratecheck").exists()
    for service in ("external-secrets-operator", "envoy-gateway", "cert-manager", "kyverno"):
        assert not (ROOT / "clusters/kind-dev-misc-local/platform-services" / service).exists()


def assert_reusable_and_binding_boundaries() -> None:
    for service in ("external-secrets-operator", "envoy-gateway", "cert-manager", "kyverno"):
        composition_root = VANILLA / "platform-services" / service
        assert composition_root.exists(), service
        binding = (composition_root / "kustomization.yaml").read_text(encoding="utf-8")
        assert f"../../../../platform-services/{service}/base" in binding
    cratecheck = (VANILLA / "application-services" / "cratecheck" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "../../../../application-services/cratecheck/base" in cratecheck


def assert_no_temporary_or_moving_refs() -> None:
    values = yaml.safe_load(FLUX_VALUES_SYNC.read_text(encoding="utf-8"))
    ref = values["gitRepository"]["spec"].get("ref", {})
    assert ref.get("branch") == "main"  # durable post-merge default for this repository
    for path in list((ROOT / "compositions").rglob("*.yaml")) + [FLUX_VALUES_SYNC]:
        text = path.read_text(encoding="utf-8")
        for token in ("qa/", "kubecrate-e2e", "KUBECRATE_E2E_QA_BRANCH"):
            assert token not in text, f"temporary QA token {token!r} in {path.relative_to(ROOT)}"
    for path in ROOT.rglob("*.yaml"):
        if any(part in {".git", ".worktrees", ".venv"} for part in path.parts):
            continue
        if "consumer" in path.parts:
            ref = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(ref, dict):
                source_ref = ref.get("ref", {})
                assert not (set(source_ref.values()) & FORBIDDEN_SOURCE_REFS)


def main() -> int:
    assert_vanilla_entrypoint_contract()
    assert_kind_reference_consumes_vanilla()
    assert_reusable_and_binding_boundaries()
    assert_no_temporary_or_moving_refs()
    print("Vanilla composition validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
