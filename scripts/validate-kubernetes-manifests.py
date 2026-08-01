#!/usr/bin/env python3
"""Validate Kubernetes YAML and Kustomize render output for kubecrate.

This script focuses on repository YAML shape, Kustomize renderability, and
Kubernetes manifest schema validation suitable for CI and pre-PR checks.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
KUSTOMIZATION_API = "kustomize.config.k8s.io/"
KUBERNETES_API_PATTERN = re.compile(r"^(?:[a-z0-9.-]+/)?v[0-9](?:[a-z0-9]+)?$")
SKIP_DIRS = {".git", ".worktrees", ".venv", "node_modules"}
KUSTOMIZE_ROOTS = (
    "platform-services/flux/base",
    "platform-services/envoy-gateway/base",
    "platform-services/cert-manager/base",
    "platform-services/kyverno/base",
    "application-services/cratecheck/base",
)


def run(cmd: list[str], *, cwd: pathlib.Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def require_tool(name: str) -> None:
    result = run(["bash", "-lc", f"command -v {name}"])
    if result.returncode != 0:
        print(result.stdout, end="")
        raise SystemExit(f"Required tool not found on PATH: {name}")


def yaml_files() -> Iterable[pathlib.Path]:
    for path in REPO_ROOT.rglob("*"):
        rel_parts = path.relative_to(REPO_ROOT).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.is_file() and path.suffix in {".yaml", ".yml"}:
            yield path


def parse_yaml_documents(path: pathlib.Path) -> list[object]:
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        return list(yaml.safe_load_all(handle))


def validate_yaml_parse() -> None:
    print("\n== YAML parse ==")
    failed = False
    files = sorted(yaml_files())
    for path in files:
        rel = path.relative_to(REPO_ROOT)
        try:
            parse_yaml_documents(path)
            print(f"ok {rel}")
        except Exception as exc:  # noqa: BLE001 - report all parser failures in CI
            failed = True
            print(f"FAIL {rel}: {exc}")
    if failed:
        raise SystemExit("YAML parse failed")
    print(f"Parsed {len(files)} YAML files")


def is_kubernetes_manifest(doc: object) -> bool:
    if not isinstance(doc, dict):
        return False
    api_version = doc.get("apiVersion")
    kind = doc.get("kind")
    if not isinstance(api_version, str) or not isinstance(kind, str):
        return False
    if api_version.startswith(KUSTOMIZATION_API):
        return False
    if not KUBERNETES_API_PATTERN.match(api_version):
        return False
    return True


def validate_source_manifests() -> None:
    print("\n== kubeconform source manifests ==")
    docs: list[str] = []
    for path in sorted(yaml_files()):
        rel = path.relative_to(REPO_ROOT)
        for doc in parse_yaml_documents(path):
            if is_kubernetes_manifest(doc):
                import yaml

                docs.append(f"---\n# Source: {rel}\n" + yaml.safe_dump(doc, sort_keys=False))
    if not docs:
        print("No source Kubernetes manifests detected")
        return
    result = run(
        [
            "kubeconform",
            "-strict",
            "-summary",
            "-ignore-missing-schemas",
        ],
        input_text="\n".join(docs),
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        raise SystemExit("kubeconform source manifest validation failed")


def validate_kustomize_roots() -> None:
    print("\n== kustomize render + kubeconform ==")
    kubectl = shutil.which("kubectl")
    kustomize = shutil.which("kustomize")
    if not kubectl and not kustomize:
        raise SystemExit("Required tool not found on PATH: kubectl or kustomize")
    render_cmd = [kubectl, "kustomize"] if kubectl else [kustomize, "build"]
    for root in KUSTOMIZE_ROOTS:
        path = REPO_ROOT / root
        if not path.exists():
            raise SystemExit(f"Expected kustomize root does not exist: {root}")
        render = run([*render_cmd, root])
        if render.stdout:
            print(f"rendered {len(render.stdout.splitlines())} lines from {root}")
        if render.returncode != 0:
            print(render.stdout, end="")
            raise SystemExit(f"kubectl kustomize failed for {root}")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write(render.stdout)
            rendered_path = handle.name
        try:
            conform = run(
                [
                    "kubeconform",
                    "-strict",
                    "-summary",
                    "-ignore-missing-schemas",
                    rendered_path,
                ]
            )
            print(conform.stdout, end="")
            if conform.returncode != 0:
                raise SystemExit(f"kubeconform rendered manifest validation failed for {root}")
        finally:
            os.unlink(rendered_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tool-check", action="store_true")
    parser.add_argument(
        "--check",
        choices=("all", "yaml", "source-manifests", "kustomize"),
        default="all",
        help="Run one validation group. Use 'all' for the full CI suite.",
    )
    args = parser.parse_args()

    if not args.skip_tool_check:
        if args.check in {"all", "source-manifests", "kustomize"}:
            require_tool("kubeconform")
        if args.check in {"all", "kustomize"} and not shutil.which("kubectl") and not shutil.which("kustomize"):
            raise SystemExit("Required tool not found on PATH: kubectl or kustomize")

    if args.check in {"all", "yaml"}:
        validate_yaml_parse()
    if args.check in {"all", "source-manifests"}:
        validate_source_manifests()
    if args.check in {"all", "kustomize"}:
        validate_kustomize_roots()


if __name__ == "__main__":
    main()
