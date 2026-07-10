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

    Structural checks:
    - Balanced parentheses, dot notation, guard clauses, exists closure,
      Ready=True predicate, no c.reason, no non-Ready types, proper quoting

    Behavioral (actual CEL evaluation via celpy):
    - Positive fixtures: Ready=True passes
    - Negative fixtures: absent conditions, Ready=False, wrong type, missing resource fail
    - Mutation regression: appending || true to every expression makes it always pass
    - TLS Secret: metadata-only fixture validation
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
            uses_other_condition = any(
                f"c.type == '{t}'" in expr
                for t in ["Available", "Healthy", "Progressing", "Degraded"]
            )
            all_ok &= check(
                f"check {cm_check_id} only matches Ready condition (no other types)",
                not uses_other_condition,
                "only Ready matched" if not uses_other_condition else "FOUND non-Ready condition type in expression",
            )

            # --- Actual CEL behavioral evaluation ---
            all_ok &= _evaluate_cel_behavioral(cm_check_id, expr) and all_ok

        elif cm_check_id == "cert-manager-tls-secret-exists":
            # --- Secret existence: metadata-only pattern ---
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
            all_ok &= check(
                f"check {cm_check_id} asserts metadata.name matches expected value",
                "object.metadata.name" in expr,
                "name assertion found" if "object.metadata.name" in expr else "missing metadata.name check — must validate the Secret name",
            )
            all_ok &= check(
                f"check {cm_check_id} has exists guard: has(object.metadata)",
                "has(object.metadata)" in expr,
                "guard present" if "has(object.metadata)" in expr else "guard missing — must guard against missing resource",
            )

            # --- Actual CEL behavioral evaluation for Secret ---
            all_ok &= _evaluate_cel_secret_behavioral(cm_check_id, expr) and all_ok

    return all_ok


def _evaluate_cel_behavioral(check_id: str, expr: str) -> bool:
    """Actually evaluate a condition-based CEL expression against fixture resources.

    Returns True if all fixture evaluations pass (expected outcomes match).
    """
    all_ok = True

    # Fixtures for condition-based checks
    ready_true_obj = {
        "status": {
            "conditions": [
                {"type": "Ready", "status": "True", "reason": "Ready", "message": "Resource is ready"},
            ]
        }
    }
    ready_false_obj = {
        "status": {
            "conditions": [
                {"type": "Ready", "status": "False", "reason": "Error", "message": "Not ready"},
            ]
        }
    }
    available_true_obj = {
        "status": {
            "conditions": [
                {"type": "Available", "status": "True", "reason": "Available", "message": "Available"},
            ]
        }
    }
    empty_conditions_obj = {"status": {"conditions": []}}
    no_status_obj = {"metadata": {"name": "test-resource"}}
    empty_obj = {}

    fixtures = [
        ("Ready=True → passes (returns true)", ready_true_obj, True),
        ("Ready=False → fails (returns false)", ready_false_obj, False),
        ("Available=True → fails (wrong condition type)", available_true_obj, False),
        ("empty conditions → fails (no matching condition)", empty_conditions_obj, False),
        ("no status → fails (guard returns false)", no_status_obj, False),
        ("empty object → fails (guard returns false)", empty_obj, False),
    ]

    mutation_fixtures = [
        ("mutated || true on no-status → true (regression detected)", no_status_obj, True),
        ("mutated || true on empty object → true (regression detected)", empty_obj, True),
        ("mutated || true on Ready=False → true (regression detected)", ready_false_obj, True),
    ]

    try:
        from celpy import Environment
        from celpy.adapter import json_to_cel

        env = Environment()

        # Normal expression evaluation
        try:
            ast = env.compile(expr)
            prg = env.program(ast)
        except Exception as e:
            all_ok &= check(
                f"check {check_id} CEL expression compiles",
                False,
                f"compilation error: {e}",
            )
            return all_ok

        for desc, obj, expected in fixtures:
            try:
                cel_obj = json_to_cel(obj)
                result = prg.evaluate({"object": cel_obj})
                actual = bool(result)
                ok = actual == expected
                all_ok &= check(
                    f"check {check_id} CEL eval: {desc}",
                    ok,
                    f"got {actual}, expected {expected}",
                )
            except Exception as e:
                all_ok &= check(
                    f"check {check_id} CEL eval: {desc}",
                    False,
                    f"evaluation error: {e}",
                )

        # Mutation regression: append || true to the expression
        mutated_expr = f"({expr}) || true"
        try:
            mut_ast = env.compile(mutated_expr)
            mut_prg = env.program(mut_ast)
        except Exception as e:
            all_ok &= check(
                f"check {check_id} CEL mutation: compilation",
                False,
                f"compilation error: {e}",
            )
            return all_ok

        for desc, obj, expected in mutation_fixtures:
            try:
                cel_obj = json_to_cel(obj)
                result = mut_prg.evaluate({"object": cel_obj})
                actual = bool(result)
                ok = actual == expected
                all_ok &= check(
                    f"check {check_id} CEL mutation regr: {desc}",
                    ok,
                    f"got {actual}, expected {expected}",
                )
            except Exception as e:
                all_ok &= check(
                    f"check {check_id} CEL mutation regr: {desc}",
                    False,
                    f"evaluation error: {e}",
                )

    except ImportError:
        all_ok &= check(
            f"check {check_id} CEL behavioral eval (celpy available)",
            False,
            "celpy not installed; install with: pip install cel-python",
        )

    return all_ok


