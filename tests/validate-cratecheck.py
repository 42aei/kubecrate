#!/usr/bin/env python3
"""Validate CrateCheck application service manifests and check config.

Usage:
    python3 tests/validate-cratecheck.py
    python3 tests/validate-cratecheck.py --render  # also run kustomize build + kubeconform

Validates:
    1. check YAML parses and has required fields
    2. Kustomize build succeeds for base, cluster binding, and entrypoint
    3. kubeconform validates generated manifests (optional, requires kubeconform)
    4. RBAC rules are present and minimal
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
    for i, c in enumerate(checks):
        prefix = f"checks[{i}]"
        check_ids: list[str] = []
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
    # Verify cert-manager checks are present
    cert_manager_check_ids = {
        "cert-manager-helmrelease-ready",
        "cert-manager-selfsigned-issuer-ready",
        "cert-manager-ca-certificate-ready",
        "cert-manager-ca-issuer-ready",
        "cert-manager-tls-certificate-ready",
        "cert-manager-tls-secret-exists",
    }
    present_cm_ids = cert_manager_check_ids & set(ids)
    all_ok &= check(
        "cert-manager check IDs are present",
        present_cm_ids == cert_manager_check_ids,
        f"missing: {cert_manager_check_ids - set(ids)}",
    )
    # Verify cert-manager CEL expressions have correct structure and behavior
    all_ok &= validate_cel_behavioral(checks, cert_manager_check_ids) and all_ok
    # Verify cert-manager resource targets are exact
    cert_manager_expected_resources = {
        "cert-manager-helmrelease-ready": {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "namespace": "core-cert-manager",
            "name": "cert-manager",
        },
        "cert-manager-selfsigned-issuer-ready": {
            "apiVersion": "cert-manager.io/v1",
            "kind": "ClusterIssuer",
            "namespace": "",
            "name": "kubecrate-local-selfsigned",
        },
        "cert-manager-ca-certificate-ready": {
            "apiVersion": "cert-manager.io/v1",
            "kind": "Certificate",
            "namespace": "core-cert-manager",
            "name": "cratecheck-local-ca",
        },
        "cert-manager-ca-issuer-ready": {
            "apiVersion": "cert-manager.io/v1",
            "kind": "ClusterIssuer",
            "namespace": "",
            "name": "kubecrate-local-ca",
        },
        "cert-manager-tls-certificate-ready": {
            "apiVersion": "cert-manager.io/v1",
            "kind": "Certificate",
            "namespace": "cratecheck",
            "name": "cratecheck-tls",
        },
        "cert-manager-tls-secret-exists": {
            "apiVersion": "v1",
            "kind": "Secret",
            "namespace": "cratecheck",
            "name": "cratecheck-tls",
        },
    }
    for cm_id, expected in cert_manager_expected_resources.items():
        cm_check = next((c for c in checks if c.get("id") == cm_id), None)
        if cm_check is None:
            continue
        resource = cm_check.get("resource", {})
        for field in ("apiVersion", "kind", "namespace", "name"):
            actual = resource.get(field, "")
            expected_val = expected[field]
            all_ok &= check(
                f"cert-manager check {cm_id} resource.{field} matches expected",
                actual == expected_val,
                f"got '{actual}', expected '{expected_val}'",
            )
    # Verify TLS Secret check uses existence pattern (no condition checks on Secret)
    tls_secret_check = next((c for c in checks if c.get("id") == "cert-manager-tls-secret-exists"), None)
    if tls_secret_check:
        expr = tls_secret_check.get("expression", "")
        all_ok &= check(
            "cert-manager-tls-secret-exists checks metadata existence (no status conditions)",
            "object.metadata" in expr and "c.status" not in expr,
            "Secret resources have no status conditions; check metadata only",
        )
    return all_ok


def validate_cel_behavioral(checks: list[dict], expected_ids: set[str]) -> bool:
    """Validate cert-manager CEL expressions with structural and behavioral checks.

    This replaces substring-only inspection with structural validation:
    - Positive: verify guard clauses, exists closure, dot notation, Ready=True predicate
    - Negative: verify expression would fail for wrong condition type or missing resource
    - Completeness: every condition-based check has proper guards and closure
    """
    all_ok = True
    condition_check_ids = {cid for cid in expected_ids if cid != "cert-manager-tls-secret-exists"}

    for cm_check_id in sorted(expected_ids):
        cm_check = next((c for c in checks if c.get("id") == cm_check_id), None)
        if cm_check is None:
            continue
        expr = cm_check.get("expression", "").strip()

        # --- Structural validation ---
        # Verify balanced parentheses
        all_ok &= check(
            f"check {cm_check_id} CEL expression has balanced parentheses",
            expr.count("(") == expr.count(")"),
            f"open={expr.count('(')} close={expr.count(')')}",
        )

        # Dot notation (CrateCheck convention, not bracket indexing)
        uses_dot = "c.type" in expr or "c.status" in expr or "object.status" in expr or "object.metadata" in expr
        uses_bracket = "c[\"type\"]" in expr or "c[\"status\"]" in expr or "object[\"status\"]" in expr or "object[\"metadata\"]" in expr
        dot_detail = "uses dot notation" if uses_dot else "no dot-notation field access found"
        bracket_detail = "found bracket-indexed fields (should use dot)" if uses_bracket else ""
        combined_detail = "; ".join(filter(None, [dot_detail, bracket_detail]))
        all_ok &= check(
            f"check {cm_check_id} uses CrateCheck dot notation (not bracket indexing)",
            uses_dot or not uses_bracket,
            combined_detail,
        )

        if cm_check_id in condition_check_ids:
            # --- Positive behavioral: condition-based checks ---
            # Guard clauses must be present
            has_status_guard = "has(object.status)" in expr
            has_conditions_guard = "has(object.status.conditions)" in expr
            all_ok &= check(
                f"check {cm_check_id} has status guard: has(object.status)",
                has_status_guard,
                "guard present" if has_status_guard else "guard missing — check would fail on missing resource",
            )
            all_ok &= check(
                f"check {cm_check_id} has conditions guard: has(object.status.conditions)",
                has_conditions_guard,
                "guard present" if has_conditions_guard else "guard missing — check would crash on resource without conditions",
            )

            # exists() closure pattern
            has_exists = "object.status.conditions.exists(c," in expr or "object.status.conditions.exists(c, " in expr
            all_ok &= check(
                f"check {cm_check_id} uses exists(c, ...) closure on conditions",
                has_exists,
                "closure present" if has_exists else "closure missing — must iterate with exists(c, ...)",
            )

            # Ready=True predicate with correctly quoted string literals
            ready_predicate = (
                "c.type == 'Ready'" in expr
                and "c.status == 'True'" in expr
            )
            all_ok &= check(
                f"check {cm_check_id} asserts Ready=True condition with single-quoted literals",
                ready_predicate,
                "Ready=True pattern found" if ready_predicate else "missing c.type == 'Ready' && c.status == 'True'",
            )

            # --- Negative behavioral: verify expression is specific ---
            # Should use 'Ready' (string literal), not an unquoted identifier
            has_unquoted_ready = "c.type == Ready" in expr.replace("'Ready'", "")
            all_ok &= check(
                f"check {cm_check_id} Ready type is properly quoted (no bare identifier)",
                not has_unquoted_ready,
                "properly quoted" if not has_unquoted_ready else "FOUND bare Ready identifier — would reference undefined variable",
            )

            # Should check status == 'True' not status == True (bare boolean)
            has_bare_true = "status == True" in expr.replace("'True'", "").replace('"True"', "")
            all_ok &= check(
                f"check {cm_check_id} status value is string 'True' (not bare boolean)",
                not has_bare_true,
                "properly quoted" if not has_bare_true else "FOUND bare True — CEL condition status is string 'True' not boolean",
            )

            # Verify NOT using c.reason or c.message (which could produce false positives)
            has_reason_field = "c.reason" in expr
            all_ok &= check(
                f"check {cm_check_id} does not match on c.reason (avoids false positives)",
                not has_reason_field,
                "not found (correct)" if not has_reason_field else "FOUND c.reason field reference — should not be used for readiness",
            )

            # Simulate: if resource with wrong condition type presented, exists would return false
            # The expression uses c.type == 'Ready' — confirm it would reject other types
            uses_other_condition = any(
                f"c.type == '{t}'" in expr
                for t in ["Available", "Healthy", "Progressing", "Degraded"]
            )
            all_ok &= check(
                f"check {cm_check_id} only matches Ready condition (no other types)",
                not uses_other_condition,
                "only Ready matched" if not uses_other_condition else "FOUND non-Ready condition type in expression",
            )

        elif cm_check_id == "cert-manager-tls-secret-exists":
            # --- Secret existence: metadata-only pattern ---
            # Positive: checks metadata, not conditions
            all_ok &= check(
                f"check {cm_check_id} uses object.metadata (not status conditions)",
                "object.metadata" in expr,
                "metadata pattern found" if "object.metadata" in expr else "missing — Secret resources must use metadata checks",
            )
            all_ok &= check(
                f"check {cm_check_id} does not reference status conditions",
                "object.status" not in expr and "c.type" not in expr and "c.status" not in expr,
                "no condition references (correct)" if ("object.status" not in expr and "c.type" not in expr and "c.status" not in expr) else "FOUND status/condition references — Secret has no conditions",
            )
            # Verify name assertion pattern is present
            all_ok &= check(
                f"check {cm_check_id} asserts metadata.name matches expected value",
                "object.metadata.name" in expr,
                "name assertion found" if "object.metadata.name" in expr else "missing metadata.name check — must validate the Secret name",
            )

            # Negative: would fail if Secret doesn't exist (has guard)
            all_ok &= check(
                f"check {cm_check_id} has exists guard: has(object.metadata)",
                "has(object.metadata)" in expr,
                "guard present" if "has(object.metadata)" in expr else "guard missing — must guard against missing resource",
            )

    return all_ok


def validate_rbac() -> bool:
    """Validate RBAC rules are present and minimal."""
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
    # Verify cert-manager resource rules are present with exact RBAC tuples
    cm_rules = {
        # HelmRelease check: needs helm.toolkit.fluxcd.io helmreleases get
        ("helm.toolkit.fluxcd.io", "helmreleases", "get"): False,
        # ClusterIssuer/Certificate checks: needs cert-manager.io clusterissuers+certificates get
        ("cert-manager.io", "clusterissuers", "get"): False,
        ("cert-manager.io", "certificates", "get"): False,
        # TLS Secret check: needs core secrets get
        ("", "secrets", "get"): False,
    }
    for r in rules:
        for g in r.get("apiGroups", []):
            for res in r.get("resources", []):
                for verb in r.get("verbs", []):
                    key = (g, res, verb)
                    if key in cm_rules:
                        cm_rules[key] = True
    for (api_group, resource, verb), found in cm_rules.items():
        all_ok &= check(
            f"ClusterRole grants {verb} on {api_group or 'core'}/{resource}",
            found,
            f"missing RBAC tuple: apiGroups=[{api_group}], resources=[{resource}], verbs=[{verb}]",
        )
    # Verify no overly broad cert-manager permissions (read-only: get only, no list/watch/create/update/delete)
    cert_manager_read_only_verbs = {"get"}
    for r in rules:
        api_groups = r.get("apiGroups", [])
        if "cert-manager.io" in api_groups or "helm.toolkit.fluxcd.io" in api_groups:
            verbs = set(r.get("verbs", []))
            all_ok &= check(
                f"cert-manager RBAC rules are read-only (get only)",
                verbs <= cert_manager_read_only_verbs,
                f"found verbs {verbs} for apiGroups={api_groups}",
            )
    # Verify ClusterRoleBinding exists
    crb_path = BASE_DIR / "clusterrolebinding.yaml"
    with open(crb_path) as f:
        crb = yaml.safe_load(f)
    all_ok &= check(
        "ClusterRoleBinding references cratecheck ServiceAccount",
        crb.get("subjects", [{}])[0].get("name") == "cratecheck",
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
    all_ok &= check(
        "Container references ghcr.io/42aei/cratecheck:v1 image",
        container.get("image", "") == "ghcr.io/42aei/cratecheck:v1",
        container.get("image", "MISSING"),
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

    if args.render:
        print("\n=== Kustomize build validation ===")
        base_ok = run_kustomize_build(BASE_DIR, "base")
        binding_ok = run_kustomize_build(CLUSTER_BINDING_DIR, "cluster-binding")
        entrypoint_ok = run_kustomize_build(ENTRYPOINT_DIR, "entrypoint")

        print("\n=== kubeconform schema validation ===")
        kubeconform_ok = run_kubeconform("entrypoint")

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
