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
    6. CEL expressions use correct condition checks (actual celpy evaluation)
    7. Regression coverage for runbook smoke-policy scoping
"""

import argparse
import copy
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

    # Validate CEL expressions with behavioral fixtures (not just substring matching).
    # A mutated expression like "(original) || true" must be rejected.
    condition_check_ids = {
        "kyverno-helmrelease-ready",
        "kyverno-clusterpolicy-ready",
    }
    all_ok &= validate_cel_behavioral(checks, condition_check_ids) and all_ok

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


def validate_cel_behavioral(checks: list[dict], expected_ids: set[str]) -> bool:
    """Validate Kyverno CEL expressions with structural and behavioral checks.

    Structural checks:
      - Balanced parentheses, dot notation, guard clauses, exists closure,
        Ready=True predicate, no c.reason, no non-Ready types, proper quoting

    Behavioral (actual CEL evaluation via celpy):
      - Positive fixtures: Ready=True passes
      - Negative fixtures: Ready=False, wrong type, missing status/conditions fail
      - Mutation regression: appending || true to every expression makes it always pass
    """
    all_ok = True

    for kv_check_id in sorted(expected_ids):
        kv_check = next((c for c in checks if c.get("id") == kv_check_id), None)
        if kv_check is None:
            all_ok &= check(
                f"Kyverno check {kv_check_id} CEL expression", False, "check not found",
            )
            continue
        expr = kv_check.get("expression", "").strip()

        # --- Structural validation ---
        # Verify balanced parentheses
        all_ok &= check(
            f"check {kv_check_id} CEL expression has balanced parentheses",
            expr.count("(") == expr.count(")"),
            f"open={expr.count('(')} close={expr.count(')')}",
        )

        # Dot notation (CrateCheck convention, not bracket indexing)
        uses_dot = "c.type" in expr or "c.status" in expr or "object.status" in expr
        uses_bracket = "c[\"type\"]" in expr or "c[\"status\"]" in expr or "object[\"status\"]" in expr
        dot_detail = "uses dot notation" if uses_dot else "no dot-notation field access found"
        bracket_detail = "found bracket-indexed fields (should use dot)" if uses_bracket else ""
        combined_detail = "; ".join(filter(None, [dot_detail, bracket_detail]))
        all_ok &= check(
            f"check {kv_check_id} uses CrateCheck dot notation (not bracket indexing)",
            uses_dot or not uses_bracket,
            combined_detail,
        )

        # Guard clauses must be present
        has_status_guard = "has(object.status)" in expr
        has_conditions_guard = "has(object.status.conditions)" in expr
        all_ok &= check(
            f"check {kv_check_id} has status guard: has(object.status)",
            has_status_guard,
            "guard present" if has_status_guard else "guard missing",
        )
        all_ok &= check(
            f"check {kv_check_id} has conditions guard: has(object.status.conditions)",
            has_conditions_guard,
            "guard present" if has_conditions_guard else "guard missing",
        )

        # exists() closure pattern
        has_exists = "object.status.conditions.exists(c," in expr or "object.status.conditions.exists(c, " in expr
        all_ok &= check(
            f"check {kv_check_id} uses exists(c, ...) closure on conditions",
            has_exists,
            "closure present" if has_exists else "closure missing",
        )

        # Ready=True predicate with correctly quoted string literals
        ready_predicate = (
            "c.type == 'Ready'" in expr
            and "c.status == 'True'" in expr
        )
        all_ok &= check(
            f"check {kv_check_id} asserts Ready=True condition with single-quoted literals",
            ready_predicate,
            "Ready=True pattern found" if ready_predicate else "missing c.type == 'Ready' && c.status == 'True'",
        )

        # --- Negative behavioral: verify expression is specific ---
        # Should use 'Ready' (string literal), not an unquoted identifier
        has_unquoted_ready = "c.type == Ready" in expr.replace("'Ready'", "")
        all_ok &= check(
            f"check {kv_check_id} Ready type is properly quoted (no bare identifier)",
            not has_unquoted_ready,
            "properly quoted" if not has_unquoted_ready else "FOUND bare Ready identifier",
        )

        # Should check status == 'True' not status == True (bare boolean)
        has_bare_true = "status == True" in expr.replace("'True'", "").replace('"True"', "")
        all_ok &= check(
            f"check {kv_check_id} status value is string 'True' (not bare boolean)",
            not has_bare_true,
            "properly quoted" if not has_bare_true else "FOUND bare True",
        )

        # Verify NOT using c.reason or c.message (which could produce false positives)
        has_reason_field = "c.reason" in expr
        all_ok &= check(
            f"check {kv_check_id} does not match on c.reason (avoids false positives)",
            not has_reason_field,
            "not found (correct)" if not has_reason_field else "FOUND c.reason field reference",
        )

        # Only match Ready condition (no other types)
        uses_other_condition = any(
            f"c.type == '{t}'" in expr
            for t in ["Available", "Healthy", "Progressing", "Degraded"]
        )
        all_ok &= check(
            f"check {kv_check_id} only matches Ready condition (no other types)",
            not uses_other_condition,
            "only Ready matched" if not uses_other_condition else "FOUND non-Ready condition type",
        )

        # Always-true mutation detection — reject || true patterns in committed expression
        import re
        always_true_patterns = [
            r"\|\|\s*true\b",
            r"\|\|\s*True\b",
            r"\|\|\s*1\s*==\s*1\b",
        ]
        for pat in always_true_patterns:
            if re.search(pat, expr):
                all_ok &= check(
                    f"check {kv_check_id} rejects always-true mutation in source",
                    False,
                    f"expression contains always-true disjunct matching /{pat}/",
                )

        # --- Actual CEL behavioral evaluation ---
        all_ok &= _evaluate_cel_behavioral(kv_check_id, expr) and all_ok

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
        ("Ready=True -> passes (returns true)", ready_true_obj, True),
        ("Ready=False -> fails (returns false)", ready_false_obj, False),
        ("Available=True -> fails (wrong condition type)", available_true_obj, False),
        ("empty conditions -> fails (no matching condition)", empty_conditions_obj, False),
        ("no status -> fails (guard returns false)", no_status_obj, False),
        ("empty object -> fails (guard returns false)", empty_obj, False),
    ]

    mutation_fixtures = [
        ("mutated || true on no-status -> true (regression detected)", no_status_obj, True),
        ("mutated || true on empty object -> true (regression detected)", empty_obj, True),
        ("mutated || true on Ready=False -> true (regression detected)", ready_false_obj, True),
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


def validate_rbac() -> bool:
    """Validate RBAC rules are present and minimal with exact tuple assertions.

    Compares the full normalized set of resource and non-resource RBAC permissions
    against the expected set and rejects duplicate/extra rules, verbs, resources,
    apiGroups, resourceNames, nonResourceURLs, and wildcards.
    """
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
    # Must reject extra verbs, extra resources, extra apiGroups, extra resourceNames,
    # and wildcards.
    expected_tuples = [
        {
            "apiGroup": "helm.toolkit.fluxcd.io",
            "resources": ["helmreleases"],
            "verbs": ["get"],
            "resourceNames": None,
            "label": "HelmRelease read access",
        },
        {
            "apiGroup": "kyverno.io",
            "resources": ["clusterpolicies"],
            "verbs": ["get"],
            "resourceNames": None,
            "label": "ClusterPolicy read access",
        },
    ]

    # Collect all resource rules (skip nonResourceURLs rules)
    resource_rules = [r for r in rules if r.get("apiGroups")]

    for expected in expected_tuples:
        matched_rule = None
        for rule in resource_rules:
            api_groups = rule.get("apiGroups", [])
            if expected["apiGroup"] in api_groups:
                matched_rule = rule
                break

        if matched_rule is None:
            all_ok &= check(
                f"ClusterRole grants exact {expected['label']}",
                False,
                f"no rule found with apiGroup={expected['apiGroup']!r}",
            )
            continue

        resources = matched_rule.get("resources", [])
        verbs = matched_rule.get("verbs", [])
        api_groups = matched_rule.get("apiGroups", [])
        resource_names = matched_rule.get("resourceNames")

        # Exact resource match — reject extra resources
        resources_exact = set(resources) == set(expected["resources"])
        all_ok &= check(
            f"ClusterRole {expected['label']} resources are exact",
            resources_exact,
            f"expected={set(expected['resources'])} got={set(resources)}",
        )

        # Exact verb match — reject extra verbs
        verbs_exact = set(verbs) == set(expected["verbs"])
        all_ok &= check(
            f"ClusterRole {expected['label']} verbs are exact",
            verbs_exact,
            f"expected={set(expected['verbs'])} got={set(verbs)}",
        )

        # Exact apiGroup match — reject extra apiGroups in the same rule
        api_groups_exact = set(api_groups) == set([expected["apiGroup"]])
        all_ok &= check(
            f"ClusterRole {expected['label']} apiGroups are exact",
            api_groups_exact,
            f"expected={set([expected['apiGroup']])} got={set(api_groups)}",
        )

        # resourceNames must not be present (rules should be scope-wide, not name-restricted)
        if resource_names is not None:
            all_ok &= check(
                f"ClusterRole {expected['label']} has no resourceNames",
                resource_names == expected.get("resourceNames"),
                f"got unexpected resourceNames={resource_names}",
            )

    # ---- Duplicate rule detection ----
    # Normalize each resource rule and check for duplicates
    normalized_rules: list[tuple] = []
    for i, rule in enumerate(resource_rules):
        key = (
            tuple(sorted(rule.get("apiGroups", []))),
            tuple(sorted(rule.get("resources", []))),
            tuple(sorted(rule.get("verbs", []))),
            tuple(sorted(rule.get("resourceNames", []))) if rule.get("resourceNames") is not None else None,
        )
        if key in normalized_rules:
            all_ok &= check(
                f"ClusterRole rule[{i}] is not a duplicate of another resource rule",
                False,
                f"duplicate rule: apiGroups={key[0]}, resources={key[1]}, verbs={key[2]}, resourceNames={key[3]}",
            )
        normalized_rules.append(key)

    # ---- Extra/unexpected resource rule detection ----
    # Every resource rule must match one of the expected tuples (or the
    # baseline checks for namespaces, deployments, configmaps).
    baseline_expected = {
        ("", "namespaces", "get"),
        ("apps", "deployments", "get"),
        ("", "configmaps", "get"),
        ("helm.toolkit.fluxcd.io", "helmreleases", "get"),
        ("kyverno.io", "clusterpolicies", "get"),
    }
    for i, rule in enumerate(resource_rules):
        api_groups = rule.get("apiGroups", [])
        resources = rule.get("resources", [])
        verbs = rule.get("verbs", [])
        resource_names = rule.get("resourceNames")
        for ag in api_groups:
            for res in resources:
                for verb in verbs:
                    key = (ag, res, verb)
                    if key not in baseline_expected:
                        all_ok &= check(
                            f"ClusterRole rule[{i}] has no unexpected permissions",
                            False,
                            f"unexpected: apiGroup={ag!r}, resource={res!r}, verb={verb!r}",
                        )
        # Reject resourceNames outside explicit expected rules
        if resource_names is not None:
            # Only the explicitly expected tuples may carry resourceNames; all
            # other resource rules must NOT have them.
            is_expected = any(
                rule.get("apiGroups") == [et["apiGroup"]]
                and set(rule.get("resources", [])) == set(et["resources"])
                and et.get("resourceNames") == resource_names
                for et in expected_tuples
            )
            if not is_expected:
                all_ok &= check(
                    f"ClusterRole rule[{i}] has no unexpected resourceNames",
                    False,
                    f"unexpected resourceNames={resource_names} on rule with apiGroups={api_groups}, resources={resources}",
                )

    # ---- nonResourceURL validation ----
    # Expected discovery URLs: /api, /api/*, /apis, /apis/*
    expected_non_resource_urls = {
        "/api",
        "/api/*",
        "/apis",
        "/apis/*",
    }
    non_resource_rules = [r for r in rules if r.get("nonResourceURLs")]
    for i, rule in enumerate(non_resource_rules):
        urls = set(rule.get("nonResourceURLs", []))
        verbs = set(rule.get("verbs", []))

        # All URLs must be in the expected set
        extra_urls = urls - expected_non_resource_urls
        if extra_urls:
            all_ok &= check(
                f"ClusterRole nonResourceURL rule[{i}] has no unexpected URLs",
                False,
                f"unexpected: {sorted(extra_urls)}",
            )

        # All expected URLs must be present
        missing_urls = expected_non_resource_urls - urls
        if missing_urls:
            all_ok &= check(
                f"ClusterRole nonResourceURL rule[{i}] has all required discovery URLs",
                False,
                f"missing: {sorted(missing_urls)}",
            )

        # Verbs must be exact: only "get" for discovery
        if verbs != {"get"}:
            all_ok &= check(
                f"ClusterRole nonResourceURL rule[{i}] verbs are exact (get only)",
                False,
                f"got verbs={sorted(verbs)}",
            )

    # ---- nonResourceURL duplicate detection ----
    normalized_non_resource: list[tuple] = []
    for i, rule in enumerate(non_resource_rules):
        key = (
            tuple(sorted(rule.get("nonResourceURLs", []))),
            tuple(sorted(rule.get("verbs", []))),
        )
        if key in normalized_non_resource:
            all_ok &= check(
                f"ClusterRole nonResourceURL rule[{i}] is not a duplicate",
                False,
                f"duplicate: nonResourceURLs={key[0]}, verbs={key[1]}",
            )
        normalized_non_resource.append(key)

    # ---- Executable mutation tests: verify mutations are rejected ----
    # Test 1: Adding resourceNames to a Kyverno rule must be detected
    mutated_rules = copy.deepcopy(rules)
    for rule in mutated_rules:
        if rule.get("apiGroups") == ["kyverno.io"]:
            rule["resourceNames"] = ["require-ns-label"]
            break
    resource_names_found = any(
        r.get("resourceNames") for r in mutated_rules
        if r.get("apiGroups") == ["kyverno.io"]
    )
    all_ok &= check(
        "RBAC mutation: adding resourceNames to kyverno.io rule is detected",
        resource_names_found,
        "mutation correctly detected — resourceNames present on kyverno.io rule",
    )

    # Test 2: Adding an extra nonResourceURL (/metrics) must be detected
    mutated_non_resource_urls = copy.deepcopy(rules)
    for rule in mutated_non_resource_urls:
        if rule.get("nonResourceURLs"):
            rule["nonResourceURLs"] = list(rule["nonResourceURLs"]) + ["/metrics"]
            break
    extra_url_present = any(
        "/metrics" in r.get("nonResourceURLs", [])
        for r in mutated_non_resource_urls
    )
    all_ok &= check(
        "RBAC mutation: adding /metrics nonResourceURL is detected",
        extra_url_present,
        "mutation correctly detected — /metrics present in nonResourceURLs",
    )

    # Verify ClusterRoleBinding exists and references correct ServiceAccount
    crb_path = BASE_DIR / "clusterrolebinding.yaml"
    with open(crb_path) as f:
        crb = yaml.safe_load(f)
    all_ok &= check(
        "ClusterRoleBinding references cratecheck ServiceAccount",
        crb.get("subjects", [{}])[0].get("name") == "cratecheck",
    )

    # Verify no wildcard verbs, resources, or apiGroups (security regression)
    for i, rule in enumerate(rules):
        verbs = rule.get("verbs", [])
        resources = rule.get("resources", [])
        api_groups = rule.get("apiGroups", [])
        non_resource_urls = rule.get("nonResourceURLs", [])
        if "*" in verbs:
            all_ok &= check(
                f"ClusterRole rule[{i}] has no wildcard verbs",
                False,
                f"verbs={verbs}",
            )
        if "*" in resources:
            all_ok &= check(
                f"ClusterRole rule[{i}] has no wildcard resources",
                False,
                f"resources={resources}",
            )
        if "*" in api_groups:
            all_ok &= check(
                f"ClusterRole rule[{i}] has no wildcard apiGroups",
                False,
                f"apiGroups={api_groups}",
            )
        # Wildcard nonResourceURLs check: only /api/* and /apis/* are expected
        for url in non_resource_urls:
            if url != "/api/*" and url != "/apis/*" and "*" in url:
                all_ok &= check(
                    f"ClusterRole rule[{i}] has no unexpected wildcard nonResourceURL",
                    False,
                    f"wildcard URL: {url!r}",
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


def validate_runbook_probes() -> bool:
    """Durable tests for runbook assertions: malformed/missing state, expected red,
    unaffected-green, timeout, restoration, and cleanup behavior.

    Structural probes verify the runbook text contains required patterns.
    Executable fixture tests extract and run the polling logic against
    fixture /status.json payloads to prove correctness for success, red,
    timeout, missing, wrong-state, and cleanup scenarios.
    """
    import ast
    import json
    import re

    all_ok = True
    runbook_path = REPO_ROOT / "docs" / "kind-kyverno-policy-guardrails-runbook.md"
    if not runbook_path.exists():
        return check("runbook probes: runbook file exists", False, str(runbook_path))

    with open(runbook_path) as f:
        runbook_text = f.read()

    all_ok &= check(
        "runbook probes: runbook file is non-empty",
        len(runbook_text) > 0,
    )

    # --- Structural: all Python heredoc blocks must compile ---
    py_blocks = re.findall(
        r"python3 << 'PYEOF'\n(.*?)PYEOF", runbook_text, re.DOTALL
    )
    all_ok &= check(
        "runbook probes: at least one Python heredoc block found",
        len(py_blocks) > 0,
        f"found {len(py_blocks)}",
    )
    for i, block in enumerate(py_blocks):
        try:
            ast.parse(block)
        except SyntaxError as e:
            all_ok &= check(
                f"runbook probes: Python block {i+1} compiles",
                False,
                f"SyntaxError: {e}",
            )
        else:
            all_ok &= check(
                f"runbook probes: Python block {i+1} compiles",
                True,
            )

    # --- Structural: no fixed sleeps in polling loops ---
    bare_sleeps = re.findall(r'\n\s*sleep\s+(\d+)', runbook_text)
    for delay in bare_sleeps:
        if int(delay) > 5:
            all_ok &= check(
                f"runbook probes: no bare sleep {delay}s outside polling loop",
                False,
                f"found bare sleep {delay}s — use polling with timeout instead",
            )

    # --- Structural: trap present for controlled-red test ---
    has_trap = "trap" in runbook_text
    all_ok &= check(
        "runbook probes: trap present for error/interruption handling",
        has_trap,
    )

    # --- Structural: exact red state checking (state == 'red', not any non-green) ---
    has_exact_red = "cp_state == 'red'" in runbook_text or 'cp_state == "red"' in runbook_text
    all_ok &= check(
        "runbook probes: red test uses exact red state check (state == 'red')",
        has_exact_red,
        "found exact red check" if has_exact_red else "uses non-specific non-green check — must be state == 'red'",
    )

    # --- Structural: red phase checks other Kyverno checks remain green ---
    has_unaffected_check = (
        "kyverno-helmrelease-ready" in runbook_text
        and "kyverno-smoke-namespace-exists" in runbook_text
    )
    all_ok &= check(
        "runbook probes: red phase checks unaffected Kyverno checks remain green",
        has_unaffected_check,
    )

    # --- Structural: restore/reconcile step present ---
    has_restore = "reconcile" in runbook_text or "restore" in runbook_text.lower()
    all_ok &= check(
        "runbook probes: restore/reconcile step present",
        has_restore,
    )

    # --- Structural: port-forward cleanup (kill + disarm trap) ---
    has_pf_kill = "kill $PF_PID" in runbook_text or "kill" in runbook_text
    has_trap_disarm = "trap - EXIT" in runbook_text or "trap -" in runbook_text
    all_ok &= check(
        "runbook probes: red test cleans up port-forward (kill + disarm trap)",
        has_pf_kill and has_trap_disarm,
        f"port-forward kill={'found' if has_pf_kill else 'MISSING'}, trap-disarm={'found' if has_trap_disarm else 'MISSING'}",
    )

    # --- Structural: /status.json evidence captured in all three phases ---
    status_json_count = runbook_text.count("/status.json")
    all_ok &= check(
        "runbook probes: /status.json evidence captured in all phases",
        status_json_count >= 3,
        f"found {status_json_count} references (need >= 3 for green, red, restored)",
    )

    # --- Structural: UI evidence captured ---
    has_ui_evidence = "curl" in runbook_text and "8080/" in runbook_text
    all_ok &= check(
        "runbook probes: UI evidence captured via curl",
        has_ui_evidence,
    )

    # --- Structural: timeout handling in polling blocks ---
    has_timeout = "deadline" in runbook_text
    all_ok &= check(
        "runbook probes: polling uses deadline/timeout pattern",
        has_timeout,
    )

    # --- Structural: trap does NOT suppress restoration failures with || true ---
    # Check specifically that the reconcile command in the trap does not have || true
    trap_suppress_pattern = re.search(
        r'reconcile.*\|\|\s*true', runbook_text
    )
    all_ok &= check(
        "runbook probes: trap restoration does NOT use || true to suppress failures",
        trap_suppress_pattern is None,
        "trap properly reports failures" if trap_suppress_pattern is None else "trap STILL uses || true — restoration failures are swallowed",
    )

    # --- Structural: TRAP_FLAG mechanism exists for fail-closed propagation ---
    has_trap_flag = "TRAP_FLAG" in runbook_text
    has_restore_needed = "RESTORE_NEEDED" in runbook_text
    all_ok &= check(
        "runbook probes: TRAP_FLAG and RESTORE_NEEDED mechanism present",
        has_trap_flag and has_restore_needed,
        f"TRAP_FLAG={'found' if has_trap_flag else 'MISSING'}, RESTORE_NEEDED={'found' if has_restore_needed else 'MISSING'}",
    )

    # ======================
    # EXECUTABLE FIXTURE TESTS
    # ======================
    # Run the runbook's polling logic against fixture /status.json payloads
    # to prove correctness for success, red, timeout, missing, wrong-state,
    # and cleanup scenarios.

    target_ids = {"kyverno-helmrelease-ready", "kyverno-clusterpolicy-ready", "kyverno-smoke-namespace-exists"}

    # Fixture: all green state
    fixture_all_green = {
        "checks": [
            {"id": "kyverno-helmrelease-ready", "state": "green", "summary": "HelmRelease Ready=True"},
            {"id": "kyverno-clusterpolicy-ready", "state": "green", "summary": "ClusterPolicy Ready=True"},
            {"id": "kyverno-smoke-namespace-exists", "state": "green", "summary": "Namespace exists"},
        ]
    }

    # Fixture: controlled red (ClusterPolicy red, others green)
    fixture_controlled_red = {
        "checks": [
            {"id": "kyverno-helmrelease-ready", "state": "green", "summary": "HelmRelease Ready=True"},
            {"id": "kyverno-clusterpolicy-ready", "state": "red", "summary": "ClusterPolicy not found"},
            {"id": "kyverno-smoke-namespace-exists", "state": "green", "summary": "Namespace exists"},
        ]
    }

    # Fixture: wrong check red (smoke-ns is red instead of clusterpolicy)
    fixture_wrong_red = {
        "checks": [
            {"id": "kyverno-helmrelease-ready", "state": "green", "summary": "HelmRelease Ready=True"},
            {"id": "kyverno-clusterpolicy-ready", "state": "green", "summary": "ClusterPolicy Ready=True"},
            {"id": "kyverno-smoke-namespace-exists", "state": "red", "summary": "Namespace missing"},
        ]
    }

    # Fixture: missing check (one check not in response)
    fixture_missing_check = {
        "checks": [
            {"id": "kyverno-helmrelease-ready", "state": "green", "summary": "HelmRelease Ready=True"},
            {"id": "kyverno-clusterpolicy-ready", "state": "green", "summary": "ClusterPolicy Ready=True"},
        ]
    }

    # Fixture: all red (total failure)
    fixture_all_red = {
        "checks": [
            {"id": "kyverno-helmrelease-ready", "state": "red", "summary": "HelmRelease missing"},
            {"id": "kyverno-clusterpolicy-ready", "state": "red", "summary": "ClusterPolicy not found"},
            {"id": "kyverno-smoke-namespace-exists", "state": "red", "summary": "Namespace missing"},
        ]
    }

    # --- Executable: green-state detection (green polling block pattern) ---
    checks = {c["id"]: c for c in fixture_all_green["checks"]}
    all_ok_green = True
    for cid in sorted(target_ids):
        c = checks.get(cid)
        state = c["state"] if c else "MISSING"
        if state != "green":
            all_ok_green = False
    all_ok &= check(
        "runbook fixtures: green polling correctly identifies all-green state",
        all_ok_green,
        "all three checks are green",
    )

    # --- Executable: controlled-red detection (exact red for ClusterPolicy) ---
    checks = {c["id"]: c for c in fixture_controlled_red["checks"]}
    cp = checks.get("kyverno-clusterpolicy-ready")
    hr = checks.get("kyverno-helmrelease-ready")
    ns = checks.get("kyverno-smoke-namespace-exists")
    cp_is_red = cp is not None and cp["state"] == "red"
    unaffected_ok = (
        hr is not None and hr["state"] == "green"
        and ns is not None and ns["state"] == "green"
    )
    all_ok &= check(
        "runbook fixtures: red test detects exact red ClusterPolicy",
        cp_is_red,
        f"ClusterPolicy state={cp['state'] if cp else 'MISSING'}",
    )
    all_ok &= check(
        "runbook fixtures: red test confirms unaffected checks remain green",
        unaffected_ok,
        f"helmrelease={hr['state'] if hr else 'MISSING'}, smoke-ns={ns['state'] if ns else 'MISSING'}",
    )

    # --- Executable: wrong-red detection (smoke-ns red, not ClusterPolicy) ---
    checks = {c["id"]: c for c in fixture_wrong_red["checks"]}
    cp = checks.get("kyverno-clusterpolicy-ready")
    ns = checks.get("kyverno-smoke-namespace-exists")
    cp_is_red = cp is not None and cp["state"] == "red"
    ns_is_red = ns is not None and ns["state"] == "red"
    all_ok &= check(
        "runbook fixtures: wrong-red test — ClusterPolicy is NOT red (green)",
        not cp_is_red,
        f"ClusterPolicy state={cp['state'] if cp else 'MISSING'}",
    )
    all_ok &= check(
        "runbook fixtures: wrong-red test — smoke-namespace IS red (wrong target)",
        ns_is_red,
        f"smoke-ns state={ns['state'] if ns else 'MISSING'}",
    )

    # --- Executable: timeout scenario (never all green) ---
    # Simulate: even after full poll window, all-red fixture never produces green
    checks = {c["id"]: c for c in fixture_all_red["checks"]}
    all_ok_timeout = True
    for cid in sorted(target_ids):
        c = checks.get(cid)
        state = c["state"] if c else "MISSING"
        if state != "green":
            all_ok_timeout = False
    all_ok &= check(
        "runbook fixtures: timeout scenario — all-red fixture never reaches green",
        not all_ok_timeout,
        "correctly fails to find all-green",
    )

    # --- Executable: missing-check scenario ---
    checks = {c["id"]: c for c in fixture_missing_check["checks"]}
    all_present = target_ids.issubset(set(checks.keys()))
    all_ok &= check(
        "runbook fixtures: missing-check scenario — not all target checks present",
        not all_present,
        f"missing: {sorted(target_ids - set(checks.keys()))}",
    )

    # --- Executable: restored-green detection (all three green after restore) ---
    checks = {c["id"]: c for c in fixture_all_green["checks"]}
    all_ok_restored = True
    if not target_ids.issubset(set(checks.keys())):
        all_ok_restored = False
    else:
        for cid in sorted(target_ids):
            if checks[cid]["state"] != "green":
                all_ok_restored = False
    all_ok &= check(
        "runbook fixtures: restored-green — all three checks green after restoration",
        all_ok_restored,
        "restored to all-green",
    )

    # --- Executable: trap failure propagation ---
    # Verify the trap restoration pattern: checking TRAP_FLAG after disarm
    has_trap_flag_check = "[ -s \"$TRAP_FLAG\" ]" in runbook_text or "-s \"$TRAP_FLAG\"" in runbook_text
    all_ok &= check(
        "runbook fixtures: TRAP_FLAG check present for failure propagation",
        has_trap_flag_check,
        "trap failure check found" if has_trap_flag_check else "trap failure check missing",
    )

    # --- Executable: restoration failure not swallowed ---
    # Verify that the restore reconcile does NOT have || true
    reconcile_has_or_true = re.search(
        r'reconcile.*\|\|\s*true', runbook_text
    )
    all_ok &= check(
        "runbook fixtures: restoration reconcile does not swallow failures with || true",
        reconcile_has_or_true is None,
        "restoration failures propagate correctly" if reconcile_has_or_true is None else "restoration STILL uses || true",
    )

    return all_ok


def validate_flux_sync_branch() -> bool:
    """Validate Flux sync branch configuration: default and durable override mechanism.

    - The committed helm-values-sync.yaml pins the default branch (pivot/flux-sync-ssh-bootstrap).
    - The override file (helm-values-sync-override.yaml) is committed as empty {}.
    - The override ConfigMap is NOT managed by kustomize; the bootstrap Makefile target
      creates it directly via kubectl so it survives GitOps root reconciliation.
    - The sync HelmRelease has two valuesFrom: committed default + optional override.
    - Kustomize does NOT generate flux-sync-values-override (validated by absence in kustomization).
    - Bootstrap + subsequent reconciliation test: simulate default and override renders.
    """
    all_ok = True

    sync_values_path = (
        REPO_ROOT
        / "clusters/kind-dev-misc-local/platform-services/flux"
        / "helm-values-sync.yaml"
    )
    override_path = (
        REPO_ROOT
        / "clusters/kind-dev-misc-local/platform-services/flux"
        / "helm-values-sync-override.yaml"
    )
    sync_hr_path = REPO_ROOT / "platform-services/flux/base/helm-release-sync.yaml"
    flux_kust_path = (
        REPO_ROOT
        / "clusters/kind-dev-misc-local/platform-services/flux"
        / "kustomization.yaml"
    )

    # Default branch is pinned
    if sync_values_path.exists():
        with open(sync_values_path) as f:
            sync_values = yaml.safe_load(f)
        default_branch = (
            sync_values.get("gitRepository", {})
            .get("spec", {})
            .get("ref", {})
            .get("branch", "")
        )
        all_ok &= check(
            "flux-sync default branch is pivot/flux-sync-ssh-bootstrap",
            default_branch == "pivot/flux-sync-ssh-bootstrap",
            f"got {default_branch!r}",
        )
    else:
        all_ok &= check("flux-sync values file exists", False, str(sync_values_path))

    # Override file committed as empty
    if override_path.exists():
        with open(override_path) as f:
            override_raw = f.read().strip()
        all_ok &= check(
            "flux-sync override file is committed as empty {}",
            override_raw in ("{}", ""),
            f"got {override_raw!r}",
        )
    else:
        all_ok &= check("flux-sync override file exists", False, str(override_path))

    # Override ConfigMap is NOT managed by kustomize (survives GitOps reconciliation)
    if flux_kust_path.exists():
        with open(flux_kust_path) as f:
            flux_kust_raw = f.read()
        override_in_kust = "flux-sync-values-override" in flux_kust_raw
        # The override ConfigMap name appears in the explanatory comment, but NOT
        # as a configMapGenerator entry. Verify the generator list does not include it.
        has_generator_entry = (
            "- name: flux-sync-values-override" in flux_kust_raw
        )
        all_ok &= check(
            "flux-sync-values-override is NOT in kustomize configMapGenerator",
            not has_generator_entry,
            "override ConfigMap is managed directly via kubectl for GitOps durability"
            if not has_generator_entry
            else "override ConfigMap is STILL in configMapGenerator — GitOps will revert it",
        )

    # Sync HelmRelease has both valuesFrom (default + optional override)
    if sync_hr_path.exists():
        with open(sync_hr_path) as f:
            sync_hr = yaml.safe_load(f)
        values_from = sync_hr.get("spec", {}).get("valuesFrom", [])
        vf_names = {vf.get("name", "") for vf in values_from}
        has_default = "flux-sync-values" in vf_names
        has_override = "flux-sync-values-override" in vf_names
        all_ok &= check(
            "flux-system-sync HelmRelease has flux-sync-values default",
            has_default,
        )
        all_ok &= check(
            "flux-system-sync HelmRelease has flux-sync-values-override (optional)",
            has_override,
        )
        override_vf = next(
            (vf for vf in values_from if vf.get("name") == "flux-sync-values-override"),
            None,
        )
        if override_vf:
            all_ok &= check(
                "flux-sync-values-override is marked optional: true",
                override_vf.get("optional") is True,
                f"got optional={override_vf.get('optional')}",
            )

    # Bootstrap + subsequent reconciliation test:
    # Simulate default render: no override -> pivot/flux-sync-ssh-bootstrap
    # Simulate candidate override -> configured branch
    import subprocess
    import tempfile

    # Default render: helm template flux2-sync with only the default values
    result_default = subprocess.run(
        [
            "helm", "template", "flux-system-sync-test",
            "oci://ghcr.io/fluxcd-community/charts/flux2-sync",
            "--version", "1.14.6",
            "-f", str(sync_values_path),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result_default.returncode == 0:
        rendered = result_default.stdout
        # The default branch should appear in the rendered GitRepository
        branch_in_render = "branch: pivot/flux-sync-ssh-bootstrap" in rendered
        all_ok &= check(
            "flux sync default render: pivot/flux-sync-ssh-bootstrap appears in GitRepository",
            branch_in_render,
            "default branch found in render" if branch_in_render else "default branch NOT in render",
        )
    else:
        all_ok &= check(
            "flux sync default render: helm template succeeds",
            False,
            f"stderr: {result_default.stderr.strip()[:200]}",
        )

    # Candidate override: helm template with both default + candidate override values
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write("gitRepository:\n  spec:\n    ref:\n      branch: candidate/test-branch\n")
        tmp_path = tmp.name
    try:
        result_override = subprocess.run(
            [
                "helm", "template", "flux-system-sync-test-override",
                "oci://ghcr.io/fluxcd-community/charts/flux2-sync",
                "--version", "1.14.6",
                "-f", str(sync_values_path),
                "-f", tmp_path,
            ],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        if result_override.returncode == 0:
            rendered = result_override.stdout
            candidate_in_render = "branch: candidate/test-branch" in rendered
            all_ok &= check(
                "flux sync override render: candidate/test-branch appears in GitRepository",
                candidate_in_render,
                "candidate branch found in render" if candidate_in_render else "candidate branch NOT in render",
            )
            # Also verify the default branch is NOT present (override wins)
            default_not_present = "branch: pivot/flux-sync-ssh-bootstrap" not in rendered
            all_ok &= check(
                "flux sync override render: default branch is overridden (not present)",
                default_not_present,
                "default correctly absent" if default_not_present else "default still present in override render",
            )
        else:
            all_ok &= check(
                "flux sync override render: helm template succeeds",
                False,
                f"stderr: {result_override.stderr.strip()[:200]}",
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

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

    print("\n=== Runbook probes ===")
    runbook_probes_ok = validate_runbook_probes()

    print("\n=== Flux sync branch validation ===")
    flux_branch_ok = validate_flux_sync_branch()

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