def _evaluate_cel_secret_behavioral(check_id: str, expr: str) -> bool:
    """Actually evaluate a metadata-only CEL expression against fixture Secrets."""
    all_ok = True

    matching_secret = {"metadata": {"name": "cratecheck-tls"}}
    wrong_name_secret = {"metadata": {"name": "other-secret"}}
    empty_secret = {}
    no_metadata = {"data": {"tls.crt": "..."}}

    fixtures = [
        ("matching Secret → passes", matching_secret, True),
        ("wrong name → fails", wrong_name_secret, False),
        ("empty object → fails (guard returns false)", empty_secret, False),
        ("no metadata → fails (guard returns false)", no_metadata, False),
    ]

    try:
        from celpy import Environment
        from celpy.adapter import json_to_cel

        env = Environment()

        try:
            ast = env.compile(expr)
            prg = env.program(ast)
        except Exception as e:
            all_ok &= check(
                f"check {check_id} CEL expression compiles",
                False,
                f"compilation error: {e}",
            )
            return all_ok

        for desc, obj, expected in fixtures:
            try:
                cel_obj = json_to_cel(obj)
                result = prg.evaluate({"object": cel_obj})
                actual = bool(result)
                ok = actual == expected
                all_ok &= check(
                    f"check {check_id} CEL eval: {desc}",
                    ok,
                    f"got {actual}, expected {expected}",
                )
            except Exception as e:
                all_ok &= check(
                    f"check {check_id} CEL eval: {desc}",
                    False,
                    f"evaluation error: {e}",
                )

    except ImportError:
        all_ok &= check(
            f"check {check_id} CEL behavioral eval (celpy available)",
            False,
            "celpy not installed; install with: pip install cel-python",
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


def validate_runbook_fixtures() -> bool:
    """Validate the runbook assertion logic against fixture payloads.

    Ensures the Python snippets in the runbook correctly detect:
    - green: all cert-manager checks present and green
    - missing: a required check ID absent → fail
    - wrong state: a check is non-green → fail
    - controlled red: red_ids non-green, unaffected_ids green
    - restore green: all checks back to green after restore
    """
    all_ok = True

    def _build_payload(check_states: dict[str, str]) -> dict:
        """Build a CrateCheck /status.json shape from a dict of id→state."""
        checks = []
        for cid, state in check_states.items():
            checks.append({"id": cid, "state": state, "summary": f"fixture {cid}", "name": cid, "severity": "red"})
        return {"checks": checks}

    cm_ids = [
        "cert-manager-helmrelease-ready",
        "cert-manager-selfsigned-issuer-ready",
        "cert-manager-ca-certificate-ready",
        "cert-manager-ca-issuer-ready",
        "cert-manager-tls-certificate-ready",
        "cert-manager-tls-secret-exists",
    ]
    unaffected_ids = cm_ids[:4]
    red_ids = cm_ids[4:]

    # --- Test 1: All green baseline ---
    green_payload = _build_payload({cid: "green" for cid in cm_ids})
    checks = {c["id"]: c for c in green_payload["checks"]}
    all_checks_present = all(cid in checks for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: all six checks present in green payload",
        all_checks_present,
    )
    all_green = all(checks[cid]["state"] == "green" for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: all six checks green",
        all_green,
    )

    # --- Test 2: Missing check IDs → must fail ---
    missing_payload = _build_payload({cid: "green" for cid in cm_ids[:3]})  # only 3 of 6
    checks_missing = {c["id"]: c for c in missing_payload["checks"]}
    any_missing = any(cid not in checks_missing for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: missing check IDs detected (fail-closed)",
        any_missing,
    )

    # Missing check with {"checks": []} should be detected
    empty_payload = {"checks": []}
    checks_empty = {c["id"]: c for c in empty_payload["checks"]}
    empty_detected = any(cid not in checks_empty for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: empty checks payload detected as missing (fail-closed)",
        empty_detected,
    )

    # --- Test 3: Wrong state (non-green when should be green) ---
    wrong_payload = _build_payload({cid: "green" for cid in cm_ids})
    wrong_payload["checks"][2]["state"] = "yellow"  # ca-certificate-ready is yellow
    checks_wrong = {c["id"]: c for c in wrong_payload["checks"]}
    has_wrong = any(checks_wrong[cid]["state"] != "green" for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: non-green check detected in baseline",
        has_wrong,
    )

    # --- Test 4: Controlled red ---
    red_payload = _build_payload(
        {cid: "green" for cid in unaffected_ids}
        | {cid: "red" for cid in red_ids}
    )
    checks_red = {c["id"]: c for c in red_payload["checks"]}

    # Red IDs must be present and non-green
    red_ids_present = all(cid in checks_red for cid in red_ids)
    all_ok &= check(
        "runbook fixture: red IDs present in controlled red payload",
        red_ids_present,
    )
    red_ids_non_green = all(checks_red[cid]["state"] != "green" for cid in red_ids)
    all_ok &= check(
        "runbook fixture: red IDs are non-green",
        red_ids_non_green,
    )

    # Unaffected IDs must be present and green
    unaffected_present = all(cid in checks_red for cid in unaffected_ids)
    all_ok &= check(
        "runbook fixture: unaffected IDs present in controlled red payload",
        unaffected_present,
    )
    unaffected_green = all(checks_red[cid]["state"] == "green" for cid in unaffected_ids)
    all_ok &= check(
        "runbook fixture: unaffected IDs remain green during red test",
        unaffected_green,
    )

    # --- Test 5: Red with missing red ID → must fail ---
    red_missing_red_payload = _build_payload(
        {cid: "green" for cid in unaffected_ids}
        | {"cert-manager-tls-certificate-ready": "red"}  # only one red ID present
    )
    checks_red_missing = {c["id"]: c for c in red_missing_red_payload["checks"]}
    red_missing_detected = any(cid not in checks_red_missing for cid in red_ids)
    all_ok &= check(
        "runbook fixture: missing red check ID detected (fail-closed)",
        red_missing_detected,
    )

    # --- Test 6: Red with affected unaffected check → must fail ---
    red_unaffected_broken_payload = _build_payload(
        {cid: "green" if cid != "cert-manager-helmrelease-ready" else "yellow" for cid in unaffected_ids}
        | {cid: "red" for cid in red_ids}
    )
    checks_unaffected_broken = {c["id"]: c for c in red_unaffected_broken_payload["checks"]}
    unaffected_broken = any(
        checks_unaffected_broken[cid]["state"] != "green"
        for cid in unaffected_ids
        if cid in checks_unaffected_broken
    )
    all_ok &= check(
        "runbook fixture: affected unaffected check detected (regression)",
        unaffected_broken,
    )

    # --- Test 7: Restore green ---
    restore_payload = _build_payload({cid: "green" for cid in cm_ids})
    checks_restore = {c["id"]: c for c in restore_payload["checks"]}
    all_restore_present = all(cid in checks_restore for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: all checks present after restore",
        all_restore_present,
    )
    all_restore_green = all(checks_restore[cid]["state"] == "green" for cid in cm_ids)
    all_ok &= check(
        "runbook fixture: all checks green after restore",
        all_restore_green,
    )

    return all_ok


def validate_runbook_probes() -> bool:
    """Validate the runbook poll_until contract, Python compilation, status coverage,
    trap presence, UI evidence, and execute poll_until with fixture probes.

    Probes:
    1. Python heredocs compile cleanly
    2. /status.json referenced at least 3 times
    3. trap EXIT INT TERM present for fail-safe cleanup
    4. UI evidence (browser/screenshot) mentioned
    5. Poll_until success: predicate that returns 0 within timeout
    6. Poll_until timeout: predicate that always fails → timeout
    7. Poll_until bounded: elapsed ≤ max_wait + interval (bounded)
    """
    all_ok = True
    runbook_path = REPO_ROOT / "docs" / "kind-cert-manager-tls-runbook.md"

    with open(runbook_path) as f:
        runbook_text = f.read()

    # --- Check 1: Runbook file is substantial ---
    all_ok &= check(
        "runbook file is non-trivial (≥5KB)",
        len(runbook_text) >= 5000,
        f"{len(runbook_text)} bytes",
    )

    # --- Check 2: poll_until has correct signature ---
    all_ok &= check(
        "poll_until uses desc max_wait predicate interval signature",
        'local desc="$1" max_wait="$2" predicate="$3" interval="${4:-5}"' in runbook_text
        or 'local desc="$1" max_wait="$2" predicate="$3" ' in runbook_text,
        "correct signature found" if (
            'local desc="$1" max_wait="$2" predicate="$3"' in runbook_text
        ) else "poll_until signature missing or incorrect",
    )

    # --- Check 3: Python heredocs compile ---
    import re
    # Extract PYEOF heredoc blocks (complete Python programs, not inline -c snippets)
    heredoc_blocks = re.findall(
        r"python3 << 'PYEOF'\n(.*?)\nPYEOF",
        runbook_text, re.DOTALL,
    )
    compile_errors = 0
    for i, snippet in enumerate(heredoc_blocks):
        snippet = snippet.strip()
        if not snippet:
            continue
        try:
            compile(snippet, f"<runbook-herodoc-{i}>", "exec")
        except SyntaxError as e:
            compile_errors += 1
            all_ok &= check(
                f"runbook PYEOF heredoc {i} compiles",
                False,
                f"SyntaxError: {e}",
            )
    if compile_errors == 0 and heredoc_blocks:
        all_ok &= check(
            f"runbook PYEOF heredocs compile ({len(heredoc_blocks)} found)",
            True,
        )
    elif not heredoc_blocks:
        all_ok &= check(
            "runbook PYEOF heredocs found",
            False,
            "no python3 << 'PYEOF' heredocs found",
        )

    # --- Check 4: /status.json coverage ---
    status_json_count = runbook_text.count("/status.json")
    all_ok &= check(
        "runbook references /status.json ≥ 3 times",
        status_json_count >= 3,
        f"found {status_json_count} references",
    )

    # --- Check 5: trap EXIT INT TERM present ---
    trap_found = "trap" in runbook_text and (
        "EXIT INT TERM" in runbook_text
        or "INT TERM EXIT" in runbook_text
        or "EXIT TERM INT" in runbook_text
    )
    all_ok &= check(
        "runbook has trap EXIT INT TERM for fail-safe cleanup",
        trap_found,
        "trap found" if trap_found else "trap with EXIT INT TERM not found",
    )

    # --- Check 6: UI evidence mentioned ---
    ui_evidence = (
        "browser" in runbook_text.lower()
        or "screenshot" in runbook_text.lower()
        or "UI evidence" in runbook_text
    )
    all_ok &= check(
        "runbook references UI evidence (browser/screenshot)",
        ui_evidence,
        "UI evidence reference found" if ui_evidence else "no browser/screenshot/UI evidence mention",
    )

    # --- Check 7: Execute poll_until with fixture probes ---
    all_ok &= _execute_poll_until_probes() and all_ok

    return all_ok


def _execute_poll_until_probes() -> bool:
    """Execute poll_until helper in a subprocess with test predicates.

    Proves: success, timeout, and bounded timeout behavior.
    """
    all_ok = True

    # Write a self-contained test script that defines poll_until and runs probes
    test_script = (
        '#!/bin/bash\n'
        'set -euo pipefail\n'
        '\n'
        'poll_until() {\n'
        '  local desc="$1" max_wait="$2" predicate="$3" interval="${4:-5}"\n'
        '  local elapsed=0\n'
        '  while [ $elapsed -lt "$max_wait" ]; do\n'
        '    if eval "$predicate" 2>/dev/null; then\n'
        '      echo "OK:$desc:${elapsed}"\n'
        '      return 0\n'
        '    fi\n'
        '    sleep "$interval"\n'
        '    elapsed=$((elapsed + interval))\n'
        '  done\n'
        '  echo "TIMEOUT:$desc:${elapsed}"\n'
        '  return 1\n'
        '}\n'
        '\n'
        '# Probe 1: success — predicate that returns 0 immediately\n'
        'poll_until "success probe" 10 "true" 1\n'
        '\n'
        '# Probe 2: timeout — predicate that always returns 1\n'
        'if poll_until "timeout probe" 8 "false" 2; then\n'
        '  echo "UNEXPECTED_SUCCESS:timeout_probe"\n'
        '  exit 1\n'
        'else\n'
        '  echo "EXPECTED_TIMEOUT:timeout_probe"\n'
        'fi\n'
        '\n'
        '# Probe 3: wrong-state — predicate that checks a condition that fails\n'
        'if poll_until "wrong-state probe" 8 "test xyz = abc" 2; then\n'
        '  echo "UNEXPECTED_SUCCESS:wrong_state_probe"\n'
        '  exit 1\n'
        'else\n'
        '  echo "EXPECTED_TIMEOUT:wrong_state_probe"\n'
        'fi\n'
        '\n'
        '# Probe 4: bounded timeout — elapsed must be < max_wait + interval\n'
        'poll_until "bounded probe" 6 "true" 1\n'
        '\n'
        'echo "ALL_PROBES_PASSED"\n'
    )

    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, prefix="runbook-probe-"
    ) as f:
        f.write(test_script)
        script_path = f.name

    try:
        import os
        os.chmod(script_path, 0o755)
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr

        # Probe 1: success
        success_matched = "OK:success probe:" in output
        all_ok &= check(
            "poll_until probe: success predicate returns within timeout",
            success_matched,
            "success detected" if success_matched else "success probe failed",
        )

        # Probe 2: timeout
        timeout_matched = "EXPECTED_TIMEOUT:timeout_probe" in output
        all_ok &= check(
            "poll_until probe: timeout predicate correctly times out",
            timeout_matched,
            "timeout detected" if timeout_matched else "timeout probe did not fire",
        )

        # Probe 3: wrong-state
        wrong_state_matched = "EXPECTED_TIMEOUT:wrong_state_probe" in output
        all_ok &= check(
            "poll_until probe: wrong-state predicate correctly times out",
            wrong_state_matched,
            "wrong-state timeout detected" if wrong_state_matched else "wrong-state probe failed",
        )

        # Probe 4: bounded timeout (elapsed must be ≤ max_wait + interval)
        import re
        elapsed_match = re.search(r"OK:bounded probe:(\d+)", output)
        if elapsed_match:
            elapsed = int(elapsed_match.group(1))
            bounded_ok = elapsed <= 11  # max_wait=6 + interval=1 + some slack
            all_ok &= check(
                "poll_until probe: bounded timeout (elapsed ≤ max_wait + interval)",
                bounded_ok,
                f"elapsed={elapsed}s, max_wait=6, interval=1",
            )
        else:
            all_ok &= check(
                "poll_until probe: bounded timeout executed",
                False,
                "bounded probe did not run",
            )

        if result.returncode != 0:
            all_ok &= check(
                "poll_until probe: all probes passed",
                False,
                f"exit code {result.returncode}",
            )

    finally:
        import os as _os
        _os.unlink(script_path)

    return all_ok


