#!/usr/bin/env python3
"""Replace only rendered Flux sync values with a disposable QA source artifact."""

import argparse
import sys

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--values", required=True)
    args = parser.parse_args()
    with open(args.values, encoding="utf-8") as handle:
        values = handle.read()
    documents = list(yaml.safe_load_all(sys.stdin))
    matches = 0
    for document in documents:
        if (
            isinstance(document, dict)
            and document.get("kind") == "ConfigMap"
            and document.get("metadata", {}).get("name") == "flux-sync-values"
            and document.get("metadata", {}).get("namespace") == "flux-system"
        ):
            document["data"] = {"values.yaml": values}
            matches += 1
    if matches != 1:
        raise SystemExit(f"expected one ConfigMap/flux-sync-values, found {matches}")
    yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
