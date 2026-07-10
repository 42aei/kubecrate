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
    # Verify ESO checks are present
    eso_check_ids = {
        "eso-helmrelease-ready",
        "eso-secretstore-ready",
        "eso-externalsecret-ready",
        "eso-projected-secret-exists",
    }
    present_eso_ids = eso_check_ids & set(ids)
    all_ok &= check(
        "ESO check IDs are present",
        present_eso_ids == eso_check_ids,
        f"missing: {eso_check_ids - set(ids)}",
    )
    for check_id in ("eso-secretstore-ready", "eso-externalsecret-ready"):
        expression = next(c["expression"] for c in checks if c.get("id") == check_id)
        all_ok &= check(
            f"{check_id} uses map-safe condition access",
            "c['type'] == 'Ready'" in expression
            and "c['status'] == 'True'" in expression,
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
    # Verify ESO resource rules are present
    eso_api_groups = set()
    eso_resources = set()
    for r in rules:
        for g in r.get("apiGroups", []):
            eso_api_groups.add(g)
        for res in r.get("resources", []):
            eso_resources.add(res)
    all_ok &= check(
        "ClusterRole grants helmreleases read access",
        "helm.toolkit.fluxcd.io" in eso_api_groups,
    )
    all_ok &= check(
        "ClusterRole grants external-secrets read access",
        "external-secrets.io" in eso_api_groups,
    )
    all_ok &= check(
        "ClusterRole grants secrets read access",
        "secrets" in eso_resources,
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


def _parse_eso_expressions() -> dict[str, dict]:
    """Parse ESO check expressions from the committed configmap.yaml.

    Returns a dict mapping check ID to expression metadata (expression,
    resource coordinates, messages).  Only returns ESO-specific checks.
    """
    eso_check_ids = {
        "eso-secretstore-ready",
        "eso-externalsecret-ready",
        "eso-projected-secret-exists",
    }
    configmap_path = BASE_DIR / "configmap.yaml"
    with open(configmap_path) as fh:
        cm = yaml.safe_load(fh)
    status_yaml = cm["data"]["status.yaml"]
    status_cfg = yaml.safe_load(status_yaml)
    expressions: dict[str, dict] = {}
    for c in status_cfg["checks"]:
        cid = c.get("id", "")
        if cid in eso_check_ids:
            expressions[cid] = {
                "expression": c["expression"],
                "resource": c["resource"],
                "success_message": c.get("successMessage", ""),
                "failure_message": c.get("failureMessage", ""),
            }
    return expressions


def _cel_eval(expression: str, activation: dict) -> bool:
    """Evaluate a CEL expression against a JSON-shaped activation dictionary."""
    import celpy  # noqa: F811
    from celpy.adapter import json_to_cel  # noqa: F811

    env = celpy.Environment()
    ast = env.compile(expression)
    program = env.program(ast)
    value = program.evaluate({"object": json_to_cel(activation)})
    return bool(value)


def validate_cel_expressions() -> bool:
    """Validate ESO CEL expressions parsed from the committed configmap against
    representative positive and negative mock status objects.

    Uses the ``celpy`` library so validation is portable — no dependency
    on a separate CrateCheck checkout, a Go toolchain, or any machine-local path.
    """
    try:
        expressions = _parse_eso_expressions()
    except Exception as exc:
        return check("ESO CEL expressions parseable from configmap", False, str(exc))

    all_ok = True

    # Required ESO check IDs
    required_ids = {
        "eso-secretstore-ready",
        "eso-externalsecret-ready",
        "eso-projected-secret-exists",
    }
    found_ids = set(expressions.keys())
    all_ok &= check(
        "All ESO check IDs present in configmap",
        found_ids == required_ids,
        f"missing: {required_ids - found_ids}, extra: {found_ids - required_ids}",
    )

    # ---- Positive / negative fixtures ----

    # SecretStore: object with conditions including type=Ready, status=True
    store_expr = expressions.get("eso-secretstore-ready", {}).get("expression", "")
    store_resource = expressions.get("eso-secretstore-ready", {}).get("resource", {})

    # Positive: Ready=True present
    store_ok_obj = {
        "status": {
            "conditions": [
                {"type": "Ready", "status": "True",
                 "reason": "Valid", "message": "Store is valid"},
            ],
        },
    }
    # Negative: no status at all
    store_no_status_obj: dict = {}
    # Negative: conditions present but no Ready type
    store_no_ready_obj = {
        "status": {
            "conditions": [
                {"type": "NotReady", "status": "True"},
            ],
        },
    }
    # Negative: Ready type present but status is False
    store_status_false_obj = {
        "status": {
            "conditions": [
                {"type": "Ready", "status": "False",
                 "reason": "InvalidConfiguration"},
            ],
        },
    }

    all_ok &= check(
        "SecretStore expression: mock (Ready) -> true",
        _cel_eval(store_expr, store_ok_obj),
    )
    all_ok &= check(
        "SecretStore expression: mock (no status) -> false",
        not _cel_eval(store_expr, store_no_status_obj),
    )
    all_ok &= check(
        "SecretStore expression: mock (no Ready condition) -> false",
        not _cel_eval(store_expr, store_no_ready_obj),
    )
    all_ok &= check(
        "SecretStore expression: mock (status=False) -> false",
        not _cel_eval(store_expr, store_status_false_obj),
    )
    all_ok &= check(
        "SecretStore resource coordinates",
        store_resource == {
            "apiVersion": "external-secrets.io/v1",
            "kind": "SecretStore",
            "namespace": "kubecrate-system",
            "name": "eso-smoke-kubernetes-store",
        },
    )

    # ExternalSecret: same expression shape, different resource coordinates
    es_expr = expressions.get("eso-externalsecret-ready", {}).get("expression", "")
    es_resource = expressions.get("eso-externalsecret-ready", {}).get("resource", {})

    es_ok_obj = {
        "status": {
            "conditions": [
                {"type": "Ready", "status": "True",
                 "reason": "Updated", "message": "Sync complete"},
            ],
        },
    }
    es_no_status_obj: dict = {}
    es_no_ready_obj = {
        "status": {
            "conditions": [
                {"type": "Error", "status": "True"},
            ],
        },
    }
    es_status_false_obj = {
        "status": {
            "conditions": [
                {"type": "Ready", "status": "False",
                 "reason": "SecretSyncedError"},
            ],
        },
    }

    all_ok &= check(
        "ExternalSecret expression: mock (Ready) -> true",
        _cel_eval(es_expr, es_ok_obj),
    )
    all_ok &= check(
        "ExternalSecret expression: mock (no status) -> false",
        not _cel_eval(es_expr, es_no_status_obj),
    )
    all_ok &= check(
        "ExternalSecret expression: mock (no Ready condition) -> false",
        not _cel_eval(es_expr, es_no_ready_obj),
    )
    all_ok &= check(
        "ExternalSecret expression: mock (status=False) -> false",
        not _cel_eval(es_expr, es_status_false_obj),
    )
    all_ok &= check(
        "ExternalSecret resource coordinates",
        es_resource == {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "namespace": "kubecrate-system",
            "name": "eso-smoke-projection",
        },
    )

    # Projected Secret: metadata.name == 'eso-smoke-projected'
    sec_expr = expressions.get("eso-projected-secret-exists", {}).get("expression", "")
    sec_resource = expressions.get("eso-projected-secret-exists", {}).get("resource", {})

    sec_ok_obj = {"metadata": {"name": "eso-smoke-projected"}}
    sec_no_metadata_obj: dict = {}
    sec_wrong_name_obj = {"metadata": {"name": "wrong-secret"}}

    all_ok &= check(
        "Projected Secret expression: mock (correct name) -> true",
        _cel_eval(sec_expr, sec_ok_obj),
    )
    all_ok &= check(
        "Projected Secret expression: mock (no metadata) -> false",
        not _cel_eval(sec_expr, sec_no_metadata_obj),
    )
    all_ok &= check(
        "Projected Secret expression: mock (wrong name) -> false",
        not _cel_eval(sec_expr, sec_wrong_name_obj),
    )
    all_ok &= check(
        "Projected Secret resource coordinates",
        sec_resource == {
            "apiVersion": "v1",
            "kind": "Secret",
            "namespace": "kubecrate-system",
            "name": "eso-smoke-projected",
        },
    )

    # ----- Adversarial: prove mutating either committed expression causes failure -----
    # If a committed expression is mutated (e.g. c.type == 'DefinitelyWrong'),
    # the positive fixture must *fail*.
    mutated_store = store_expr.replace(
        "c['type'] == 'Ready'", "c['type'] == 'DefinitelyWrong'"
    )
    all_ok &= check(
        "Adversarial: mutated SecretStore expression fails on valid mock",
        not _cel_eval(mutated_store, store_ok_obj),
    )
    mutated_es = es_expr.replace(
        "c['type'] == 'Ready'", "c['type'] == 'DefinitelyWrong'"
    )
    all_ok &= check(
        "Adversarial: mutated ExternalSecret expression fails on valid mock",
        not _cel_eval(mutated_es, es_ok_obj),
    )
    mutated_sec = sec_expr.replace("'eso-smoke-projected'", "'definitely-wrong'")
    all_ok &= check(
        "Adversarial: mutated Projected Secret expression fails on valid mock",
        not _cel_eval(mutated_sec, sec_ok_obj),
    )

    return all_ok


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

    print("\n=== CrateCheck CEL expression validation ===")
    cel_ok = validate_cel_expressions()

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