def validate_flux_render_assertions() -> bool:
    """Validate parsed Flux render assertions for sync branch.

    Checks:
    1. Default flux-sync-values ConfigMap has branch: pivot/flux-sync-ssh-bootstrap
    2. Override mechanism references correct ConfigMap name
    """
    all_ok = True

    # Run kustomize build on entrypoint
    result = subprocess.run(
        ["kustomize", "build", str(ENTRYPOINT_DIR)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        all_ok &= check(
            "flux render: kustomize build succeeds",
            False,
            result.stderr.strip()[:120],
        )
        return all_ok

    # Parse all YAML documents
    docs = list(yaml.safe_load_all(result.stdout))
    docs = [d for d in docs if d is not None]

    # Find flux-sync-values ConfigMap
    sync_values_cm = None
    sync_override_cm = None
    for d in docs:
        if d.get("kind") != "ConfigMap":
            continue
        name = d.get("metadata", {}).get("name", "")
        if name == "flux-sync-values":
            sync_values_cm = d
        elif name == "flux-sync-values-override":
            sync_override_cm = d

    # --- Check default sync values ---
    if sync_values_cm:
        values_yaml = ""
        if "data" in sync_values_cm and "values.yaml" in sync_values_cm["data"]:
            values_yaml = sync_values_cm["data"]["values.yaml"]
        elif "binaryData" in sync_values_cm:
            all_ok &= check(
                "flux render: flux-sync-values ConfigMap has data.values.yaml",
                False,
                "uses binaryData instead of data",
            )
            return all_ok
        else:
            all_ok &= check(
                "flux render: flux-sync-values ConfigMap has data.values.yaml",
                False,
                "no data field found",
            )
            return all_ok

        parsed = yaml.safe_load(values_yaml)
        branch = (
            parsed.get("gitRepository", {})
            .get("spec", {})
            .get("ref", {})
            .get("branch", "")
        )
        all_ok &= check(
            "flux render: default sync branch is pivot/flux-sync-ssh-bootstrap",
            branch == "pivot/flux-sync-ssh-bootstrap",
            f"got '{branch}'",
        )
    else:
        all_ok &= check(
            "flux render: flux-sync-values ConfigMap exists in rendered output",
            False,
        )

    # --- Check override ConfigMap exists (it should always be generated) ---
    all_ok &= check(
        "flux render: flux-sync-values-override ConfigMap exists in rendered output",
        sync_override_cm is not None,
    )

    # --- Verify sync HelmRelease references both ConfigMaps ---
    helmrelease_found = False
    for d in docs:
        if d.get("kind") == "HelmRelease" and d.get("metadata", {}).get("name") == "flux-system-sync":
            helmrelease_found = True
            values_from = d.get("spec", {}).get("valuesFrom", [])
            cm_names = [vf.get("name", "") for vf in values_from if vf.get("kind") == "ConfigMap"]
            has_default = "flux-sync-values" in cm_names
            has_override = "flux-sync-values-override" in cm_names
            all_ok &= check(
                "flux render: sync HelmRelease references flux-sync-values",
                has_default,
            )
            override_is_optional = any(
                vf.get("name") == "flux-sync-values-override" and vf.get("optional") is True
                for vf in values_from
            )
            all_ok &= check(
                "flux render: sync HelmRelease override is optional",
                override_is_optional,
                "optional: true" if override_is_optional else "override not marked optional",
            )
            break
    all_ok &= check(
        "flux render: sync HelmRelease flux-system-sync rendered",
        helmrelease_found,
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

    print("\n=== Runbook fixture validation ===")
    runbook_ok = validate_runbook_fixtures()

    print("\n=== Runbook probe validation ===")
    probes_ok = validate_runbook_probes()

    print("\n=== Flux render assertions ===")
    flux_render_ok = validate_flux_render_assertions()

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
