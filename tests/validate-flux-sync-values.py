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
HELM_RELEASE = ROOT / "platform-services/flux/base/helm-release-sync.yaml"
CHART_VERSION = "1.14.6"


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
            "    ref:\n"
            "      branch: kubecrate-qa/exact-tree\n"
        )
        override.flush()
        exact = subprocess.run(
            [sys.executable, str(RENDERER), "--values", override.name,
             "--expected-branch", "kubecrate-qa/exact-tree"],
            input=rendered,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    values = rendered_configmap_values(exact)
    assert values["gitRepository"]["spec"]["ref"]["branch"] == "kubecrate-qa/exact-tree"
    assert values["gitRepository"]["spec"]["url"] == "ssh://git@github.com/42aei/kubecrate.git"
    assert values["kustomization"]["spec"]["path"] == "./clusters/kind-dev-misc-local/entrypoint"


def run_renderer(override: str, *, branch: str = "kubecrate-qa/exact-tree",
                 rendered: str | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as values_file:
        values_file.write(override)
        values_file.flush()
        return subprocess.run(
            [sys.executable, str(RENDERER), "--values", values_file.name,
             "--expected-branch", branch],
            input=rendered if rendered is not None else render_entrypoint(),
            check=False, text=True, capture_output=True,
        )


def test_exact_qa_renderer_rejects_every_non_source_only_override() -> None:
    invalid = {
        "credential override": "secret:\n  create: false\n",
        "unknown top key": "other: {}\n",
        "unknown nested key": "gitRepository:\n  spec:\n    ref:\n      branch: kubecrate-qa/exact-tree\n      tag: bad\n",
        "scalar spec": "gitRepository:\n  spec: bad\n",
        "scalar ref": "gitRepository:\n  spec:\n    ref: bad\n",
        "missing branch": "gitRepository:\n  spec:\n    ref: {}\n",
        "empty branch": "gitRepository:\n  spec:\n    ref:\n      branch: ''\n",
        "protected branch": "gitRepository:\n  spec:\n    ref:\n      branch: main\n",
        "branch mismatch": "gitRepository:\n  spec:\n    ref:\n      branch: kubecrate-qa/other\n",
        "malformed YAML": "gitRepository: [\n",
    }
    for label, override in invalid.items():
        result = run_renderer(override)
        assert result.returncode != 0, label
        assert result.stdout == "", label


def test_exact_qa_renderer_rejects_corrupt_repository_owned_base_types() -> None:
    rendered = render_entrypoint()
    configmap = next(
        document for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict) and document.get("kind") == "ConfigMap"
        and document.get("metadata", {}).get("name") == "flux-sync-values"
    )
    base = yaml.safe_load(configmap["data"]["values.yaml"])
    corruptions = [
        lambda value: value.update(gitRepository="bad"),
        lambda value: value["gitRepository"].update(spec="bad"),
        lambda value: value["gitRepository"]["spec"].update(ref="bad"),
        lambda value: value.update(secret="bad"),
        lambda value: value["secret"].update(generate="bad"),
        lambda value: value.update(kustomization="bad"),
        lambda value: value["kustomization"].update(spec="bad"),
    ]
    for corrupt in corruptions:
        candidate = yaml.safe_load(yaml.safe_dump(base))
        corrupt(candidate)
        configmap["data"]["values.yaml"] = yaml.safe_dump(candidate)
        candidate_render = yaml.safe_dump_all([configmap])
        result = run_renderer(
            "gitRepository:\n  spec:\n    ref:\n      branch: kubecrate-qa/exact-tree\n",
            rendered=candidate_render,
        )
        assert result.returncode != 0
        assert result.stdout == ""


def test_helm_1146_render_requests_ed25519() -> None:
    release = yaml.safe_load(HELM_RELEASE.read_text(encoding="utf-8"))
    assert release["spec"]["chart"]["spec"]["version"] == CHART_VERSION
    if not shutil.which("helm"):
        raise AssertionError("helm executable is required for pinned chart render validation")
    version = subprocess.run(
        ["helm", "version", "--short"], check=True, text=True, capture_output=True
    ).stdout.strip()
    assert version.startswith("v3."), f"Helm v3 is required, got: {version}"
    rendered = subprocess.run(
        [
            "helm", "template", "flux-system", "flux2-sync",
            "--repo", "https://fluxcd-community.github.io/helm-charts",
            "--version", CHART_VERSION, "--namespace", "flux-system", "-f", str(VALUES),
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
    assert command.count("--ssh-key-algorithm=ed25519") == 1
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
