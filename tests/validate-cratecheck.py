#!/usr/bin/env python3
"""Validate CrateCheck application service manifests and check config.

Usage:
    python3 tests/validate-cratecheck.py
    python3 tests/validate-cratecheck.py --render  # also run kustomize build + kubeconform

Validates:
    1. check YAML parses and has required fields
    2. Kustomize build succeeds for base, cluster binding, and entrypoint
    3. kubeconform validates generated manifests (optional, requires kubeconform)
    4. RBAC rules are present and minimal with exact tuple assertions
    5. Kyverno check resource targets match expected values exactly
    6. CEL expressions use correct condition checks (not just substring matching)
    7. Regression coverage for runbook smoke-policy scoping
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = REPO_ROOT / "application-services" / "cratecheck" / "base"
CLUSTER_BINDING_DIR = (
    REPO_ROOT / "clusters" / "kind-dev-misc-local" / "application-services" / "cratecheck"
)
ENTRYPOINT_DIR = REPO_ROOT / "clusters" / "kind-dev-misc-local" / "entrypoint"

FAILURES: list[str] = []


def check(description: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {description}"
    if detail:
        line += f": {detail}"
    print(line)
    if not ok:
        FAILURES.append(description)
    return ok


def validate_status_config() -> bool:
    """Validate the CrateCheck check YAML in the ConfigMap."""
    configmap_path = BASE_DIR / "configmap.yaml"
    with open(configmap_path) as f:
        cm = yaml.safe_load(f)

    assert cm["kind"] == "ConfigMap", "Expected ConfigMap"
    assert cm["metadata"]["name"] == "cratecheck-status-config", "Expected cratecheck-status-config"

    status_yaml = cm["data"]["status.yaml"]
    status_cfg = yaml.safe_load(status_yaml)

    all_ok = True
    all_ok &= check(
        "no CRD-shaped apiVersion field",
        "apiVersion" not in status_cfg,
    )
    all_ok &= check(
        "no CRD-shaped kind field",
        "kind" not in status_cfg,
    )
    all_ok &= check(
        "interval is non-empty",
        bool(status_cfg.get("interval")),
    )
    checks = status_cfg.get("checks", [])
    all_ok &= check(
        "at least one check defined",
        len(checks) >= 1,
        f"found {len(checks)}",
    )
    check_ids: list[str] = []
    for i, c in enumerate(checks):
        prefix = f"checks[{i}]"
        for field in ("id", "name", "severity", "resource", "expression"):
            all_ok &= check(
                f"{prefix}.{field} is present",
                bool(c.get(field)),
            )
        all_ok &= check(
            f"{prefix}.severity is valid",
            c.get("severity") in ("red", "yellow", "unknown"),
            f"got {c.get('severity')}",
        )
        check_ids.append(c.get("id", ""))

    # No duplicate IDs
    ids = [c.get("id", "") for c in checks]
    all_ok &= check(
        "no duplicate check IDs",
        len(ids) == len(set(ids)),
    )

    # ---- Kyverno-specific validations ----

    # Verify Kyverno check IDs are present
    kyverno_check_ids = {
        "kyverno-helmrelease-ready",
        "kyverno-clusterpolicy-ready",
        "kyverno-smoke-namespace-exists",
    }
    present_kv_ids = kyverno_check_ids & set(ids)
    all_ok &= check(
        "Kyverno check IDs are present",
        present_kv_ids == kyverno_check_ids,
        f"missing: {kyverno_check_ids - set(ids)}",
    )

    # Assert exact resource targets for each Kyverno check
    kyverno_resource_targets = {
        "kyverno-helmrelease-ready": {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "namespace": "core-kyverno",
            "name": "kyverno",
        },
        "kyverno-clusterpolicy-ready": {
            "apiVersion": "kyverno.io/v1",
            "kind": "ClusterPolicy",
            "namespace": "",
            "name": "require-ns-label",
        },
        "kyverno-smoke-namespace-exists": {
            "apiVersion": "v1",
            "kind": "Namespace",
            "namespace": "",
            "name": "kyverno-smoke-allowed",
        },
    }
    checks_by_id = {c.get("id"): c for c in checks}
    for cid, expected in kyverno_resource_targets.items():
        c = checks_by_id.get(cid)
        label = f"Kyverno check {cid} resource target"
        if c is None:
            all_ok &= check(label, False, "check not found")
            continue
        resource = c.get("resource", {})
        for field, expected_value in expected.items():
            actual = resource.get(field)
            all_ok &= check(
                f"{label} {field}",
                actual == expected_value,
                f"expected={expected_value!r} got={actual!r}",
            )

    # Validate CEL expressions use correct condition patterns (not just substring matching)
    condition_checks = [
        "kyverno-helmrelease-ready",
        "kyverno-clusterpolicy-ready",
    ]
    for kv_check_id in condition_checks:
        kv_check = checks_by_id.get(kv_check_id)
        label = f"Kyverno check {kv_check_id} CEL expression"
        if kv_check is None:
            all_ok &= check(label, False, "check not found")
            continue
        expr = kv_check.get("expression", "")

        # Positive condition: must check c.type == 'Ready' && c.status == 'True'
        has_ready_type = "c.type == 'Ready'" in expr or 'c.type == "Ready"' in expr
        has_true_status = "c.status == 'True'" in expr or 'c.status == "True"' in expr
        all_ok &= check(
            f"{label} checks c.type == 'Ready'",
            has_ready_type,
        )
        all_ok &= check(
            f"{label} checks c.status == 'True'",
            has_true_status,
        )

        # Must use conditions.exists() pattern (not just has(status.conditions))
        has_conditions_exists = ".conditions.exists(" in expr
        all_ok &= check(
            f"{label} uses conditions.exists() pattern",
            has_conditions_exists,
        )

        # Dot notation must be used (CrateCheck contract)
        uses_dot = "c.type" in expr and "c.status" in expr
        all_ok &= check(
            f"{label} uses CrateCheck-supported dot notation",
            uses_dot,
            "bracket notation must not be used",
        )

    # Validate smoke namespace name follows kyverno-smoke-* pattern (consistent with ClusterPolicy scoping)
    smoke_ns_check = checks_by_id.get("kyverno-smoke-namespace-exists")
    if smoke_ns_check:
        ns_name = smoke_ns_check.get("resource", {}).get("name", "")
        all_ok &= check(
            "kyverno-smoke-namespace-exists resource name uses kyverno-smoke-* prefix",
            ns_name.startswith("kyverno-smoke-"),
            f"got {ns_name!r}",
        )
        # The allowed fixture namespace must carry the required label in its manifest
        ns_manifest_path = (
            REPO_ROOT
            / "clusters/kind-dev-misc-local/platform-services/kyverno/smoke"
            / "smoke-allowed-namespace.yaml"
        )
        if ns_manifest_path.exists():
            with open(ns_manifest_path) as f:
                ns_manifest = yaml.safe_load(f)
            ns_labels = ns_manifest.get("metadata", {}).get("labels", {})
            all_ok &= check(
                "allowed fixture namespace has kubecrate.io/validated=true label",
                ns_labels.get("kubecrate.io/validated") == "true",
                f"got labels={ns_labels}",
            )

    return all_ok


def validate_rbac() -> bool:
    """Validate RBAC rules are present and minimal with exact tuple assertions."""
    cr_path = BASE_DIR / "clusterrole.yaml"
    with open(cr_path) as f:
        cr = yaml.safe_load(f)

    all_ok = True
    all_ok &= check(
        "ClusterRole exists",
        cr["kind"] == "ClusterRole",
    )
    rules = cr.get("rules", [])
    all_ok &= check(
        "ClusterRole has rules",
        len(rules) > 0,
    )

    # Check for discovery access
    has_discovery = any(
        r.get("nonResourceURLs")
        for r in rules
    )
    all_ok &= check(
        "ClusterRole includes discovery API access",
        has_discovery,
    )

    # Exact RBAC tuple assertions for Kyverno resources
    # Map each expected tuple to the resource type name for readable output
    expected_tuples = [
        {
            "apiGroup": "helm.toolkit.fluxcd.io",
            "resources": ["helmreleases"],
            "verbs": ["get"],
            "label": "HelmRelease read access",
        },
        {
            "apiGroup": "kyverno.io",
            "resources": ["clusterpolicies"],
            "verbs": ["get"],
            "label": "ClusterPolicy read access",
        },
    ]

    for expected in expected_tuples:
        found = False
        for rule in rules:
            api_groups = rule.get("apiGroups", [])
            resources = rule.get("resources", [])
            verbs = rule.get("verbs", [])
            if (
                expected["apiGroup"] in api_groups
                and set(expected["resources"]) <= set(resources)
                and set(expected["verbs"]) <= set(verbs)
            ):
                found = True
                break

        # Build detail for failure
        all_ok &= check(
            f"ClusterRole grants exact {expected['label']}",
            found,
            f"expected apiGroup={expected['apiGroup']!r} resources={expected['resources']} verbs={expected['verbs']}",
        )

    # Verify ClusterRoleBinding exists and references correct ServiceAccount
    crb_path = BASE_DIR / "clusterrolebinding.yaml"
    with open(crb_path) as f:
        crb = yaml.safe_load(f)
    all_ok &= check(
        "ClusterRoleBinding references cratecheck ServiceAccount",
        crb.get("subjects", [{}])[0].get("name") == "cratecheck",
    )

    # Verify no wildcard verbs or resources (security regression)
    for i, rule in enumerate(rules):
        verbs = rule.get("verbs", [])
        if "*" in verbs:
            all_ok &= check(
                f"ClusterRole rule[{i}] has no wildcard verbs",
                False,
                f"verbs={verbs}",
            )

    return all_ok


def validate_deployment() -> bool:
    """Validate the Deployment references the correct image and ConfigMap."""
    deploy_path = BASE_DIR / "deployment.yaml"
    with open(deploy_path) as f:
        deploy = yaml.safe_load(f)

    all_ok = True
    containers = deploy["spec"]["template"]["spec"]["containers"]
    all_ok &= check(
        "Deployment has at least one container",
        len(containers) >= 1,
    )
    container = containers[0]
    image = container.get("image", "")
    all_ok &= check(
        "Container references CrateCheck v1 semantic image tag",
        image == "ghcr.io/42aei/cratecheck:v1",
        image or "MISSING",
    )
    all_ok &= check(
        "No imagePullSecrets in pod spec",
        "imagePullSecrets" not in deploy["spec"]["template"]["spec"],
    )
    # ConfigMap volume mount
    volumes = deploy["spec"]["template"]["spec"].get("volumes", [])
    has_config_volume = any(
        v.get("configMap", {}).get("name") == "cratecheck-status-config"
        for v in volumes
    )
    all_ok &= check(
        "Deployment mounts cratecheck-status-config ConfigMap",
        has_config_volume,
    )
    return all_ok


def validate_smoke_policy_scoping() -> bool:
    """Validate smoke ClusterPolicy is scoped to kyverno-smoke-* namespaces only."""
    all_ok = True

    policy_paths = [
        REPO_ROOT
        / "clusters/kind-dev-misc-local/platform-services/kyverno/smoke"
        / "require-ns-label-policy.yaml",
        REPO_ROOT
        / "clusters/kind-dev-misc-local/platform-services/kyverno/smoke-policy"
        / "require-ns-label-policy.yaml",
    ]

    for policy_path in policy_paths:
        if not policy_path.exists():
            continue
        with open(policy_path) as f:
            policy = yaml.safe_load(f)

        label = f"ClusterPolicy ({policy_path.relative_to(REPO_ROOT)})"

        all_ok &= check(
            f"{label} uses Enforce mode",
            policy.get("spec", {}).get("validationFailureAction") == "Enforce",
        )

        rules = policy.get("spec", {}).get("rules", [])
        if not rules:
            all_ok &= check(f"{label} has rules", False)
            continue

        rule = rules[0]
        match_any = rule.get("match", {}).get("any", [])

        # Verify match is scoped to kyverno-smoke-* names only
        names_scoped = False
        for m in match_any:
            resources = m.get("resources", {})
            names = resources.get("names", [])
            if "kyverno-smoke-*" in names:
                names_scoped = True
                break

        all_ok &= check(
            f"{label} match is scoped to kyverno-smoke-* names",
            names_scoped,
            "policy must not match all Namespaces cluster-wide",
        )

        # Verify the policy message references the expected label
        message = rule.get("validate", {}).get("message", "")
        all_ok &= check(
            f"{label} deny message references kubecrate.io/validated label",
            "kubecrate.io/validated" in message,
            f"got message={message!r}",
        )

    return all_ok


def validate_entrypoint_ordering() -> bool:
    """Validate the entrypoint Kustomization ordering for Kyverno smoke."""
    all_ok = True

    entrypoint_path = ENTRYPOINT_DIR / "kustomization.yaml"
    with open(entrypoint_path) as f:
        ep = yaml.safe_load(f)

    resources = ep.get("resources", [])
    all_ok &= check(
        "Entrypoint includes kyverno-kustomization.yaml",
        "./kyverno-kustomization.yaml" in resources,
    )
    all_ok &= check(
        "Entrypoint includes kyverno-smoke-policy-kustomization.yaml",
        "./kyverno-smoke-policy-kustomization.yaml" in resources,
    )
    all_ok &= check(
        "Entrypoint includes kyverno-smoke-kustomization.yaml",
        "./kyverno-smoke-kustomization.yaml" in resources,
    )

    # Verify ordering: kyverno before smoke-policy before smoke
    kv_idx = resources.index("./kyverno-kustomization.yaml") if "./kyverno-kustomization.yaml" in resources else -1
    sp_idx = resources.index("./kyverno-smoke-policy-kustomization.yaml") if "./kyverno-smoke-policy-kustomization.yaml" in resources else -1
    s_idx = resources.index("./kyverno-smoke-kustomization.yaml") if "./kyverno-smoke-kustomization.yaml" in resources else -1
    all_ok &= check(
        "Entrypoint ordering: kyverno before smoke-policy",
        kv_idx >= 0 and sp_idx >= 0 and kv_idx < sp_idx,
        f"kyverno index={kv_idx}, smoke-policy index={sp_idx}",
    )
    all_ok &= check(
        "Entrypoint ordering: smoke-policy before smoke",
        sp_idx >= 0 and s_idx >= 0 and sp_idx < s_idx,
        f"smoke-policy index={sp_idx}, smoke index={s_idx}",
    )

    # Verify smoke-policy Kustomization dependsOn kyverno
    sp_k_path = ENTRYPOINT_DIR / "kyverno-smoke-policy-kustomization.yaml"
    if sp_k_path.exists():
        with open(sp_k_path) as f:
            sp_k = yaml.safe_load(f)
        depends_on = sp_k.get("spec", {}).get("dependsOn", [])
        all_ok &= check(
            "kyverno-smoke-policy dependsOn kyverno",
            any(d.get("name") == "kyverno" for d in depends_on),
            f"dependsOn={depends_on}",
        )

    # Verify smoke Kustomization dependsOn smoke-policy
    s_k_path = ENTRYPOINT_DIR / "kyverno-smoke-kustomization.yaml"
    if s_k_path.exists():
        with open(s_k_path) as f:
            s_k = yaml.safe_load(f)
        depends_on = s_k.get("spec", {}).get("dependsOn", [])
        all_ok &= check(
            "kyverno-smoke dependsOn kyverno-smoke-policy",
            any(d.get("name") == "kyverno-smoke-policy" for d in depends_on),
            f"dependsOn={depends_on}",
        )

    return all_ok


def run_kustomize_build(path: Path, label: str) -> bool:
    """Run kustomize build and return success."""
    result = subprocess.run(
        ["kustomize", "build", str(path)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    return check(
        f"kustomize build {label}",
        result.returncode == 0,
        result.stderr.strip()[:120] if result.returncode != 0 else "",
    )


def run_kubeconform(label: str) -> bool:
    """Run kubeconform against the entrypoint build output."""
    kustomize = subprocess.run(
        ["kustomize", "build", str(ENTRYPOINT_DIR)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if kustomize.returncode != 0:
        return check(f"kubeconform {label}", False, "kustomize build failed")
    result = subprocess.run(
        ["kubeconform", "-ignore-missing-schemas", "-summary"],
        input=kustomize.stdout, capture_output=True, text=True,
    )
    # Extract summary
    ok = "Invalid: 0" in result.stdout and "Errors: 0" in result.stdout
    return check(
        f"kubeconform {label}",
        ok,
        result.stdout.strip().split("\n")[-1] if result.stdout else "",
    )


def main():
    parser = argparse.ArgumentParser(description="Validate CrateCheck manifests")
    parser.add_argument("--render", action="store_true", help="Run kustomize build + kubeconform")
    args = parser.parse_args()

    print("=== CrateCheck check config validation ===")
    cfg_ok = validate_status_config()

    print("\n=== CrateCheck RBAC validation ===")
    rbac_ok = validate_rbac()

    print("\n=== CrateCheck Deployment validation ===")
    deploy_ok = validate_deployment()

    print("\n=== Smoke ClusterPolicy scoping validation ===")
    policy_ok = validate_smoke_policy_scoping()

    print("\n=== Entrypoint ordering validation ===")
    ordering_ok = validate_entrypoint_ordering()

    if args.render:
        print("\n=== Kustomize build validation ===")
        base_ok = run_kustomize_build(BASE_DIR, "base")
        binding_ok = run_kustomize_build(CLUSTER_BINDING_DIR, "cluster-binding")
        smoke_policy_ok = run_kustomize_build(
            REPO_ROOT / "clusters/kind-dev-misc-local/platform-services/kyverno/smoke-policy",
            "smoke-policy",
        )
        entrypoint_ok = run_kustomize_build(ENTRYPOINT_DIR, "entrypoint")

        print("\n=== kubeconform schema validation ===")
        kubeconform_ok = run_kubeconform("entrypoint")

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S):")
        for f_item in FAILURES:
            print(f"  - {f_item}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
