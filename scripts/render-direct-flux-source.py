#!/usr/bin/env python3
"""Replace SSH source with HTTPS source for the direct kind+Flux E2E runner."""

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--https-url", required=True)
    parser.add_argument("--secret-name", default="flux-system-sync")
    args = parser.parse_args()
    try:
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
                values = yaml.load(encoded_values, Loader=UniqueKeyLoader)
            except yaml.YAMLError as error:
                raise ValueError(f"invalid ConfigMap/flux-sync-values values.yaml: {error}") from error
            root = require_mapping(values, "values root")
            # Replace SSH with HTTPS, disable SSH key generation.
            secret = require_mapping(root.get("secret"), "secret")
            secret["create"] = False
            secret.pop("generate", None)
            git_repo = require_mapping(root.get("gitRepository"), "gitRepository")
            spec = require_mapping(git_repo.get("spec"), "gitRepository.spec")
            spec["url"] = args.https_url
            spec["secretRef"] = {"name": args.secret_name}
            data["values.yaml"] = yaml.safe_dump(values, sort_keys=False)
            matches += 1
        if matches != 1:
            raise ValueError(f"expected one ConfigMap/flux-sync-values, found {matches}")
    except (ValueError, yaml.YAMLError) as error:
        print(f"render-direct-flux-source: ERROR: {error}", file=sys.stderr)
        return 1
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
