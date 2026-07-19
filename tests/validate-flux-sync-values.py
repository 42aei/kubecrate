#!/usr/bin/env python3
"""Validate the repository-owned Flux sync values used by local and direct E2E paths."""

import argparse
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VALUES = ROOT / "clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync.yaml"
ENTRYPOINT = ROOT / "clusters/kind-dev-misc-local/entrypoint"
HELM_RELEASE = ROOT / "platform-services/flux/base/helm-release-sync.yaml"
CHART_VERSION = "1.14.6"
SYNC_NAME = "flux-system-sync"
SYNC_NAMESPACE = "flux-system"


def load_values(text: str) -> dict:
    values = yaml.safe_load(text)
    assert isinstance(values, dict)
    assert values.get("secret", {}).get("create") is True
    assert values.get("secret", {}).get("generate", {}).get("sshKeyAlgorithm") == "ed25519"
    assert values.get("gitRepository", {}).get("spec", {}).get("ref", {}).get("branch") == "main"
    return values


def render_entrypoint() -> str:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    return subprocess.run(
        [*command, str(ENTRYPOINT)], check=True, text=True, capture_output=True
    ).stdout


def rendered_configmap_values(rendered: str) -> dict:
    matches = [
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict)
        and document.get("kind") == "ConfigMap"
        and document.get("metadata", {}).get("name") == "flux-sync-values"
        and document.get("metadata", {}).get("namespace") == SYNC_NAMESPACE
    ]
    assert len(matches) == 1
    return load_values(matches[0]["data"]["values.yaml"])


def validate_repository_contract() -> None:
    load_values(VALUES.read_text(encoding="utf-8"))
    rendered = render_entrypoint()
    rendered_configmap_values(rendered)
    expected_names = {
        "cratecheck",
        "external-secrets-operator",
        "external-secrets-operator-smoke",
    }
    children = {
        document.get("metadata", {}).get("name"): document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict)
        and document.get("apiVersion") == "kustomize.toolkit.fluxcd.io/v1"
        and document.get("kind") == "Kustomization"
    }
    assert set(children) == expected_names
    for name, child in children.items():
        metadata = child.get("metadata", {})
        source_ref = child.get("spec", {}).get("sourceRef", {})
        assert metadata.get("namespace") == SYNC_NAMESPACE, name
        assert source_ref.get("kind") == "GitRepository", name
        assert source_ref.get("name") == SYNC_NAME, name
        assert source_ref.get("namespace", SYNC_NAMESPACE) == SYNC_NAMESPACE, name


def validate_helm_render() -> None:
    release = yaml.safe_load(HELM_RELEASE.read_text(encoding="utf-8"))
    assert release["spec"]["chart"]["spec"]["version"] == CHART_VERSION
    assert release["metadata"]["name"] == SYNC_NAME
    assert release["metadata"]["namespace"] == SYNC_NAMESPACE
    assert release["spec"]["releaseName"] == SYNC_NAME
    if not shutil.which("helm"):
        raise AssertionError("helm executable is required for pinned chart render validation")
    rendered = subprocess.run(
        [
            "helm", "template", SYNC_NAME, "flux2-sync",
            "--repo", "https://fluxcd-community.github.io/helm-charts",
            "--version", CHART_VERSION, "--namespace", SYNC_NAMESPACE, "-f", str(VALUES),
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    jobs = [
        document for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict) and document.get("kind") == "Job"
    ]
    assert len(jobs) == 1
    command = jobs[0]["spec"]["template"]["spec"]["containers"][0]["command"]
    create_secret = ["create", "secret", "git", SYNC_NAME]
    assert any(
        command[index:index + len(create_secret)] == create_secret
        for index in range(len(command) - len(create_secret) + 1)
    )
    assert command.count(f"--namespace={SYNC_NAMESPACE}") == 1
    assert command.count("--ssh-key-algorithm=ed25519") == 1
    for kind in ("GitRepository", "Kustomization"):
        matches = [
            document for document in yaml.safe_load_all(rendered)
            if isinstance(document, dict) and document.get("kind") == kind
        ]
        assert len(matches) == 1
        assert matches[0]["metadata"]["name"] == SYNC_NAME
        assert matches[0]["metadata"]["namespace"] == SYNC_NAMESPACE


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--helm-render", action="store_true")
    args = parser.parse_args()
    validate_repository_contract()
    if args.helm_render:
        validate_helm_render()
    print("Flux sync values validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
