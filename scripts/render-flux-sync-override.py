#!/usr/bin/env python3
"""Render the flux-sync-values-override ConfigMap.

Reads the base helm-values-sync.yaml and, if FLUX_GIT_BRANCH_OVERRIDE is
set in the environment, writes a ConfigMap to stdout with the overridden
branch. Without the override, writes the identity ConfigMap (empty values).
"""

import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_VALUES_PATH = (
    REPO_ROOT
    / "clusters"
    / "kind-dev-misc-local"
    / "platform-services"
    / "flux"
    / "helm-values-sync.yaml"
)


def main():
    # Read base sync values to extract the canonical branch
    with open(SYNC_VALUES_PATH) as f:
        base_values = yaml.safe_load(f)

    canonical_branch = (
        base_values.get("gitRepository", {})
        .get("spec", {})
        .get("ref", {})
        .get("branch", "")
    )

    override_branch = os.environ.get("FLUX_GIT_BRANCH_OVERRIDE", "").strip()

    if override_branch and override_branch != canonical_branch:
        override_values = {
            "gitRepository": {
                "spec": {
                    "ref": {
                        "branch": override_branch,
                    }
                }
            }
        }
    else:
        override_values = {}
        # Empty override: no-op. The optional valuesFrom on the HelmRelease
        # will skip this ConfigMap when it carries only an empty dict.

    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "flux-sync-values-override",
            "namespace": "flux-system",
            "labels": {
                "app.kubernetes.io/name": "flux-system-sync",
                "app.kubernetes.io/part-of": "kubecrate",
            },
        },
        "data": {
            "values.yaml": yaml.dump(override_values, default_flow_style=False),
        },
    }

    yaml.dump(cm, sys.stdout, default_flow_style=False)
    print(end="")  # trailing newline


if __name__ == "__main__":
    main()
