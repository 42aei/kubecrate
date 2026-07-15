#!/usr/bin/env python3
"""Replace only rendered Flux sync values with a disposable QA source artifact."""

import argparse
import sys

import yaml


def merge_values(base: dict, override: dict) -> dict:
    """Recursively override source selection without dropping base contracts."""
    merged = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_values(merged[key], value)
        else:
            merged[key] = value
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--values", required=True)
    args = parser.parse_args()
    with open(args.values, encoding="utf-8") as handle:
        override = yaml.safe_load(handle)
    if not isinstance(override, dict):
        raise SystemExit("QA values override must be a YAML mapping")
    documents = list(yaml.safe_load_all(sys.stdin))
    matches = 0
    for document in documents:
        if (
            isinstance(document, dict)
            and document.get("kind") == "ConfigMap"
            and document.get("metadata", {}).get("name") == "flux-sync-values"
            and document.get("metadata", {}).get("namespace") == "flux-system"
        ):
            base = yaml.safe_load(document.get("data", {}).get("values.yaml", ""))
            if not isinstance(base, dict):
                raise SystemExit("rendered ConfigMap/flux-sync-values must contain mapping values")
            values = merge_values(base, override)
            document["data"] = {"values.yaml": yaml.safe_dump(values, sort_keys=False)}
            matches += 1
    if matches != 1:
        raise SystemExit(f"expected one ConfigMap/flux-sync-values, found {matches}")
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
