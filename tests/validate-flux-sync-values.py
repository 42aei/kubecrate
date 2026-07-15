#!/usr/bin/env python3
"""Semantic contracts for Flux sync credential generation and QA rendering."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VALUES = ROOT / "clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync.yaml"
ENTRYPOINT = ROOT / "clusters/kind-dev-misc-local/entrypoint"
RENDERER = ROOT / "scripts/render-final-qa-flux-source.py"


def load_values(text: str) -> dict:
    values = yaml.safe_load(text)
    assert isinstance(values, dict)
    assert values.get("secret", {}).get("create") is True
    assert values.get("secret", {}).get("generate", {}).get("sshKeyAlgorithm") == "ed25519"
    return values


def rendered_configmap_values(rendered: str) -> dict:
    matches = [
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict)
        and document.get("kind") == "ConfigMap"
        and document.get("metadata", {}).get("name") == "flux-sync-values"
        and document.get("metadata", {}).get("namespace") == "flux-system"
    ]
    assert len(matches) == 1
    return load_values(matches[0]["data"]["values.yaml"])


def render_entrypoint() -> str:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    return subprocess.run(
        [*command, str(ENTRYPOINT)], check=True, text=True, capture_output=True
    ).stdout


def test_repository_and_kustomize_values_request_ed25519() -> None:
    load_values(VALUES.read_text(encoding="utf-8"))
    rendered_configmap_values(render_entrypoint())


def test_exact_qa_renderer_preserves_ed25519_when_overriding_source() -> None:
    rendered = render_entrypoint()
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as override:
        override.write(
            "gitRepository:\n"
            "  spec:\n"
            "    url: ssh://git@github.com/42aei/kubecrate.git\n"
            "    ref:\n"
            "      branch: kubecrate-qa/exact-tree\n"
        )
        override.flush()
        exact = subprocess.run(
            [sys.executable, str(RENDERER), "--values", override.name],
            input=rendered,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    values = rendered_configmap_values(exact)
    assert values["gitRepository"]["spec"]["ref"]["branch"] == "kubecrate-qa/exact-tree"


def test_helm_1146_render_requests_ed25519() -> None:
    rendered = subprocess.run(
        [
            "helm", "template", "flux-system", "flux2-sync",
            "--repo", "https://fluxcd-community.github.io/helm-charts",
            "--version", "1.14.6", "--namespace", "flux-system", "-f", str(VALUES),
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
    assert "--ssh-key-algorithm=ed25519" in command
    assert "--ssh-key-algorithm=ecdsa" not in command


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--helm-render", action="store_true")
    args = parser.parse_args()
    test_repository_and_kustomize_values_request_ed25519()
    test_exact_qa_renderer_preserves_ed25519_when_overriding_source()
    if args.helm_render:
        test_helm_1146_render_requests_ed25519()
    print("Flux sync values validation passed")
