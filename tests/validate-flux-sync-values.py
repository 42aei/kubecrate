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
SYNC_NAME = "flux-system-sync"
SYNC_NAMESPACE = "flux-system"


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
        "null root": "null\n",
        "list root": "[]\n",
        "scalar root": "bad\n",
        "credential override": "secret:\n  create: false\n",
        "unknown top key": "other: {}\n",
        "unknown nested key": "gitRepository:\n  spec:\n    ref:\n      branch: kubecrate-qa/exact-tree\n      tag: bad\n",
        "duplicate key": "gitRepository:\n  spec:\n    ref:\n      branch: kubecrate-qa/exact-tree\n      branch: kubecrate-qa/exact-tree\n",
        "null repository": "gitRepository: null\n",
        "list repository": "gitRepository: []\n",
        "scalar spec": "gitRepository:\n  spec: bad\n",
        "null spec": "gitRepository:\n  spec: null\n",
        "list spec": "gitRepository:\n  spec: []\n",
        "scalar ref": "gitRepository:\n  spec:\n    ref: bad\n",
        "null ref": "gitRepository:\n  spec:\n    ref: null\n",
        "list ref": "gitRepository:\n  spec:\n    ref: []\n",
        "missing branch": "gitRepository:\n  spec:\n    ref: {}\n",
        "empty branch": "gitRepository:\n  spec:\n    ref:\n      branch: ''\n",
        "null branch": "gitRepository:\n  spec:\n    ref:\n      branch: null\n",
        "list branch": "gitRepository:\n  spec:\n    ref:\n      branch: []\n",
        "scalar branch": "gitRepository:\n  spec:\n    ref:\n      branch: 17\n",
        "protected branch": "gitRepository:\n  spec:\n    ref:\n      branch: main\n",
        "branch mismatch": "gitRepository:\n  spec:\n    ref:\n      branch: kubecrate-qa/other\n",
        "malformed YAML": "gitRepository: [\n",
    }
    for label, override in invalid.items():
        result = run_renderer(override)
        assert result.returncode != 0, label
        assert result.stdout == "", label


def test_exact_qa_renderer_uses_git_branch_ref_format_semantics() -> None:
    invalid_branches = [
        "kubecrate-qa/.foo",
        "kubecrate-qa/foo.lock/bar",
        "kubecrate-qa/foo..bar",
        "kubecrate-qa/foo@{bar",
        "kubecrate-qa/foo.",
        "kubecrate-qa/foo/",
        "kubecrate-qa/foo//bar",
        "kubecrate-qa/foo\\bar",
        "kubecrate-qa/foo:bar",
        "kubecrate-qa/foo?bar",
        "kubecrate-qa/foo*bar",
        "kubecrate-qa/foo[bar",
        "kubecrate-qa/foo bar",
        "kubecrate-qa/foo\x01bar",
        "@",
        "/kubecrate-qa/foo",
        "kubecrate-qa",
    ]
    for branch in invalid_branches:
        if branch.startswith("kubecrate-qa/"):
            git_result = subprocess.run(
                ["git", "check-ref-format", "--branch", branch],
                check=False, text=True, capture_output=True,
            )
            assert git_result.returncode != 0, branch
        override = yaml.safe_dump(
            {"gitRepository": {"spec": {"ref": {"branch": branch}}}},
            sort_keys=False,
        )
        result = run_renderer(override, branch=branch)
        assert result.returncode != 0, branch
        assert result.stdout == "", branch

    for branch in ("kubecrate-qa/exact-tree", "kubecrate-qa/review_17/v2"):
        subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            check=True, text=True, capture_output=True,
        )
        result = run_renderer(
            yaml.safe_dump(
                {"gitRepository": {"spec": {"ref": {"branch": branch}}}},
                sort_keys=False,
            ),
            branch=branch,
        )
        assert result.returncode == 0, result.stderr


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


def test_helm_1146_render_matches_generated_sync_resource_contract() -> None:
    release = yaml.safe_load(HELM_RELEASE.read_text(encoding="utf-8"))
    assert release["spec"]["chart"]["spec"]["version"] == CHART_VERSION
    assert release["metadata"]["name"] == SYNC_NAME
    assert release["metadata"]["namespace"] == SYNC_NAMESPACE
    assert release["spec"]["releaseName"] == SYNC_NAME
    if not shutil.which("helm"):
        raise AssertionError("helm executable is required for pinned chart render validation")
    version = subprocess.run(
        ["helm", "version", "--short"], check=True, text=True, capture_output=True
    ).stdout.strip()
    assert version.startswith("v3."), f"Helm v3 is required, got: {version}"
    rendered = subprocess.run(
        [
            "helm", "template", SYNC_NAME, "flux2-sync",
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
    create_secret = ["create", "secret", "git", SYNC_NAME]
    assert any(command[index:index + len(create_secret)] == create_secret
               for index in range(len(command) - len(create_secret) + 1))
    assert command.count(f"--namespace={SYNC_NAMESPACE}") == 1
    assert command.count("--ssh-key-algorithm=ed25519") == 1
    assert "--ssh-key-algorithm=ecdsa" not in command
    for kind in ("GitRepository", "Kustomization"):
        matches = [
            document for document in yaml.safe_load_all(rendered)
            if isinstance(document, dict) and document.get("kind") == kind
        ]
        assert len(matches) == 1
        assert matches[0]["metadata"]["name"] == SYNC_NAME
        assert matches[0]["metadata"]["namespace"] == SYNC_NAMESPACE


CONTRACT_CHECKS = (
    test_repository_and_kustomize_values_request_ed25519,
    test_exact_qa_renderer_preserves_ed25519_when_overriding_source,
    test_exact_qa_renderer_rejects_every_non_source_only_override,
    test_exact_qa_renderer_uses_git_branch_ref_format_semantics,
    test_exact_qa_renderer_rejects_corrupt_repository_owned_base_types,
)
EXPECTED_CONTRACT_CHECKS = (
    "test_repository_and_kustomize_values_request_ed25519",
    "test_exact_qa_renderer_preserves_ed25519_when_overriding_source",
    "test_exact_qa_renderer_rejects_every_non_source_only_override",
    "test_exact_qa_renderer_uses_git_branch_ref_format_semantics",
    "test_exact_qa_renderer_rejects_corrupt_repository_owned_base_types",
)


def run_all_contract_checks(checks=CONTRACT_CHECKS) -> None:
    actual = tuple(check.__name__ for check in checks)
    assert actual == EXPECTED_CONTRACT_CHECKS, (
        f"contract check registry mismatch: expected {EXPECTED_CONTRACT_CHECKS}, "
        f"got {actual}"
    )
    for check in checks:
        check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--helm-render", action="store_true")
    args = parser.parse_args()
    run_all_contract_checks()
    if args.helm_render:
        test_helm_1146_render_matches_generated_sync_resource_contract()
    print("Flux sync values validation passed")
