#!/usr/bin/env python3
"""Replace only the source branch in rendered Flux sync values for exact-tree QA."""

import argparse
import re
import sys
from typing import Any

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that also rejects ambiguous duplicate mapping keys."""


def construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode,
                             deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


def require_mapping(value: Any, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return value


def require_exact_keys(value: dict[Any, Any], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{path} must contain exactly: {', '.join(sorted(expected))}")


def load_override(path: str, expected_branch: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            override = yaml.load(handle, Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot load QA values override: {error}") from error

    root = require_mapping(override, "QA values override")
    require_exact_keys(root, {"gitRepository"}, "QA values override")
    repository = require_mapping(root["gitRepository"], "gitRepository")
    require_exact_keys(repository, {"spec"}, "gitRepository")
    spec = require_mapping(repository["spec"], "gitRepository.spec")
    require_exact_keys(spec, {"ref"}, "gitRepository.spec")
    ref = require_mapping(spec["ref"], "gitRepository.spec.ref")
    require_exact_keys(ref, {"branch"}, "gitRepository.spec.ref")
    branch = ref["branch"]
    if not isinstance(branch, str) or not branch:
        raise ValueError("gitRepository.spec.ref.branch must be a nonempty string")
    if not re.fullmatch(r"kubecrate-qa/[A-Za-z0-9._/-]+", branch) or any(
        token in branch for token in ("..", "//", "@{")
    ) or branch.endswith(("/", ".", ".lock")):
        raise ValueError("gitRepository.spec.ref.branch must be a valid kubecrate-qa/* branch")
    if branch != expected_branch:
        raise ValueError("QA values branch does not match --expected-branch")
    return branch


def validate_base_values(value: Any) -> dict[Any, Any]:
    root = require_mapping(value, "rendered values root")
    repository = require_mapping(root.get("gitRepository"), "gitRepository")
    spec = require_mapping(repository.get("spec"), "gitRepository.spec")
    require_mapping(spec.get("ref"), "gitRepository.spec.ref")
    secret = require_mapping(root.get("secret"), "secret")
    require_mapping(secret.get("generate"), "secret.generate")
    kustomization = require_mapping(root.get("kustomization"), "kustomization")
    require_mapping(kustomization.get("spec"), "kustomization.spec")
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--values", required=True)
    parser.add_argument("--expected-branch", required=True)
    args = parser.parse_args()
    try:
        branch = load_override(args.values, args.expected_branch)
        documents = list(yaml.load_all(sys.stdin, Loader=UniqueKeyLoader))
        matches = 0
        for document in documents:
            if not isinstance(document, dict) or document.get("kind") != "ConfigMap":
                continue
            metadata = document.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if metadata.get("name") != "flux-sync-values" or metadata.get("namespace") != "flux-system":
                continue
            data = require_mapping(document.get("data"), "ConfigMap/flux-sync-values.data")
            encoded_values = data.get("values.yaml")
            if not isinstance(encoded_values, str):
                raise ValueError("ConfigMap/flux-sync-values data.values.yaml must be a string")
            try:
                values = validate_base_values(yaml.load(encoded_values, Loader=UniqueKeyLoader))
            except yaml.YAMLError as error:
                raise ValueError(f"invalid ConfigMap/flux-sync-values values.yaml: {error}") from error
            values["gitRepository"]["spec"]["ref"]["branch"] = branch
            data["values.yaml"] = yaml.safe_dump(values, sort_keys=False)
            matches += 1
        if matches != 1:
            raise ValueError(f"expected one ConfigMap/flux-sync-values, found {matches}")
    except (ValueError, yaml.YAMLError) as error:
        print(f"render-final-qa-flux-source: ERROR: {error}", file=sys.stderr)
        return 1
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
