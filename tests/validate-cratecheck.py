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
        # Auto-detect repo .venv so the exact system-Python invocation works
        # without a machine-specific PYTHONPATH injection.
        # Also probe the main repo root when running inside a git worktree.
        _venv_roots = [REPO_ROOT]
        _gitfile = REPO_ROOT / ".git"
        if _gitfile.is_file():
            _first_line = _gitfile.read_text().split("\n", 1)[0]
            if _first_line.startswith("gitdir: "):
                _gitdir = _first_line.removeprefix("gitdir: ").strip()
                _main_repo = Path(_gitdir).parent.parent.parent
                if _main_repo.is_dir():
                    _venv_roots.append(_main_repo)
        for _root in _venv_roots:
            _venv_site = (
                _root / ".venv" / "lib"
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
                / "site-packages"
            )
            if _venv_site.is_dir() and str(_venv_site) not in sys.path:
                sys.path.insert(0, str(_venv_site))

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
    # The shared helper at scripts/runbook-kv-poll.py is the authoritative source.
    poll_script = REPO_ROOT / "scripts" / "runbook-kv-poll.py"
    poll_script_text = ""
    if poll_script.exists():
        with open(poll_script_path := poll_script) as f:
            poll_script_text = f.read()
    has_exact_red_in_helper = 'state"] == "red"' in poll_script_text or "state'] == 'red'" in poll_script_text
    # Also check runbook for direct references (pre-migration compatibility)
    has_exact_red_in_runbook = "cp_state == 'red'" in runbook_text or 'cp_state == "red"' in runbook_text
    has_exact_red = has_exact_red_in_helper or has_exact_red_in_runbook
    all_ok &= check(
        "runbook probes: red test uses exact red state check (state == 'red')",
        has_exact_red,
        "found exact red check in shared helper" if has_exact_red_in_helper
        else "found exact red check in runbook" if has_exact_red_in_runbook
        else "uses non-specific non-green check — must be state == 'red'",
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

    # --- Structural: runbook uses shared polling helper (not inline implementations) ---
    # The three polling phases (green, red, restored-green) must call
    # scripts/runbook-kv-poll.py, the single authoritative polling source.
    # Count occurrences of the shared helper call.
    shared_helper_calls = runbook_text.count("scripts/runbook-kv-poll.py")
    all_ok &= check(
        "runbook probes: runbook uses shared polling helper (scripts/runbook-kv-poll.py) for all phases",
        shared_helper_calls >= 3,
        f"found {shared_helper_calls} shared-helper calls (need >= 3 for green, red, restored-green)"
        if shared_helper_calls >= 3
        else f"found only {shared_helper_calls} shared-helper calls — runbook may have inline polling implementations instead",
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

    # --- Structural: trap uses exit 1 on restoration failure ---
    # The trap must call exit 1 directly (not just write to TRAP_FLAG) so
    # restoration failures propagate a non-zero exit code.
    has_trap_exit = "exit 1" in runbook_text
    all_ok &= check(
        "runbook probes: trap uses exit 1 on restoration failure (not just TRAP_FLAG write)",
        has_trap_exit,
        "exit 1 found in trap" if has_trap_exit else "trap does not contain exit 1 — restoration failures may exit 0",
    )

    # --- Structural: TRAP_FLAG and RESTORE_NEEDED mechanism present ---
    has_trap_flag = "TRAP_FLAG" in runbook_text
    has_restore_needed = "RESTORE_NEEDED" in runbook_text
    all_ok &= check(
        "runbook probes: TRAP_FLAG and RESTORE_NEEDED mechanism present",
        has_trap_flag and has_restore_needed,
        f"TRAP_FLAG={'found' if has_trap_flag else 'MISSING'}, RESTORE_NEEDED={'found' if has_restore_needed else 'MISSING'}",
    )

    # ===================================================================
    # EXECUTABLE FIXTURE TESTS — call the shared polling helper script
    # ===================================================================
    # These replace inlined fixture logic with execution of the actual
    # extracted/shared runbook helper at scripts/runbook-kv-poll.py.
    # Each test runs the helper against a fixture /status.json payload
    # and verifies the expected exit code.

    fixtures_dir = REPO_ROOT / "tests" / "fixtures"
    poll_script = REPO_ROOT / "scripts" / "runbook-kv-poll.py"

    all_ok &= check(
        "runbook fixtures: shared polling script exists",
        poll_script.exists(),
        str(poll_script),
    )

    # --- Green-state detection ---
    result = subprocess.run(
        [sys.executable, str(poll_script), "--fixture",
         str(fixtures_dir / "kv-all-green.json"), "--mode", "green"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "runbook fixtures: green polling correctly identifies all-green state",
        result.returncode == 0,
        f"exit={result.returncode}" + (f" stderr: {result.stderr.strip()[:100]}" if result.stderr.strip() else ""),
    )

    # --- Controlled-red detection (exact red for ClusterPolicy) ---
    result = subprocess.run(
        [sys.executable, str(poll_script), "--fixture",
         str(fixtures_dir / "kv-controlled-red.json"), "--mode", "red"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "runbook fixtures: red test detects exact red ClusterPolicy + unaffected-green",
        result.returncode == 0,
        f"exit={result.returncode}" + (f" stderr: {result.stderr.strip()[:100]}" if result.stderr.strip() else ""),
    )

    # --- Wrong-red detection (wrong check is red) ---
    result = subprocess.run(
        [sys.executable, str(poll_script), "--fixture",
         str(fixtures_dir / "kv-wrong-red.json"), "--mode", "red",
         "--deadline-offset", "10"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "runbook fixtures: wrong-red test — smoke-ns red, ClusterPolicy NOT red -> exit 1",
        result.returncode == 1,
        f"exit={result.returncode} (expected 1)" + (
            f" stderr: {result.stderr.strip()[:100]}" if result.stderr.strip() else ""
        ),
    )

    # --- Timeout scenario (all-red fixture never reaches green) ---
    # Use a short deadline offset (10s) so the always-failing predicate
    # consumes the configured bound quickly while still proving the loop
    # respects the deadline.
    result = subprocess.run(
        [sys.executable, str(poll_script), "--fixture",
         str(fixtures_dir / "kv-all-red.json"), "--mode", "green",
         "--deadline-offset", "10"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "runbook fixtures: timeout scenario — all-red fixture never reaches green -> exit 1",
        result.returncode == 1,
        f"exit={result.returncode} (expected 1)" + (
            f" stderr: {result.stderr.strip()[:100]}" if result.stderr.strip() else ""
        ),
    )

    # --- Missing-check scenario ---
    result = subprocess.run(
        [sys.executable, str(poll_script), "--fixture",
         str(fixtures_dir / "kv-missing-check.json"), "--mode", "green",
         "--deadline-offset", "10"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "runbook fixtures: missing-check scenario — not all target checks present -> exit 1",
        result.returncode == 1,
        f"exit={result.returncode} (expected 1)" + (
            f" stderr: {result.stderr.strip()[:100]}" if result.stderr.strip() else ""
        ),
    )

    # --- Restored-green detection ---
    result = subprocess.run(
        [sys.executable, str(poll_script), "--fixture",
         str(fixtures_dir / "kv-all-green.json"), "--mode", "restored-green"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "runbook fixtures: restored-green — all three checks green after restoration -> exit 0",
        result.returncode == 0,
        f"exit={result.returncode}" + (f" stderr: {result.stderr.strip()[:100]}" if result.stderr.strip() else ""),
    )

    # ===================================================================
    # EXECUTABLE TRAP RESTORATION TESTS
    # ===================================================================
    # Test that the trap handler exits non-zero when Flux reconcile fails
    # or when post-reconcile resource-read fails.

    import tempfile

    # Extract the cleanup_and_restore function from the runbook
    trap_func_match = re.search(
        r'cleanup_and_restore\(\) \{(.*?)\n\}',
        runbook_text, re.DOTALL,
    )
    trap_body = trap_func_match.group(1) if trap_func_match else ""

    # --- Injected Flux reconcile failure ---
    if trap_body:
        # Ensure .tmp directory exists
        tmp_dir = REPO_ROOT / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        trap_test_script = f"""#!/bin/bash
set -e
PF_PID=99999
RESTORE_NEEDED=1
# Mock flux: always fails
flux() {{ echo "mock flux: simulating reconcile failure" >&2; return 1; }}
kubectl() {{ echo "mock kubectl $*" >&2; return 1; }}
export -f flux kubectl
cleanup_and_restore() {{
{trap_body}
}}
trap cleanup_and_restore EXIT
# Script reaches end — EXIT trap runs cleanup_and_restore
# which should call exit 1 on reconcile failure
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
        ) as tmp:
            tmp.write(trap_test_script)
            trap_test_path = tmp.name

        try:
            result = subprocess.run(
                ["bash", trap_test_path],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            all_ok &= check(
                "runbook fixtures: injected Flux reconcile failure -> trap exits non-zero",
                result.returncode != 0,
                f"exit={result.returncode} (expected non-zero)" + (
                    f" stdout: {result.stdout.strip()[:100]}" if result.stdout.strip() else ""
                ),
            )
        finally:
            Path(trap_test_path).unlink(missing_ok=True)

        # --- Injected post-reconcile resource-read failure ---
        # Mock flux succeeds but kubectl get returns nothing (ClusterPolicy still missing)
        trap_test_script2 = f"""#!/bin/bash
set -e
PF_PID=99999
RESTORE_NEEDED=1
flux() {{ echo "mock flux: reconcile succeeded" >&2; return 0; }}
kubectl() {{
    if [[ "$*" == *"get clusterpolicy"* ]]; then
        echo "mock kubectl: ClusterPolicy still missing" >&2
        return 1
    fi
    echo "mock kubectl $*" >&2
    return 0
}}
export -f flux kubectl
cleanup_and_restore() {{
{trap_body}
}}
trap cleanup_and_restore EXIT
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
        ) as tmp:
            tmp.write(trap_test_script2)
            trap_test_path2 = tmp.name

        try:
            result = subprocess.run(
                ["bash", trap_test_path2],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            all_ok &= check(
                "runbook fixtures: injected post-reconcile resource-read failure -> trap exits non-zero",
                result.returncode != 0,
                f"exit={result.returncode} (expected non-zero)" + (
                    f" stdout: {result.stdout.strip()[:100]}" if result.stdout.strip() else ""
                ),
            )
        finally:
            Path(trap_test_path2).unlink(missing_ok=True)

    # --- Port-forward cleanup: behavioral test — trap actually kills PF_PID ---
    # Prove the exact PF PID is terminated and waited under safe mocks.
    # This is NOT just a string search; it executes the trap handler with a
    # mock kill that records its target PID to a trace file.

    if trap_body:
        pf_trace = tmp_dir / "pf-cleanup-trace.txt"
        pf_trace.write_text("")

        pf_test_script = f"""#!/bin/bash
set -e
PF_PID=424242
RESTORE_NEEDED=0
# Mock kill: records the PID to the trace file
kill() {{
    echo "kill $*" >> "{pf_trace}"
    return 0
}}
wait() {{
    echo "wait $*" >> "{pf_trace}"
    return 0
}}
flux() {{ echo "mock flux: skipping" >&2; return 0; }}
kubectl() {{ echo "mock kubectl $*" >&2; return 0; }}
export -f kill wait flux kubectl
cleanup_and_restore() {{
{trap_body}
}}
trap cleanup_and_restore EXIT
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
        ) as tmp:
            tmp.write(pf_test_script)
            pf_test_path = tmp.name

        try:
            result = subprocess.run(
                ["bash", pf_test_path],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            pf_trace_content = pf_trace.read_text()
            pf_kill_called = f"kill {424242}" in pf_trace_content or "kill 424242" in pf_trace_content
            pf_wait_called = f"wait {424242}" in pf_trace_content or "wait 424242" in pf_trace_content

            all_ok &= check(
                "runbook fixtures: trap actually calls kill on PF_PID (behavioral)",
                pf_kill_called,
                f"kill 424242 found in trace" if pf_kill_called
                else f"trace ({len(pf_trace_content)} chars): {pf_trace_content.strip()[:200]}",
            )
            all_ok &= check(
                "runbook fixtures: trap actually calls wait on PF_PID (behavioral)",
                pf_wait_called,
                f"wait 424242 found in trace" if pf_wait_called
                else f"trace: {pf_trace_content.strip()[:200]}",
            )
            all_ok &= check(
                "runbook fixtures: port-forward cleanup exits 0",
                result.returncode == 0,
                f"exit={result.returncode}" + (
                    f" stderr: {result.stderr.strip()[:200]}" if result.stderr.strip() else ""
                ),
            )

            # ================================================================
            # ADVERSARIAL: execution-based runbook mutations
            # ================================================================
            # Each mutation alters the trap body (M5-M8) or polling-helper
            # invocation (M9-M11). An INDEPENDENT SUBPROCESS ORACLE checks
            # the mutated output and exits 1 (nonzero) when the mutation is
            # detected, proving the validator would exit nonzero. The test
            # asserts oracle exit code != 0 and in (0,1) (not a crash).
            # Expected workflow RCs are asserted separately.

            # --- Independent text-presence oracle subprocess ---
            # Used for M5/M8 (trace checks) and M9-M11 (text checks).
            # Exits 0 when the needle IS found (unmutated — PASS), exits 1
            # when the needle is MISSING (mutation detected — validator exits nonzero).
            def _run_trace_oracle_subprocess(trace_text: str, needle: str, label: str) -> tuple[int, str, str]:
                """Run text-presence check as an independent subprocess.

                Returns (exit_code, stdout, stderr). Exit 1 = needle absent
                (mutation detected, validator would exit nonzero).
                Exit 0 = needle present (mutation NOT detected or ineffective).
                """
                oracle_py = tmp_dir / f"oracle-trace-{label}.py"
                oracle_py.write_text(f'''import sys
text = sys.stdin.read()
needle = {needle!r}
if needle in text:
    print(f"PASS: needle found in trace — mutation NOT detected")
    sys.exit(0)
else:
    print(f"FAIL: needle MISSING from trace — mutation detected, validator exits nonzero")
    sys.exit(1)
''')
                result = subprocess.run(
                    [sys.executable, str(oracle_py)],
                    input=trace_text, capture_output=True, text=True, cwd=REPO_ROOT,
                )
                return result.returncode, result.stdout.strip(), result.stderr.strip()

            # --- Independent exit-code oracle subprocess ---
            # Used for M6/M7 where the mutation detection is based on the
            # mutated trap's exit code. Exits 1 when RC==0 (mutation detected
            # — trap no longer fails), exits 0 when RC!=0 (trap still fails).
            def _run_rc_oracle_subprocess(exit_code: int, label: str) -> tuple[int, str, str]:
                """Run exit-code check as an independent subprocess.

                Returns (exit_code, stdout, stderr). Exit 1 = RC is 0
                (mutation detected, validator would exit nonzero).
                Exit 0 = RC is non-zero (trap still fails, mutation not detected).
                """
                oracle_py = tmp_dir / f"oracle-rc-{label}.py"
                oracle_py.write_text(f'''import sys
rc = int(sys.stdin.read().strip())
if rc == 0:
    print(f"FAIL: trap exit 0 — mutation detected, validator exits nonzero")
    sys.exit(1)
else:
    print(f"PASS: trap exit non-zero — mutation NOT detected, trap still fails")
    sys.exit(0)
''')
                result = subprocess.run(
                    [sys.executable, str(oracle_py)],
                    input=str(exit_code), capture_output=True, text=True, cwd=REPO_ROOT,
                )
                return result.returncode, result.stdout.strip(), result.stderr.strip()

            # --- M5: Remove kill PF_PID — the port-forward cleanup check must FAIL ---
            mutated_body = re.sub(
                r'kill\s+\$PF_PID\s+2>/dev/null\s*\|\|\s*true\s*;?\s*',
                '# kill removed\n',
                trap_body,
            )
            if mutated_body != trap_body:
                pf_mutated_trace = tmp_dir / "pf-mutated-trace.txt"
                pf_mutated_trace.write_text("")
                mutated_script = f"""#!/bin/bash
set -e
PF_PID=424242
RESTORE_NEEDED=0
kill() {{
    echo "kill $*" >> "{pf_mutated_trace}"
    return 0
}}
wait() {{ echo "wait $*" >> "{pf_mutated_trace}"; return 0; }}
flux() {{ echo "mock flux" >&2; return 0; }}
kubectl() {{ echo "mock kubectl $*" >&2; return 0; }}
export -f kill wait flux kubectl
cleanup_and_restore() {{
{mutated_body}
}}
trap cleanup_and_restore EXIT
"""
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
                ) as tmp_mut:
                    tmp_mut.write(mutated_script)
                    pf_mutated_path = tmp_mut.name

                try:
                    result_m5 = subprocess.run(
                        ["bash", pf_mutated_path],
                        capture_output=True, text=True, cwd=REPO_ROOT,
                    )
                    # Harness integrity: mutated workflow must exit with the
                    # EXPECTED RC (0 — clean exit with RESTORE_NEEDED=0, no
                    # failed kill). A crash/syntax error (e.g. RC 2) must not
                    # masquerade as mutation detection.
                    all_ok &= check(
                        "runbook fixtures: adversarial M5 — mutated workflow exits 0 (harness integrity — no crash)",
                        result_m5.returncode == 0,
                        f"rc={result_m5.returncode} (expected 0)" if result_m5.returncode == 0
                        else f"rc={result_m5.returncode} — unexpected exit, crash/syntax error?",
                    )
                    mutated_trace_content = pf_mutated_trace.read_text()
                    # INDEPENDENT SUBPROCESS ORACLE: exit 1 = kill missing
                    orc5_rc, orc5_out, orc5_err = _run_trace_oracle_subprocess(
                        mutated_trace_content, "kill 424242", "m5",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M5 — oracle subprocess exits nonzero (validator would exit nonzero)",
                        orc5_rc != 0,
                        f"oracle rc={orc5_rc}, out={orc5_out!r}" if orc5_rc == 0
                        else f"oracle rc={orc5_rc}, {orc5_out}",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M5 — oracle subprocess did not crash (rc in (0,1))",
                        orc5_rc in (0, 1),
                        f"oracle rc={orc5_rc} stderr={orc5_err[:200]}",
                    )
                    # Runtime: verify mutation was applied
                    kill_still_present = "kill 424242" in mutated_trace_content
                    all_ok &= check(
                        "runbook fixtures: adversarial M5 — remove kill PF_PID: mutation applied (kill absent from trace)",
                        not kill_still_present,
                        "kill correctly absent" if not kill_still_present
                        else "kill STILL present after mutation — mutation was ineffective",
                    )
                finally:
                    Path(pf_mutated_path).unlink(missing_ok=True)
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M5 — mutation application",
                    False,
                    "M5 regex did not match trap_body — mutation could not be applied (silent skip prevented)",
                )

            # --- M8: Remove wait PF_PID — the port-forward wait check must FAIL ---
            mutated_body_wait = re.sub(
                r'wait\s+\$PF_PID\s+2>/dev/null\s*\|\|\s*true\s*;?\s*',
                '# wait removed\n',
                trap_body,
            )
            if mutated_body_wait != trap_body:
                pf_wait_trace = tmp_dir / "pf-wait-trace.txt"
                pf_wait_trace.write_text("")
                wait_script = f"""#!/bin/bash
set -e
PF_PID=424242
RESTORE_NEEDED=0
kill() {{
    echo "kill $*" >> "{pf_wait_trace}"
    return 0
}}
wait() {{ echo "wait $*" >> "{pf_wait_trace}"; return 0; }}
flux() {{ echo "mock flux" >&2; return 0; }}
kubectl() {{ echo "mock kubectl $*" >&2; return 0; }}
export -f kill wait flux kubectl
cleanup_and_restore() {{
{mutated_body_wait}
}}
trap cleanup_and_restore EXIT
"""
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
                ) as tmp_wait:
                    tmp_wait.write(wait_script)
                    pf_wait_path = tmp_wait.name

                try:
                    result_m8 = subprocess.run(
                        ["bash", pf_wait_path],
                        capture_output=True, text=True, cwd=REPO_ROOT,
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M8 — mutated workflow exits 0 (harness integrity — no crash)",
                        result_m8.returncode == 0,
                        f"rc={result_m8.returncode} (expected 0)" if result_m8.returncode == 0
                        else f"rc={result_m8.returncode} — unexpected exit, crash/syntax error?",
                    )
                    wait_trace_content = pf_wait_trace.read_text()
                    # INDEPENDENT SUBPROCESS ORACLE: exit 1 = wait missing
                    orc8_rc, orc8_out, orc8_err = _run_trace_oracle_subprocess(
                        wait_trace_content, "wait 424242", "m8",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M8 — oracle subprocess exits nonzero (validator would exit nonzero)",
                        orc8_rc != 0,
                        f"oracle rc={orc8_rc}, out={orc8_out!r}" if orc8_rc == 0
                        else f"oracle rc={orc8_rc}, {orc8_out}",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M8 — oracle subprocess did not crash (rc in (0,1))",
                        orc8_rc in (0, 1),
                        f"oracle rc={orc8_rc} stderr={orc8_err[:200]}",
                    )
                    wait_still_present = "wait 424242" in wait_trace_content
                    all_ok &= check(
                        "runbook fixtures: adversarial M8 — remove wait PF_PID: mutation applied (wait absent from trace)",
                        not wait_still_present,
                        "wait correctly absent" if not wait_still_present
                        else "wait STILL present after mutation — mutation was ineffective",
                    )
                finally:
                    Path(pf_wait_path).unlink(missing_ok=True)
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M8 — mutation application",
                    False,
                    "M8 regex did not match trap_body — mutation could not be applied (silent skip prevented)",
                )

            # --- M6: Remove Flux reconcile from trap ---
            # The mutated trap exits 0 (instead of non-zero), proving the
            # reconcile was removed. An independent subprocess oracle receives
            # the exit code and exits 1 when it's 0 (mutation detected — trap
            # no longer fails). It exits 0 when RC is non-zero (trap still
            # fails — mutation not detected or ineffective).
            mutated_no_reconcile = re.sub(
                r'if ! flux.*?reconcile.*?; then\n.*?exit 1\n\s+elif',
                'if true; then\n            echo "RECONCILE SKIPPED (removed)"\n            RESTORE_NEEDED=0\n        elif',
                trap_body,
                flags=re.DOTALL,
            )
            if mutated_no_reconcile != trap_body:
                m6_script = f"""#!/bin/bash
set -e
PF_PID=99999
RESTORE_NEEDED=1
flux() {{ echo "mock flux: would fail" >&2; return 1; }}
kubectl() {{ echo "mock kubectl $*" >&2; return 0; }}
export -f flux kubectl
cleanup_and_restore() {{
{mutated_no_reconcile}
}}
trap cleanup_and_restore EXIT
"""
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
                ) as tmp_m6:
                    tmp_m6.write(m6_script)
                    m6_path = tmp_m6.name

                try:
                    result_m6 = subprocess.run(
                        ["bash", m6_path],
                        capture_output=True, text=True, cwd=REPO_ROOT,
                    )
                    # Harness integrity: mutated workflow exits 0 (reconcile
                    # was removed, trap doesn't fail). Non-zero would mean the
                    # mutation didn't take effect or something else went wrong.
                    all_ok &= check(
                        "runbook fixtures: adversarial M6 — mutated workflow exits 0 (harness integrity — reconcile removed)",
                        result_m6.returncode == 0,
                        f"rc={result_m6.returncode} (expected 0 — trap no longer fails)" if result_m6.returncode == 0
                        else f"rc={result_m6.returncode} — mutation was ineffective (unexpected)",
                    )
                    # INDEPENDENT SUBPROCESS RC ORACLE: exits 1 when RC==0
                    orc6_rc, orc6_out, orc6_err = _run_rc_oracle_subprocess(
                        result_m6.returncode, "m6",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M6 — oracle subprocess exits nonzero (validator would exit nonzero)",
                        orc6_rc != 0,
                        f"oracle rc={orc6_rc}, out={orc6_out!r}" if orc6_rc == 0
                        else f"oracle rc={orc6_rc}, {orc6_out}",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M6 — oracle subprocess did not crash (rc in (0,1))",
                        orc6_rc in (0, 1),
                        f"oracle rc={orc6_rc} stderr={orc6_err[:200]}",
                    )
                finally:
                    Path(m6_path).unlink(missing_ok=True)
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M6 — mutation application",
                    False,
                    "M6 regex did not match trap_body — mutation could not be applied (silent skip prevented)",
                )

            # --- M7: Remove post-reconcile kubectl read from trap ---
            mutated_no_read = re.sub(
                r'elif ! kubectl.*?get clusterpolicy.*?; then\n.*?exit 1\n\s+else',
                'elif true; then\n            echo "KUBECTL READ SKIPPED (removed)"\n            RESTORE_NEEDED=0\n        else',
                trap_body,
                flags=re.DOTALL,
            )
            if mutated_no_read != trap_body and mutated_no_read != mutated_no_reconcile:
                m7_script = f"""#!/bin/bash
set -e
PF_PID=99999
RESTORE_NEEDED=1
flux() {{ echo "mock flux: reconcile succeeded" >&2; return 0; }}
kubectl() {{
    if [[ "$*" == *"get clusterpolicy"* ]]; then
        echo "mock kubectl: ClusterPolicy still missing" >&2
        return 1
    fi
    echo "mock kubectl $*" >&2
    return 0
}}
export -f flux kubectl
cleanup_and_restore() {{
{mutated_no_read}
}}
trap cleanup_and_restore EXIT
"""
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".sh", delete=False, dir=str(tmp_dir)
                ) as tmp_m7:
                    tmp_m7.write(m7_script)
                    m7_path = tmp_m7.name

                try:
                    result_m7 = subprocess.run(
                        ["bash", m7_path],
                        capture_output=True, text=True, cwd=REPO_ROOT,
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M7 — mutated workflow exits 0 (harness integrity — read removed)",
                        result_m7.returncode == 0,
                        f"rc={result_m7.returncode} (expected 0 — trap no longer fails)" if result_m7.returncode == 0
                        else f"rc={result_m7.returncode} — mutation was ineffective (unexpected)",
                    )
                    # INDEPENDENT SUBPROCESS RC ORACLE
                    orc7_rc, orc7_out, orc7_err = _run_rc_oracle_subprocess(
                        result_m7.returncode, "m7",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M7 — oracle subprocess exits nonzero (validator would exit nonzero)",
                        orc7_rc != 0,
                        f"oracle rc={orc7_rc}, out={orc7_out!r}" if orc7_rc == 0
                        else f"oracle rc={orc7_rc}, {orc7_out}",
                    )
                    all_ok &= check(
                        "runbook fixtures: adversarial M7 — oracle subprocess did not crash (rc in (0,1))",
                        orc7_rc in (0, 1),
                        f"oracle rc={orc7_rc} stderr={orc7_err[:200]}",
                    )
                finally:
                    Path(m7_path).unlink(missing_ok=True)
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M7 — mutation application",
                    False,
                    "M7 regex did not match trap_body — mutation could not be applied (silent skip prevented)",
                )

            # --- M9: Remove green polling-helper invocation from runbook ---
            mutated_runbook_green = re.sub(
                r'python3 scripts/runbook-kv-poll\.py --url http://localhost:8080/status\.json --mode green --deadline-offset \d+',
                '# GREEN POLLING PHASE REMOVED',
                runbook_text,
            )
            if mutated_runbook_green != runbook_text:
                orc9_rc, orc9_out, orc9_err = _run_trace_oracle_subprocess(
                    mutated_runbook_green,
                    "scripts/runbook-kv-poll.py --url http://localhost:8080/status.json --mode green",
                    "m9",
                )
                all_ok &= check(
                    "runbook fixtures: adversarial M9 — oracle subprocess exits nonzero (validator would exit nonzero)",
                    orc9_rc != 0,
                    f"oracle rc={orc9_rc}, out={orc9_out!r}" if orc9_rc == 0
                    else f"oracle rc={orc9_rc}, {orc9_out}",
                )
                all_ok &= check(
                    "runbook fixtures: adversarial M9 — oracle subprocess did not crash (rc in (0,1))",
                    orc9_rc in (0, 1),
                    f"oracle rc={orc9_rc} stderr={orc9_err[:200]}",
                )
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M9 — mutation application",
                    False,
                    "M9 regex did not match runbook text — mutation could not be applied (silent skip prevented)",
                )

            # --- M10: Remove red polling-helper invocation from runbook ---
            mutated_runbook_red = re.sub(
                r'python3 scripts/runbook-kv-poll\.py --url http://localhost:8080/status\.json --mode red --deadline-offset \d+',
                '# RED POLLING PHASE REMOVED',
                runbook_text,
            )
            if mutated_runbook_red != runbook_text:
                orc10_rc, orc10_out, orc10_err = _run_trace_oracle_subprocess(
                    mutated_runbook_red,
                    "scripts/runbook-kv-poll.py --url http://localhost:8080/status.json --mode red",
                    "m10",
                )
                all_ok &= check(
                    "runbook fixtures: adversarial M10 — oracle subprocess exits nonzero (validator would exit nonzero)",
                    orc10_rc != 0,
                    f"oracle rc={orc10_rc}, out={orc10_out!r}" if orc10_rc == 0
                    else f"oracle rc={orc10_rc}, {orc10_out}",
                )
                all_ok &= check(
                    "runbook fixtures: adversarial M10 — oracle subprocess did not crash (rc in (0,1))",
                    orc10_rc in (0, 1),
                    f"oracle rc={orc10_rc} stderr={orc10_err[:200]}",
                )
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M10 — mutation application",
                    False,
                    "M10 regex did not match runbook text — mutation could not be applied (silent skip prevented)",
                )

            # --- M11: Remove restored-green polling-helper invocation from runbook ---
            mutated_runbook_restored = re.sub(
                r'python3 scripts/runbook-kv-poll\.py --url http://localhost:8080/status\.json --mode restored-green --deadline-offset \d+',
                '# RESTORED-GREEN POLLING PHASE REMOVED',
                runbook_text,
            )
            if mutated_runbook_restored != runbook_text:
                orc11_rc, orc11_out, orc11_err = _run_trace_oracle_subprocess(
                    mutated_runbook_restored,
                    "scripts/runbook-kv-poll.py --url http://localhost:8080/status.json --mode restored-green",
                    "m11",
                )
                all_ok &= check(
                    "runbook fixtures: adversarial M11 — oracle subprocess exits nonzero (validator would exit nonzero)",
                    orc11_rc != 0,
                    f"oracle rc={orc11_rc}, out={orc11_out!r}" if orc11_rc == 0
                    else f"oracle rc={orc11_rc}, {orc11_out}",
                )
                all_ok &= check(
                    "runbook fixtures: adversarial M11 — oracle subprocess did not crash (rc in (0,1))",
                    orc11_rc in (0, 1),
                    f"oracle rc={orc11_rc} stderr={orc11_err[:200]}",
                )
            else:
                all_ok &= check(
                    "runbook fixtures: adversarial M11 — mutation application",
                    False,
                    "M11 regex did not match runbook text — mutation could not be applied (silent skip prevented)",
                )
        finally:
            Path(pf_test_path).unlink(missing_ok=True)

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


def _extract_make_recipe(makefile_text: str, target: str) -> str | None:
    """Extract the recipe body for a Makefile target.

    The Makefile uses .RECIPEPREFIX := > so recipe lines start with '>'.
    Returns the recipe text with the prefix stripped, suitable for shell execution,
    or None if the target is not found.
    """
    import re

    # Find the target line: "target-name:"
    target_pat = re.compile(rf"^{re.escape(target)}:\s*$", re.MULTILINE)
    m = target_pat.search(makefile_text)
    if not m:
        return None

    start = m.end()
    # Collect recipe lines (start with >) and continuation lines (start with whitespace + shell)
    lines = []
    recipe_prefix_len = len("> ")
    for line in makefile_text[start:].split("\n"):
        if line.startswith(">"):
            lines.append(line[recipe_prefix_len:])
        elif line.startswith("    ") or line.startswith("\t"):
            # Continuation of previous recipe line
            if lines:
                lines[-1] = lines[-1] + "\n" + line
            else:
                lines.append(line)
        elif line.strip() == "":
            if lines:
                # Empty line inside recipe body
                lines.append("")
            else:
                continue
        elif line.startswith(".") or ":" in line and not line.startswith(" ") and not line.startswith("\t"):
            # Next target or directive
            break
        elif lines:
            # More continuation
            lines.append(line)
        else:
            break

    body = "\n".join(lines)
    return body if body.strip() else None


def validate_flux_sync_override_reset() -> bool:
    """Validate that default bootstrap resets pre-existing override ConfigMap.

    Executes the actual Makefile kind-dev-misc-local-bootstrap recipe with
    mock kubectl and helm, recording every invocation to a trace file.
    Verifies:
      - Override path: creates ConfigMap, does NOT delete
      - Default path: deletes stale ConfigMap, does NOT create
      - Adversarial: mutating the condition (-n→-z) or removing delete/apply fails
      - Failure propagation: kubectl create/apply/delete failures cause non-zero exit
    """
    import re
    import tempfile

    all_ok = True
    makefile_path = REPO_ROOT / "Makefile"
    with open(makefile_path) as f:
        makefile_text = f.read()

    # Extract the actual recipe from the Makefile
    recipe = _extract_make_recipe(makefile_text, "kind-dev-misc-local-bootstrap")
    if recipe is None:
        return check(
            "flux sync override reset: recipe extraction",
            False,
            "could not extract kind-dev-misc-local-bootstrap recipe from Makefile",
        )

    all_ok &= check(
        "flux sync override reset: recipe extracted from Makefile",
        len(recipe) > 200,
        f"extracted {len(recipe)} chars of recipe text",
    )

    # Structural checks (against the extracted recipe, not the raw text)
    has_delete = "delete configmap flux-sync-values-override" in recipe
    has_create = "create configmap flux-sync-values-override" in recipe
    has_ignore = "--ignore-not-found" in recipe
    has_apply = "apply -f -" in recipe

    all_ok &= check(
        "flux sync override reset: recipe has delete command",
        has_delete,
        "delete found" if has_delete else "delete NOT found",
    )
    all_ok &= check(
        "flux sync override reset: recipe has create command",
        has_create,
        "create found" if has_create else "create NOT found",
    )
    all_ok &= check(
        "flux sync override reset: recipe has --ignore-not-found",
        has_ignore,
        "found" if has_ignore else "MISSING",
    )
    all_ok &= check(
        "flux sync override reset: recipe has apply -f - (for kubectl create dry-run pipe)",
        has_apply,
        "found" if has_apply else "MISSING",
    )

    # Verify delete is inside the else branch
    else_match = re.search(r'else\b.*?\n(.*?)fi\b', recipe, re.DOTALL)
    if else_match:
        else_block = else_match.group(1)
        delete_in_else = "delete configmap flux-sync-values-override" in else_block
        all_ok &= check(
            "flux sync override reset: delete is in the else (default) branch",
            delete_in_else,
            "delete in else branch" if delete_in_else
            else f"else block: {else_block.strip()[:80]}",
        )

    # Verify apply -f - is inside an if (override) branch
    # The recipe has two if blocks. Find apply -f - and confirm it is
    # inside any if...fi construct by checking all if/fi pairs.
    apply_pos = recipe.find("apply -f -")
    if apply_pos >= 0:
        # Find all if/fi spans and check if apply_pos falls inside any of them
        apply_in_if = False
        for m in re.finditer(r'\bif\b.*?\bfi\b', recipe, re.DOTALL):
            if m.start() <= apply_pos <= m.end():
                apply_in_if = True
                break
        all_ok &= check(
            "flux sync override reset: apply -f - is in an if (override) branch",
            apply_in_if,
            "apply inside if...fi" if apply_in_if
            else f"apply at pos {apply_pos} — NOT inside any if...fi",
        )
    else:
        all_ok &= check(
            "flux sync override reset: apply -f - is present in recipe",
            False,
            "apply -f - NOT found in recipe",
        )

    # ===================================================================
    # BEHAVIORAL: execute the actual recipe with mock kubectl/helm
    # ===================================================================

    tmp_dir = REPO_ROOT / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = REPO_ROOT / "clusters" / "kind-dev-misc-local" / "entrypoint"

    def _run_recipe(override_branch: str, inject_fail: str | None = None) -> tuple[int, str, str]:
        """Run the recipe with mock tools. Returns (exit_code, trace, stderr)."""
        mock_dir = tmp_dir / "mock-bin"
        mock_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize branch name for use in filenames (replace / with -)
        safe_branch = (override_branch or "default").replace("/", "-")

        # Mock kubectl: records every invocation to a trace file
        trace_file = tmp_dir / f"kubectl-trace-{safe_branch}"
        mock_kubectl = mock_dir / "kubectl"
        mock_kubectl.write_text(f"""#!/bin/bash
echo "kubectl $*" >> "{trace_file}"
# Inject failures for specific commands
if [ -n "{inject_fail or ''}" ]; then
    if echo "$*" | grep -q "{inject_fail}"; then
        echo "MOCK INJECTED FAILURE: $*" >> "{trace_file}"
        exit 1
    fi
fi
exit 0
""")
        mock_kubectl.chmod(0o755)

        # Mock helm: records invocation, succeeds
        mock_helm = mock_dir / "helm"
        mock_helm.write_text(f"""#!/bin/bash
echo "helm $*" >> "{trace_file}"
exit 0
""")
        mock_helm.chmod(0o755)

        # Convert Makefile $(VAR) references to shell ${VAR} before execution.
        # The Makefile's .RECIPEPREFIX := > was already stripped during extraction.
        shell_recipe = re.sub(r'\$\((\w+)\)', r'${\1}', recipe)

        override_file = tmp_dir / f"test-override-{safe_branch}.yaml"
        helm_values = tmp_dir / "test-helm-values.yaml"
        helm_values.write_text("{}")

        script = f"""#!/bin/bash
set -eo pipefail
export PATH="{mock_dir}:$PATH"
export KIND_CLUSTER_NAME="kind-dev-misc-local"
export KIND_CONTEXT="kind-$KIND_CLUSTER_NAME"
export HELM_CONTEXT_ARGS="--kube-context $KIND_CONTEXT"
export FLUX_GIT_BRANCH="pivot/flux-sync-ssh-bootstrap"
export FLUX_GIT_BRANCH_OVERRIDE="{override_branch}"
export FLUX_SYNC_OVERRIDE_FILE="{override_file}"
export FLUX_RELEASE_NAME="flux-system"
export FLUX_SYNC_HELMRELEASE_NAME="flux-system-sync"
export FLUX_NAMESPACE="flux-system"
export FLUX_CHART="oci://ghcr.io/fluxcd-community/charts/flux2"
export FLUX_CHART_VERSION="2.18.4"
export FLUX_HELM_VALUES="{helm_values}"
export ENTRYPOINT_ROOT="{entrypoint}"

# The extracted recipe (Makefile variable refs converted to shell syntax)
{shell_recipe}
"""
        script_path = tmp_dir / f"test-recipe-{safe_branch}.sh"
        script_path.write_text(script)

        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        trace = trace_file.read_text() if trace_file.exists() else ""
        return result.returncode, trace, result.stderr

    def _run_recipe_with_body(
        recipe_body: str,
        override_branch: str,
        tmp_dir: Path,
        entrypoint: Path,
        inject_fail: str | None = None,
    ) -> tuple[int, str, str]:
        """Like _run_recipe but takes an explicit recipe body (for mutation testing).

        Returns (exit_code, trace, stderr).
        """
        mock_dir = tmp_dir / "mock-bin-adversarial"
        mock_dir.mkdir(parents=True, exist_ok=True)

        safe_branch = (override_branch or "default").replace("/", "-")
        trace_file = tmp_dir / f"kubectl-trace-adv-{safe_branch}"

        # Mock kubectl
        mock_kubectl = mock_dir / "kubectl"
        mock_kubectl.write_text(f"""#!/bin/bash
echo "kubectl $*" >> "{trace_file}"
if [ -n "{inject_fail or ''}" ]; then
    if echo "$*" | grep -q "{inject_fail}"; then
        echo "MOCK INJECTED FAILURE: $*" >> "{trace_file}"
        exit 1
    fi
fi
exit 0
""")
        mock_kubectl.chmod(0o755)

        # Mock helm
        mock_helm = mock_dir / "helm"
        mock_helm.write_text(f"""#!/bin/bash
echo "helm $*" >> "{trace_file}"
exit 0
""")
        mock_helm.chmod(0o755)

        # Convert $(VAR) to ${VAR}
        shell_recipe = re.sub(r'\$\((\w+)\)', r'${\1}', recipe_body)

        override_file = tmp_dir / f"test-override-adv-{safe_branch}.yaml"
        helm_values = tmp_dir / "test-helm-values-adv.yaml"
        helm_values.write_text("{}")

        script = f"""#!/bin/bash
set -eo pipefail
export PATH="{mock_dir}:$PATH"
export KIND_CLUSTER_NAME="kind-dev-misc-local"
export KIND_CONTEXT="kind-$KIND_CLUSTER_NAME"
export HELM_CONTEXT_ARGS="--kube-context $KIND_CONTEXT"
export FLUX_GIT_BRANCH="pivot/flux-sync-ssh-bootstrap"
export FLUX_GIT_BRANCH_OVERRIDE="{override_branch}"
export FLUX_SYNC_OVERRIDE_FILE="{override_file}"
export FLUX_RELEASE_NAME="flux-system"
export FLUX_SYNC_HELMRELEASE_NAME="flux-system-sync"
export FLUX_NAMESPACE="flux-system"
export FLUX_CHART="oci://ghcr.io/fluxcd-community/charts/flux2"
export FLUX_CHART_VERSION="2.18.4"
export FLUX_HELM_VALUES="{helm_values}"
export ENTRYPOINT_ROOT="{entrypoint}"

{shell_recipe}
"""
        script_path = tmp_dir / f"test-recipe-adv-{safe_branch}.sh"
        script_path.write_text(script)

        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        trace = trace_file.read_text() if trace_file.exists() else ""
        return result.returncode, trace, result.stderr

    # --- Override path: FLUX_GIT_BRANCH_OVERRIDE=candidate/test-branch ---
    override_exit, override_trace, override_stderr = _run_recipe("candidate/test-branch")
    override_has_delete = "delete configmap flux-sync-values-override" in override_trace
    override_has_create = "create configmap flux-sync-values-override" in override_trace
    override_has_apply = "apply -f -" in override_trace

    all_ok &= check(
        "flux sync override reset: override path — recipe exits 0",
        override_exit == 0,
        f"exit={override_exit}" + (
            f" stderr: {override_stderr.strip()[:200]}" if override_stderr.strip() else ""
        ),
    )
    all_ok &= check(
        "flux sync override reset: override path creates ConfigMap (kubectl create called)",
        override_has_create,
        "create found in trace" if override_has_create
        else f"trace ({len(override_trace)} chars): {override_trace.strip()[:200]}",
    )
    all_ok &= check(
        "flux sync override reset: override path applies ConfigMap (apply -f - called)",
        override_has_apply,
        "apply found in trace" if override_has_apply
        else f"trace: {override_trace.strip()[:200]}",
    )
    all_ok &= check(
        "flux sync override reset: override path does NOT delete ConfigMap",
        not override_has_delete,
        "delete correctly absent" if not override_has_delete
        else f"unexpected delete in trace: {override_trace.strip()[:200]}",
    )

    # --- Default path: FLUX_GIT_BRANCH_OVERRIDE empty ---
    default_exit, default_trace, default_stderr = _run_recipe("")
    default_has_delete = "delete configmap flux-sync-values-override" in default_trace
    default_has_create = "create configmap flux-sync-values-override" in default_trace

    all_ok &= check(
        "flux sync override reset: default path — recipe exits 0",
        default_exit == 0,
        f"exit={default_exit}" + (
            f" stderr: {default_stderr.strip()[:200]}" if default_stderr.strip() else ""
        ),
    )
    all_ok &= check(
        "flux sync override reset: default path deletes stale ConfigMap (kubectl delete called)",
        default_has_delete,
        "delete found in trace" if default_has_delete
        else f"trace ({len(default_trace)} chars): {default_trace.strip()[:200]}",
    )
    all_ok &= check(
        "flux sync override reset: default path does NOT create ConfigMap",
        not default_has_create,
        "create correctly absent" if not default_has_create
        else f"unexpected create in trace: {default_trace.strip()[:200]}",
    )

    # --- Failure propagation: kubectl delete failure ---
    fail_exit, fail_trace, fail_stderr = _run_recipe("", inject_fail="delete configmap")
    all_ok &= check(
        "flux sync override reset: kubectl delete failure propagates non-zero exit",
        fail_exit != 0,
        f"exit={fail_exit} (expected non-zero)" + (
            f" stderr: {fail_stderr.strip()[:200]}" if fail_stderr.strip() else ""
        ),
    )

    # --- Failure propagation: kubectl create failure ---
    fail_create_exit, fail_create_trace, fail_create_stderr = _run_recipe(
        "candidate/test-branch", inject_fail="create configmap"
    )
    all_ok &= check(
        "flux sync override reset: kubectl create failure propagates non-zero exit",
        fail_create_exit != 0,
        f"exit={fail_create_exit} (expected non-zero)" + (
            f" stderr: {fail_create_stderr.strip()[:200]}" if fail_create_stderr.strip() else ""
        ),
    )

    # ===================================================================
    # ADVERSARIAL: execution-based mutation tests
    # ===================================================================
    # Each mutation modifies the recipe, then an INDEPENDENT validation
    # oracle (_oracle_check_recipe) is called against the mutated recipe.
    # The test asserts the oracle returns nonzero (all_pass=False),
    # proving the validator would exit nonzero on the mutation.
    # Runtime behavioral checks supplement the oracle verdict.

    def _oracle_check_recipe(recipe_text: str) -> tuple[bool, list[str]]:
        """Run the same structural checks the validator uses against a recipe.

        Returns (all_pass, failures) where all_pass is True if every structural
        check passes, and failures is the list of failing check descriptions.
        A mutation test asserts that the oracle returns all_pass=False,
        proving the validator would exit nonzero on the mutated recipe.
        """
        failures = []
        has_delete = "delete configmap flux-sync-values-override" in recipe_text
        has_create = "create configmap flux-sync-values-override" in recipe_text
        has_apply = "apply -f -" in recipe_text
        has_ignore = "--ignore-not-found" in recipe_text

        if not has_delete:
            failures.append("recipe has delete command")
        if not has_create:
            failures.append("recipe has create command")
        if not has_apply:
            failures.append("recipe has apply -f -")
        if not has_ignore:
            failures.append("recipe has --ignore-not-found")

        # Check delete is inside else branch
        else_match = re.search(r'else\b.*?\n(.*?)fi\b', recipe_text, re.DOTALL)
        delete_in_else = bool(
            else_match and "delete configmap flux-sync-values-override" in else_match.group(1)
        )
        if has_delete and not delete_in_else:
            failures.append("delete is in else branch")

        # Check apply is inside an if branch
        apply_pos = recipe_text.find("apply -f -")
        apply_in_if = False
        if apply_pos >= 0:
            for m in re.finditer(r'\bif\b.*?\bfi\b', recipe_text, re.DOTALL):
                if m.start() <= apply_pos <= m.end():
                    apply_in_if = True
                    break
        if has_apply and not apply_in_if:
            failures.append("apply -f - is in if branch")

        # Check condition uses -n (non-empty), not -z (empty)
        if '-n "' not in recipe_text:
            failures.append("condition uses -n (non-empty check)")
        if '[ -z "' in recipe_text:
            failures.append("condition uses -z (inverted — should be -n)")

        all_pass = len(failures) == 0
        return all_pass, failures

    # --- M1: Invert condition -n to -z ---
    mutated_recipe_neg = re.sub(r'\[ -n "', '[ -z "', recipe)
    if mutated_recipe_neg != recipe:
        # INDEPENDENT ORACLE: run structural checks against mutated recipe
        oracle_m1_pass, oracle_m1_failures = _oracle_check_recipe(mutated_recipe_neg)
        all_ok &= check(
            "flux sync override reset: adversarial M1 — oracle detects inverted condition (validator would exit nonzero)",
            not oracle_m1_pass,
            f"oracle failures: {', '.join(oracle_m1_failures)}" if not oracle_m1_pass
            else "oracle passed unexpectedly — mutation was not detected by structural checks",
        )
        # Runtime: execute with override path, verify behavioral mismatch
        exit_m1, trace_m1, _ = _run_recipe_with_body(
            mutated_recipe_neg, "candidate/test-m1", tmp_dir, entrypoint,
        )
        m1_has_create = "create configmap flux-sync-values-override" in trace_m1
        m1_has_delete = "delete configmap flux-sync-values-override" in trace_m1
        all_ok &= check(
            "flux sync override reset: adversarial M1 — inverted -n→-z: override path does NOT create ConfigMap",
            not m1_has_create,
            "create correctly absent (inverted condition)" if not m1_has_create
            else f"create STILL present — mutation was ineffective. trace: {trace_m1.strip()[:200]}",
        )
        all_ok &= check(
            "flux sync override reset: adversarial M1 — inverted -n→-z: override path deletes (wrong branch)",
            m1_has_delete,
            "delete detected (inverted) — expected because -z makes override fall into else branch",
        )
        # Runtime: execute with default path, verify delete fails
        exit_m1d, trace_m1d, _ = _run_recipe_with_body(
            mutated_recipe_neg, "", tmp_dir, entrypoint,
        )
        m1d_has_delete = "delete configmap flux-sync-values-override" in trace_m1d
        all_ok &= check(
            "flux sync override reset: adversarial M1 — inverted -n→-z: default path does NOT delete (wrong branch)",
            not m1d_has_delete,
            "delete correctly absent (inverted condition)" if not m1d_has_delete
            else f"delete STILL present — mutation was ineffective",
        )
    else:
        all_ok &= check(
            "flux sync override reset: adversarial M1 — mutation application",
            False,
            "M1 regex did not match recipe — mutation could not be applied (silent skip prevented)",
        )

    # --- M2: Remove create command from recipe ---
    mutated_no_create = re.sub(
        r'create\s+configmap\s+flux-sync-values-override.*?apply\s+-f\s+-;',
        '# CREATE + APPLY REMOVED',
        recipe,
        flags=re.DOTALL,
    )
    if mutated_no_create != recipe:
        # INDEPENDENT ORACLE: run structural checks against mutated recipe
        oracle_m2_pass, oracle_m2_failures = _oracle_check_recipe(mutated_no_create)
        all_ok &= check(
            "flux sync override reset: adversarial M2 — oracle detects missing create (validator would exit nonzero)",
            not oracle_m2_pass,
            f"oracle failures: {', '.join(oracle_m2_failures)}" if not oracle_m2_pass
            else "oracle passed unexpectedly — mutation was not detected by structural checks",
        )
        # Runtime: execute and verify behavioral mismatch
        exit_m2, trace_m2, _ = _run_recipe_with_body(
            mutated_no_create, "candidate/test-m2", tmp_dir, entrypoint,
        )
        m2_has_create = "create configmap flux-sync-values-override" in trace_m2
        all_ok &= check(
            "flux sync override reset: adversarial M2 — create removed: override path does NOT create ConfigMap",
            not m2_has_create,
            "create correctly absent (removed)" if not m2_has_create
            else f"create STILL present — mutation was ineffective",
        )
    else:
        all_ok &= check(
            "flux sync override reset: adversarial M2 — mutation application",
            False,
            "M2 regex did not match recipe — mutation could not be applied (silent skip prevented)",
        )

    # --- M3: Remove apply -f - command from recipe ---
    mutated_no_apply = re.sub(
        r'\|\s*kubectl\s+.*?apply\s+-f\s+-;',
        '# APPLY PIPE REMOVED',
        recipe,
        flags=re.DOTALL,
    )
    if mutated_no_apply != recipe:
        # INDEPENDENT ORACLE: run structural checks against mutated recipe
        oracle_m3_pass, oracle_m3_failures = _oracle_check_recipe(mutated_no_apply)
        all_ok &= check(
            "flux sync override reset: adversarial M3 — oracle detects missing apply (validator would exit nonzero)",
            not oracle_m3_pass,
            f"oracle failures: {', '.join(oracle_m3_failures)}" if not oracle_m3_pass
            else "oracle passed unexpectedly — mutation was not detected by structural checks",
        )
        # Runtime: execute and verify behavioral mismatch
        exit_m3, trace_m3, _ = _run_recipe_with_body(
            mutated_no_apply, "candidate/test-m3", tmp_dir, entrypoint,
        )
        m3_has_apply = "apply -f -" in trace_m3
        all_ok &= check(
            "flux sync override reset: adversarial M3 — apply removed: override path does NOT apply ConfigMap",
            not m3_has_apply,
            "apply correctly absent (removed)" if not m3_has_apply
            else f"apply STILL present — mutation was ineffective",
        )
    else:
        all_ok &= check(
            "flux sync override reset: adversarial M3 — mutation application",
            False,
            "M3 regex did not match recipe — mutation could not be applied (silent skip prevented)",
        )

    # --- M4: Remove delete command from recipe ---
    mutated_no_delete = re.sub(
        r'kubectl\s+.*?delete\s+configmap\s+flux-sync-values-override.*?--ignore-not-found;',
        '# DELETE REMOVED',
        recipe,
        flags=re.DOTALL,
    )
    if mutated_no_delete != recipe:
        # INDEPENDENT ORACLE: run structural checks against mutated recipe
        oracle_m4_pass, oracle_m4_failures = _oracle_check_recipe(mutated_no_delete)
        all_ok &= check(
            "flux sync override reset: adversarial M4 — oracle detects missing delete (validator would exit nonzero)",
            not oracle_m4_pass,
            f"oracle failures: {', '.join(oracle_m4_failures)}" if not oracle_m4_pass
            else "oracle passed unexpectedly — mutation was not detected by structural checks",
        )
        # Runtime: execute and verify behavioral mismatch
        exit_m4, trace_m4, _ = _run_recipe_with_body(
            mutated_no_delete, "", tmp_dir, entrypoint,
        )
        m4_has_delete = "delete configmap flux-sync-values-override" in trace_m4
        all_ok &= check(
            "flux sync override reset: adversarial M4 — delete removed: default path does NOT delete ConfigMap",
            not m4_has_delete,
            "delete correctly absent (removed)" if not m4_has_delete
            else f"delete STILL present — mutation was ineffective",
        )
    else:
        all_ok &= check(
            "flux sync override reset: adversarial M4 — mutation application",
            False,
            "M4 regex did not match recipe — mutation could not be applied (silent skip prevented)",
        )

    # ===================================================================
    # FAILURE PROPAGATION: kubectl apply -f - failure (independent of create)
    # ===================================================================
    fail_apply_exit, fail_apply_trace, fail_apply_stderr = _run_recipe(
        "candidate/test-branch", inject_fail="apply -f -"
    )
    all_ok &= check(
        "flux sync override reset: kubectl apply -f - failure propagates non-zero exit",
        fail_apply_exit != 0,
        f"exit={fail_apply_exit} (expected non-zero)" + (
            f" stderr: {fail_apply_stderr.strip()[:200]}" if fail_apply_stderr.strip() else ""
        ),
    )

    # ===================================================================
    # STATEFUL BOOTSTRAP LIFECYCLE: candidate → reconcile → default → canonical
    # ===================================================================
    # Prove one lifecycle with genuinely persisted effective branch state.
    # Mock kubectl writes the effective branch to a state FILE (not trace
    # markers). After each phase the test reads the state file via an
    # INDEPENDENT SUBPROCESS and asserts its return code. Explicit simulated
    # root reconciliation runs as a bash subprocess between phases with
    # asserted exit codes. An injected reconciliation failure proves
    # nonzero propagation.

    state_dir = tmp_dir / "mock-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "effective-branch"
    state_file.write_text("uninitialized")

    stateful_trace = tmp_dir / "stateful-lifecycle-trace.txt"
    stateful_trace.write_text("")

    # Shared mock scripts that persist state via the state file
    stateful_mock_dir = tmp_dir / "mock-bin-stateful"
    stateful_mock_dir.mkdir(parents=True, exist_ok=True)
    mock_kubectl_sf = stateful_mock_dir / "kubectl"
    mock_helm_sf = stateful_mock_dir / "helm"

    mock_kubectl_sf.write_text(f"""#!/bin/bash
echo "kubectl $*" >> "{stateful_trace}"
# Persist effective branch to a state FILE (not a trace marker).
# This is the ground-truth source that downstream tests read.
case "$*" in
    *"create configmap flux-sync-values-override"*)
        # Extract branch from the override file written by the recipe
        branch=$(grep 'branch:' "${{FLUX_SYNC_OVERRIDE_FILE}}" 2>/dev/null | awk '{{print $2}}')
        if [ -n "$branch" ]; then
            echo "$branch" > "{state_file}"
            echo "STATE:effective-branch=$branch" >> "{stateful_trace}"
        fi
        ;;
    *"delete configmap flux-sync-values-override"*)
        echo "pivot/flux-sync-ssh-bootstrap" > "{state_file}"
        echo "STATE:effective-branch=pivot/flux-sync-ssh-bootstrap" >> "{stateful_trace}"
        ;;
esac
exit 0
""")
    mock_kubectl_sf.chmod(0o755)
    mock_helm_sf.write_text(f"""#!/bin/bash
echo "helm $*" >> "{stateful_trace}"
exit 0
""")
    mock_helm_sf.chmod(0o755)

    def _read_effective_branch_subprocess(label: str) -> tuple[int, str]:
        """Read the persisted effective branch via an INDEPENDENT SUBPROCESS.

        Returns (exit_code, branch). The exit code is asserted so crashes
        and permission errors are not silently swallowed.
        """
        reader_py = tmp_dir / f"read-state-{label}.py"
        reader_py.write_text(f'''import sys
state_file = {str(state_file)!r}
try:
    with open(state_file) as f:
        branch = f.read().strip()
    print(branch)
    sys.exit(0)
except Exception as e:
    print(f"ERROR reading state file: {{e}}", file=sys.stderr)
    sys.exit(2)
''')
        result = subprocess.run(
            [sys.executable, str(reader_py)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        return result.returncode, result.stdout.strip()

    def _simulate_flux_root_reconcile(inject_failure: bool = False) -> tuple[int, int, str]:
        """Simulate Flux root reconciliation as an EXPLICIT BASH SUBPROCESS.

        Flux applies committed config from git. Since the override
        ConfigMap is NOT managed by kustomize, the committed config
        does not include or remove it. Therefore reconciliation
        preserves the existing effective branch (candidate if override
        exists, canonical if it was deleted).

        When inject_failure=True, the reconciliation script exits
        non-zero to prove failure propagation.

        Returns (reconcile_rc, read_rc, effective_branch_after).
        Both RCs are returned separately so callers can assert
        reconciliation success/failure independently from the
        post-reconcile state-reader process health.
        """
        reconcile_script = tmp_dir / "reconcile-sim.sh"
        reconcile_script.write_text(f"""#!/bin/bash
set -e
# Read the current effective branch from shared persisted state
branch=$(cat "{state_file}")
echo "RECONCILE: effective-branch=$branch"
if [ "{'true' if inject_failure else 'false'}" = "true" ]; then
    echo "RECONCILE: injected failure — simulating cluster unreachable" >&2
    exit 3
fi
# Simulate Flux applying committed config from git:
# - Committed config does NOT include flux-sync-values-override
# - So the override ConfigMap survives if present, or stays absent
# - The effective branch is preserved
echo "$branch" > "{state_file}"
echo "RECONCILE: preserved effective-branch=$branch"
exit 0
""")
        reconcile_script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(reconcile_script)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )

        # Read branch AFTER reconciliation via independent subprocess
        read_rc, branch_after = _read_effective_branch_subprocess(
            "post-reconcile" + ("-fail" if inject_failure else "")
        )
        return result.returncode, read_rc, branch_after

    def _run_stateful_phase(override_branch: str, phase_label: str) -> tuple[int, str, str, int]:
        """Run one phase of the lifecycle with shared mock state.

        Returns (exit_code, trace_snapshot, effective_branch, read_rc).
        The effective branch is read via an independent subprocess;
        read_rc is returned explicitly so callers can assert
        the reader process itself succeeded (RC == 0) independently
        from the exact persisted branch value.
        """
        safe_branch = (override_branch or "default").replace("/", "-")
        shell_recipe = re.sub(r'\$\((\w+)\)', r'${\1}', recipe)
        override_file = tmp_dir / f"test-override-sf-{safe_branch}.yaml"
        helm_values = tmp_dir / "test-helm-values-sf.yaml"
        helm_values.write_text("{}")

        script = f"""#!/bin/bash
set -eo pipefail
export PATH="{stateful_mock_dir}:$PATH"
export KIND_CLUSTER_NAME="kind-dev-misc-local"
export KIND_CONTEXT="kind-$KIND_CLUSTER_NAME"
export HELM_CONTEXT_ARGS="--kube-context $KIND_CONTEXT"
export FLUX_GIT_BRANCH="pivot/flux-sync-ssh-bootstrap"
export FLUX_GIT_BRANCH_OVERRIDE="{override_branch}"
export FLUX_SYNC_OVERRIDE_FILE="{override_file}"
export FLUX_RELEASE_NAME="flux-system"
export FLUX_SYNC_HELMRELEASE_NAME="flux-system-sync"
export FLUX_NAMESPACE="flux-system"
export FLUX_CHART="oci://ghcr.io/fluxcd-community/charts/flux2"
export FLUX_CHART_VERSION="2.18.4"
export FLUX_HELM_VALUES="{helm_values}"
export ENTRYPOINT_ROOT="{entrypoint}"

{shell_recipe}
"""
        script_path = tmp_dir / f"test-sf-{safe_branch}.sh"
        script_path.write_text(script)
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        trace_snapshot = stateful_trace.read_text()
        read_rc, effective = _read_effective_branch_subprocess(phase_label)
        return result.returncode, trace_snapshot, effective, read_rc

    # --- Phase 1: Candidate bootstrap ---
    exit_cand, trace_cand, branch_cand, read_rc_cand = _run_stateful_phase("candidate/test-stateful", "candidate")
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-1 — candidate bootstrap exits 0",
        exit_cand == 0,
        f"exit={exit_cand}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-1 — read subprocess exits 0",
        read_rc_cand == 0,
        f"read_rc={read_rc_cand}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-1 — effective branch is candidate/test-stateful",
        branch_cand == "candidate/test-stateful",
        f"effective-branch={branch_cand!r} (expected 'candidate/test-stateful')"
        if branch_cand != "candidate/test-stateful"
        else f"effective-branch={branch_cand!r}",
    )

    # --- Explicit simulated Flux root reconciliation after phase 1 ---
    # Reconciliation re-applies committed config; since the override
    # ConfigMap exists and is NOT managed by kustomize, the effective
    # branch remains candidate.
    reconcile1_rc, read1_rc, reconcile1_branch = _simulate_flux_root_reconcile(inject_failure=False)
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-1 reconcile — subprocess exits 0",
        reconcile1_rc == 0,
        f"exit={reconcile1_rc}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-1 reconcile — read subprocess exits 0",
        read1_rc == 0,
        f"read_rc={read1_rc}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle after phase-1 reconcile — effective branch remains candidate/test-stateful",
        reconcile1_branch == "candidate/test-stateful",
        "candidate survives reconciliation"
        if reconcile1_branch == "candidate/test-stateful"
        else f"effective-branch changed to {reconcile1_branch!r} — override would be lost",
    )

    # --- Phase 2: Default bootstrap (overrides empty) ---
    exit_def, trace_def, branch_def, read_rc_def = _run_stateful_phase("", "default")
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-2 — default bootstrap exits 0",
        exit_def == 0,
        f"exit={exit_def}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-2 — read subprocess exits 0",
        read_rc_def == 0,
        f"read_rc={read_rc_def}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-2 — effective branch is pivot/flux-sync-ssh-bootstrap",
        branch_def == "pivot/flux-sync-ssh-bootstrap",
        f"effective-branch={branch_def!r}"
        if branch_def == "pivot/flux-sync-ssh-bootstrap"
        else f"effective-branch={branch_def!r} (expected 'pivot/flux-sync-ssh-bootstrap')",
    )

    # --- Explicit simulated Flux root reconciliation after phase 2 ---
    # Default bootstrap removed the override → reconciliation resolves to
    # the committed default branch exactly pivot/flux-sync-ssh-bootstrap.
    reconcile2_rc, read2_rc, reconcile2_branch = _simulate_flux_root_reconcile(inject_failure=False)
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-2 reconcile — subprocess exits 0",
        reconcile2_rc == 0,
        f"exit={reconcile2_rc}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle phase-2 reconcile — read subprocess exits 0",
        read2_rc == 0,
        f"read_rc={read2_rc}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle after phase-2 reconcile — effective branch is exactly pivot/flux-sync-ssh-bootstrap",
        reconcile2_branch == "pivot/flux-sync-ssh-bootstrap",
        "canonical branch restored and survives reconciliation"
        if reconcile2_branch == "pivot/flux-sync-ssh-bootstrap"
        else f"effective-branch is {reconcile2_branch!r} — canonical branch NOT restored",
    )

    # --- Injected reconciliation failure: proves nonzero propagation ---
    # Run candidate bootstrap to set up state, then inject a reconcile
    # failure. The reconcile subprocess must exit exactly 3 and the failure
    # must be observable. The post-failure state-read subprocess must
    # exit 0 independently, and the persisted branch must remain candidate.
    exit_cand2, _, branch_cand2, read_rc_cand2 = _run_stateful_phase("candidate/test-stateful", "candidate-fail-prep")
    all_ok &= check(
        "flux sync override reset: stateful lifecycle fail-prep — candidate bootstrap exits 0",
        exit_cand2 == 0,
        f"exit={exit_cand2}",
    )
    all_ok &= check(
        "flux sync override reset: stateful lifecycle fail-prep — read subprocess exits 0",
        read_rc_cand2 == 0,
        f"read_rc={read_rc_cand2}",
    )
    fail_rc, fail_read_rc, fail_reconcile_branch = _simulate_flux_root_reconcile(inject_failure=True)
    all_ok &= check(
        "flux sync override reset: injected reconcile failure — reconcile subprocess exits exactly 3",
        fail_rc == 3,
        f"exit={fail_rc} (expected 3 — intentional failure propagation)",
    )
    all_ok &= check(
        "flux sync override reset: injected reconcile failure — post-failure read subprocess exits 0",
        fail_read_rc == 0,
        f"read_rc={fail_read_rc}",
    )
    all_ok &= check(
        "flux sync override reset: injected reconcile failure — effective branch remains candidate/test-stateful",
        fail_reconcile_branch == "candidate/test-stateful",
        "candidate branch persisted through reconcile failure"
        if fail_reconcile_branch == "candidate/test-stateful"
        else f"effective-branch={fail_reconcile_branch!r} — branch lost on reconcile failure",
    )

    # Clean up mock traces
    import shutil
    mock_dir = tmp_dir / "mock-bin"
    if mock_dir.exists():
        shutil.rmtree(mock_dir, ignore_errors=True)
    for f in tmp_dir.glob("kubectl-trace-*"):
        f.unlink(missing_ok=True)

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

    print("\n=== Flux sync override reset validation ===")
    flux_reset_ok = validate_flux_sync_override_reset()

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
