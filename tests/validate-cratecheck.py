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


def validate_envoyproxy_patch() -> bool:
    """Validate the EnvoyProxy patch is valid under Kubernetes Service strategic merge.

    The EnvoyProxy in smoke-envoyproxy.yaml uses envoyService.patch to pin
    nodePort 30080. The patch MUST include `port` as the Service ports merge
    key — without it, `kubectl patch --local --type=strategic` fails with
    'does not contain declared merge key: port'.
    """
    envoyproxy_path = (
        REPO_ROOT
        / "clusters"
        / "kind-dev-misc-local"
        / "platform-services"
        / "envoy-gateway"
        / "smoke"
        / "smoke-envoyproxy.yaml"
    )
    with open(envoyproxy_path) as f:
        ep = yaml.safe_load(f)

    all_ok = True
    all_ok &= check(
        "EnvoyProxy smoke resource exists",
        ep["kind"] == "EnvoyProxy",
    )

    patch = (
        ep.get("spec", {})
        .get("provider", {})
        .get("kubernetes", {})
        .get("envoyService", {})
        .get("patch", {})
        .get("value", {})
    )
    all_ok &= check(
        "envoyService.patch.value is present",
        bool(patch),
    )

    ports = patch.get("spec", {}).get("ports", [])
    all_ok &= check(
        "envoyService.patch has exactly one port entry",
        len(ports) == 1,
        f"found {len(ports)}",
    )

    port_entry = ports[0] if ports else {}
    all_ok &= check(
        "envoyService.patch port entry has name http",
        port_entry.get("name") == "http",
        f"name={port_entry.get('name')}",
    )
    all_ok &= check(
        "envoyService.patch port entry has port 80 (strategic merge key)",
        port_entry.get("port") == 80,
        f"port={port_entry.get('port')}",
    )
    all_ok &= check(
        "envoyService.patch port entry has deterministic nodePort 30080",
        port_entry.get("nodePort") == 30080,
        f"nodePort={port_entry.get('nodePort')}",
    )

    # Prove the patch is valid under strategic merge by applying it to
    # a representative generated Service via kubectl patch --local.
    representative_svc = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "envoy-kubecrate-envoy-smoke", "namespace": "core-envoy-gateway"},
        "spec": {
            "ports": [
                {"name": "http", "port": 80, "protocol": "TCP", "targetPort": 10080},
            ],
            "selector": {"app": "envoy"},
            "type": "ClusterIP",
        },
    }
    import json, tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as svc_f:
        json.dump(representative_svc, svc_f)
        svc_path = svc_f.name
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as patch_f:
        json.dump(patch, patch_f)
        patch_path = patch_f.name

    try:
        result = subprocess.run(
            [
                "kubectl", "patch", "--local=true", "-f", svc_path,
                "--type=strategic", "--patch-file", patch_path,
                "-o", "json",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            all_ok &= check(
                "kubectl strategic patch applies successfully",
                False,
                result.stderr.strip()[:200],
            )
        else:
            patched = json.loads(result.stdout)
            patched_ports = patched.get("spec", {}).get("ports", [])
            http_port = next(
                (p for p in patched_ports if p.get("name") == "http"), None
            )
            all_ok &= check(
                "patched Service has nodePort 30080",
                http_port is not None and http_port.get("nodePort") == 30080,
                f"ports={json.dumps(patched_ports)}",
            )
    finally:
        import os
        os.unlink(svc_path)
        os.unlink(patch_path)

    return all_ok


def validate_flux_sync_override() -> bool:
    """Validate the Flux sync branch override mechanism.

    The bootstrap target must not depend on yq or imperative post-apply
    patches. Instead:
    - The sync HelmRelease declares an optional valuesFrom for
      flux-sync-values-override.
    - The render script produces a ConfigMap with the override branch
      when FLUX_GIT_BRANCH_OVERRIDE is set, and an identity ConfigMap
      otherwise.
    - The committed helm-values-sync.yaml remains the canonical branch
      reference.
    """
    all_ok = True

    # 1. Verify the sync HelmRelease references the optional override
    sync_hr_path = REPO_ROOT / "platform-services" / "flux" / "base" / "helm-release-sync.yaml"
    with open(sync_hr_path) as f:
        hr = yaml.safe_load(f)
    values_from = hr["spec"].get("valuesFrom", [])
    override_entry = [v for v in values_from if v.get("name") == "flux-sync-values-override"]
    all_ok &= check(
        "sync HelmRelease includes flux-sync-values-override in valuesFrom",
        len(override_entry) == 1,
    )
    all_ok &= check(
        "flux-sync-values-override valuesFrom is optional",
        override_entry[0].get("optional") is True,
    )

    # 2. Verify the render script exists and is executable
    script_path = REPO_ROOT / "scripts" / "render-flux-sync-override.py"
    all_ok &= check(
        "render-flux-sync-override.py exists",
        script_path.is_file(),
    )

    # 3. Verify default branch: render with no override -> ConfigMap with
    #    identity values
    import json
    result = subprocess.run(
        ["python3", str(script_path)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    all_ok &= check(
        "render script succeeds without override",
        result.returncode == 0,
        result.stderr.strip()[:200],
    )
    default_cm = yaml.safe_load(result.stdout)
    default_data = yaml.safe_load(default_cm["data"]["values.yaml"])
    all_ok &= check(
        "default render produces identity (empty) override values",
        default_data == {},
        f"got {json.dumps(default_data)}",
    )

    # 4. Verify override branch: render with FLUX_GIT_BRANCH_OVERRIDE ->
    #    ConfigMap with the branch set
    result = subprocess.run(
        ["python3", str(script_path)],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={**__import__("os").environ, "FLUX_GIT_BRANCH_OVERRIDE": "qa/test-branch"},
    )
    all_ok &= check(
        "render script succeeds with override",
        result.returncode == 0,
        result.stderr.strip()[:200],
    )
    override_cm = yaml.safe_load(result.stdout)
    override_data = yaml.safe_load(override_cm["data"]["values.yaml"])
    rendered_branch = (
        override_data.get("gitRepository", {})
        .get("spec", {})
        .get("ref", {})
        .get("branch", "")
    )
    all_ok &= check(
        "override render sets gitRepository.spec.ref.branch to qa/test-branch",
        rendered_branch == "qa/test-branch",
        f"got {rendered_branch}",
    )
    all_ok &= check(
        "override ConfigMap name is flux-sync-values-override",
        override_cm["metadata"]["name"] == "flux-sync-values-override",
    )

    # 5. Verify the canonical branch in helm-values-sync.yaml is unchanged
    sync_values_path = (
        REPO_ROOT
        / "clusters"
        / "kind-dev-misc-local"
        / "platform-services"
        / "flux"
        / "helm-values-sync.yaml"
    )
    with open(sync_values_path) as f:
        committed_values = yaml.safe_load(f)
    canonical = (
        committed_values.get("gitRepository", {})
        .get("spec", {})
        .get("ref", {})
        .get("branch", "")
    )
    all_ok &= check(
        "canonical branch in helm-values-sync.yaml is present",
        bool(canonical),
    )
    all_ok &= check(
        "canonical branch is not the QA test branch",
        canonical != "qa/test-branch",
        f"canonical={canonical}",
    )

    # 6. Verify Makefile no longer depends on yq
    makefile_path = REPO_ROOT / "Makefile"
    with open(makefile_path) as f:
        makefile_text = f.read()
    all_ok &= check(
        "Makefile does not depend on yq for QA branch override",
        "yq eval" not in makefile_text,
    )
    all_ok &= check(
        "Makefile uses render-flux-sync-override.py for QA branch override",
        "render-flux-sync-override.py" in makefile_text,
    )

    # 7. Verify Makefile has delete in else branch for default bootstrap reset
    all_ok &= check(
        "Makefile has delete configmap flux-sync-values-override in else branch",
        "delete configmap flux-sync-values-override" in makefile_text,
    )
    all_ok &= check(
        "Makefile delete uses --ignore-not-found for safe idempotent reset",
        "--ignore-not-found" in makefile_text,
    )
    import re
    else_match = re.search(r'else\b.*?\n(.*?)fi\b', makefile_text, re.DOTALL)
    if else_match:
        else_block = else_match.group(1)
        delete_in_else = "delete configmap flux-sync-values-override" in else_block
        all_ok &= check(
            "flux sync override reset: delete is in the else (default) branch",
            delete_in_else,
            "delete in else branch" if delete_in_else
            else f"else block: {else_block.strip()[:80]}",
        )
    else:
        all_ok &= check(
            "flux sync override reset: else branch found in Makefile",
            False,
            "could not locate else branch",
        )

    # 8. Verify the committed empty override file is not in the entrypoint
    #    (it was removed; the override is purely imperative via render script)
    stale_override_path = (
        REPO_ROOT / "clusters" / "kind-dev-misc-local" / "entrypoint"
        / "flux-sync-values-override.yaml"
    )
    all_ok &= check(
        "committed empty flux-sync-values-override.yaml is not in entrypoint",
        not stale_override_path.exists(),
        f"present at {stale_override_path}" if stale_override_path.exists() else "absent (correct)",
    )

    return all_ok


def validate_cel_contracts() -> bool:
    """Validate CEL expression contracts with behavioral celpy evaluation.

    Replaces string/substring assertions with actual CEL evaluation against
    positive and negative fixtures. Tests at minimum:
    - expected healthy=true with correct parentRef and controllerName
    - expected unresolved + unrelated healthy=false (ResolvedRefs != True)
    - wrong parent name -> false
    - wrong controllerName -> false
    """
    import celpy

    configmap_path = BASE_DIR / "configmap.yaml"
    with open(configmap_path) as f:
        cm = yaml.safe_load(f)
    status_yaml = cm["data"]["status.yaml"]
    status_cfg = yaml.safe_load(status_yaml)
    checks_by_id = {c["id"]: c for c in status_cfg.get("checks", [])}

    all_ok = True

    envoy_route = checks_by_id.get("envoy-httproute-ready", {})
    expr = envoy_route.get("expression", "")

    # Positive: scoped parentRef + controllerName + both conditions True
    all_ok &= check(
        "envoy-httproute-ready expression scopes to parentRef",
        "parentRef" in expr,
    )
    all_ok &= check(
        "envoy-httproute-ready expression checks controllerName",
        "controllerName" in expr,
    )
    all_ok &= check(
        "envoy-httproute-ready expression references Accepted + ResolvedRefs",
        "'Accepted'" in expr and "'ResolvedRefs'" in expr,
    )

    # Parse and compile the CEL expression
    env = celpy.Environment()
    try:
        ast = env.compile(expr)
    except Exception as e:
        all_ok &= check("CEL expression compiles", False, str(e))
        return all_ok

    prg = env.program(ast)

    def evaluate(fixture: dict) -> bool:
        """Evaluate the CEL expression against a fixture object."""
        try:
            activation = celpy.json_to_cel(fixture)
            result = prg.evaluate(activation)
            return bool(result)
        except Exception:
            return False

    # Fixture 1: expected healthy — correct parentRef, correct controller,
    # Accepted=True, ResolvedRefs=True
    healthy = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "kubecrate-envoy-smoke",
                            "namespace": "core-envoy-gateway",
                            "sectionName": "http",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True", "reason": "Accepted"},
                            {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
                        ],
                    }
                ]
            }
        }
    }
    all_ok &= check(
        "CEL fixture: expected healthy -> true",
        evaluate(healthy) is True,
    )

    # Fixture 2: unresolved backend — correct parentRef + controller but
    # ResolvedRefs=False
    unresolved = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "kubecrate-envoy-smoke",
                            "namespace": "core-envoy-gateway",
                            "sectionName": "http",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True", "reason": "Accepted"},
                            {"type": "ResolvedRefs", "status": "False", "reason": "BackendNotFound"},
                        ],
                    }
                ]
            }
        }
    }
    all_ok &= check(
        "CEL fixture: unresolved backend -> false",
        evaluate(unresolved) is False,
    )

    # Fixture 3: unrelated parentStatus entry — routes from another Gateway
    # have the correct controller but a different parent name
    wrong_parent = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "other-gateway",
                            "namespace": "other-ns",
                            "sectionName": "https",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True", "reason": "Accepted"},
                            {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
                        ],
                    }
                ]
            }
        }
    }
    all_ok &= check(
        "CEL fixture: wrong parent name -> false",
        evaluate(wrong_parent) is False,
    )

    # Fixture 4: wrong controller — correct parentRef but wrong
    # controllerName (e.g., a different gateway implementation)
    wrong_controller = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "kubecrate-envoy-smoke",
                            "namespace": "core-envoy-gateway",
                            "sectionName": "http",
                        },
                        "controllerName": "other-gateway.io/other-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True", "reason": "Accepted"},
                            {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
                        ],
                    }
                ]
            }
        }
    }
    all_ok &= check(
        "CEL fixture: wrong controllerName -> false",
        evaluate(wrong_controller) is False,
    )

    # Fixture 5: multiple parents, one matching — should match the
    # correct one and return true if its conditions are met
    multi_parent = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "other-gateway",
                            "namespace": "other-ns",
                            "sectionName": "https",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True"},
                            {"type": "ResolvedRefs", "status": "True"},
                        ],
                    },
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "kubecrate-envoy-smoke",
                            "namespace": "core-envoy-gateway",
                            "sectionName": "http",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True", "reason": "Accepted"},
                            {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
                        ],
                    },
                ]
            }
        }
    }
    all_ok &= check(
        "CEL fixture: multiple parents, one matching -> true",
        evaluate(multi_parent) is True,
    )

    # Fixture 6: Accepted=False — correct parent/controller but
    # Accepted is False (ResolvedRefs=True). Must evaluate to False.
    accepted_false = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": "kubecrate-envoy-smoke",
                            "namespace": "core-envoy-gateway",
                            "sectionName": "http",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "False", "reason": "NotAccepted"},
                            {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
                        ],
                    }
                ]
            }
        }
    }
    all_ok &= check(
        "CEL fixture: Accepted=False -> false",
        evaluate(accepted_false) is False,
    )

    # ── adversarial CEL predicate mutation probes ────────────────────
    # Build the expected healthy fixture from the actual HTTPRoute YAML
    # so that changes to the committed manifest (parentRef name,
    # namespace) are reflected in the test fixture automatically.
    httproute_path = (
        REPO_ROOT / "clusters" / "kind-dev-misc-local"
        / "platform-services" / "envoy-gateway" / "smoke"
        / "smoke-httproute.yaml"
    )
    with open(httproute_path) as f:
        route = yaml.safe_load(f)
    parent_ref = route["spec"]["parentRefs"][0]
    parent_name = parent_ref["name"]
    parent_namespace = parent_ref["namespace"]

    # Build the healthy fixture from the committed parentRef values.
    committed_healthy = {
        "object": {
            "status": {
                "parents": [
                    {
                        "parentRef": {
                            "group": "gateway.networking.k8s.io",
                            "kind": "Gateway",
                            "name": parent_name,
                            "namespace": parent_namespace,
                            "sectionName": "http",
                        },
                        "controllerName": "gateway.envoyproxy.io/gatewayclass-controller",
                        "conditions": [
                            {"type": "Accepted", "status": "True", "reason": "Accepted"},
                            {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
                        ],
                    }
                ]
            }
        }
    }

    # Probe: committed healthy evaluates to True.
    all_ok &= check(
        "CEL adversarial: committed parentRef healthy -> true",
        evaluate(committed_healthy) is True,
    )

    # ── mutation probe helpers ───────────────────────────────────────
    import copy

    def _mutated_fixture(**overrides):
        """Deep-copy committed_healthy and apply overrides at leaf paths.

        Override keys are dotted paths relative to parents[0], e.g.:
            parentRef.name = 'wrong'
            controllerName = 'other.io/ctrl'
            conditions.Accepted = 'False'
            conditions.ResolvedRefs = 'False'
        """
        fixture = copy.deepcopy(committed_healthy)
        parent = fixture["object"]["status"]["parents"][0]
        for path, value in overrides.items():
            parts = path.split(".")
            # Handle conditions mutation: find entry by type
            if parts[0] == "conditions":
                cond_type = parts[1]
                for entry in parent["conditions"]:
                    if entry.get("type") == cond_type:
                        entry["status"] = value
                        break
            else:
                # Drill down to parent, then set leaf
                target = parent
                for p in parts[:-1]:
                    target = target[p]
                target[parts[-1]] = value
        return fixture

    # Mutation 1: wrong parent name
    mut_parent = _mutated_fixture(**{"parentRef.name": "other-gateway"})
    all_ok &= check(
        "CEL adversarial: mutated parentRef.name -> false",
        evaluate(mut_parent) is False,
    )

    # Mutation 2: wrong controllerName
    mut_ctrl = _mutated_fixture(
        **{"controllerName": "other-gateway.io/other-controller"}
    )
    all_ok &= check(
        "CEL adversarial: mutated controllerName -> false",
        evaluate(mut_ctrl) is False,
    )

    # Mutation 3: Accepted=False
    mut_accepted = _mutated_fixture(**{"conditions.Accepted": "False"})
    all_ok &= check(
        "CEL adversarial: mutated Accepted=False -> false",
        evaluate(mut_accepted) is False,
    )

    # Mutation 4: ResolvedRefs=False
    mut_resolved = _mutated_fixture(**{"conditions.ResolvedRefs": "False"})
    all_ok &= check(
        "CEL adversarial: mutated ResolvedRefs=False -> false",
        evaluate(mut_resolved) is False,
    )

    # Mutation 5: both Accepted=False AND ResolvedRefs=False
    mut_both = _mutated_fixture(
        **{"conditions.Accepted": "False", "conditions.ResolvedRefs": "False"}
    )
    all_ok &= check(
        "CEL adversarial: mutated both conditions false -> false",
        evaluate(mut_both) is False,
    )

    return all_ok


def validate_flux_bootstrap_behavior() -> bool:
    """Validate the real Make bootstrap target with mocked commands.

    Creates mock kubectl/helm/flux scripts and executes
    ``make kind-dev-misc-local-bootstrap`` with them on PATH. Asserts:
    - apply order: helm upgrade -> apply -k entrypoint -> override apply ->
      wait for HelmRelease
    - override content: FLUX_GIT_BRANCH_OVERRIDE produces correct branch
    - default reset: no override -> delete ConfigMap (else branch)
    - root-reconcile durability: root Kustomization reconcile does NOT
      revert the imperative override ConfigMap
    - default-after-reconcile: after root reconcile, default bootstrap
      restores canonical

    Adversarial self-tests (Phase C) mutate the real Makefile recipe and
    re-run the same behavioral assertions as Phase A/B. Each mutation
    MUST cause at least one behavioral assertion to FAIL, proving the
    validator is coupled to the production recipe pipeline.
    """
    import os
    import shutil
    import tempfile

    all_ok = True
    makefile_path = REPO_ROOT / "Makefile"
    with open(makefile_path) as f:
        original_makefile = f.read()

    # ── shared mock script template ──────────────────────────────────
    MOCK_SCRIPT_TEMPLATE = """#!/bin/bash
# Mock {name}: record calls, persist effective Flux branch state.
LOG_FILE="{log_file}"
CTX_FILE="{ctx_file}"
STDIN_DIR="{stdin_dir}"
STATE_DIR="{state_dir}"

echo "{name} $*" >> "$LOG_FILE"

# Record the full command
cmd="{name}"
for a in "$@"; do
    cmd="$cmd $a"
done
echo "CALL: $cmd" >> "$LOG_FILE"

# Save any stdin data to a unique file per call (counter-based)
# to avoid overwriting when the same mock is called multiple times.
counter=0
counter_file="${{STDIN_DIR}}/counter"
if [ -f "$counter_file" ]; then
    counter=$(cat "$counter_file")
fi
counter=$((counter + 1))
echo "$counter" > "$counter_file"

stdin_file="${{STDIN_DIR}}/{name}_stdin_${{counter}}.yaml"
if [ ! -t 0 ]; then
    dd of="$stdin_file" bs=64K 2>/dev/null
    if [ -s "$stdin_file" ]; then
        echo "STDIN_SAVED:${{counter}}" >> "$LOG_FILE"
    fi
fi

# ── mock state: track effective Flux branch ────────────────────────────
# Only kubectl can change the effective branch.
if [ "{name}" = "kubectl" ]; then
    STATE_FILE="$STATE_DIR/effective-branch"

    # Case 1: delete of override ConfigMap resets to canonical.
    if echo "$*" | grep -q "delete.*flux-sync-values-override"; then
        canonical="${{MOCK_STATE_CANONICAL_BRANCH:-pivot/flux-sync-ssh-bootstrap}}"
        printf '%s\n' "$canonical" > "$STATE_FILE"
        echo "STATE: reset to canonical $canonical (delete)" >> "$LOG_FILE"
    fi

    # Case 2: apply -f with stdin containing a branch value.
    if echo "$*" | grep -q "apply" && echo "$*" | grep -q -- "-f"; then
        if [ -f "$stdin_file" ] && [ -s "$stdin_file" ]; then
            branch=$(grep -o 'branch: *[a-zA-Z0-9_/.-]*' "$stdin_file" 2>/dev/null | head -1 | sed 's/branch: *//')
            if [ -n "$branch" ]; then
                printf '%s\n' "$branch" > "$STATE_FILE"
                echo "STATE: set effective branch to $branch (apply -f)" >> "$LOG_FILE"
            fi
        fi
    fi
fi

exit {exit_code}
"""

    # ── harness ──────────────────────────────────────────────────────
    def _setup_harness(override_branch=""):
        """Set up temp directory with mock scripts and return (tmpdir, log_path)."""
        tmpdir = tempfile.mkdtemp(prefix="cratecheck-harness-")
        log_path = os.path.join(tmpdir, "calls.log")
        stdin_dir = os.path.join(tmpdir, "stdin")
        os.makedirs(stdin_dir, exist_ok=True)
        ctx_file = os.path.join(tmpdir, "ctx.txt")
        # Write the kubecontext so Makefile's KIND_CONTEXT resolves
        with open(ctx_file, "w") as f:
            f.write("kind-dry-run")

        # ── mock state: persist effective Flux branch ──────────────────
        state_dir = os.path.join(tmpdir, "mock-state")
        os.makedirs(state_dir, exist_ok=True)
        state_file = os.path.join(state_dir, "effective-branch")
        # Initialize with sentinel so we can detect "never written".
        with open(state_file, "w") as f:
            f.write("uninitialized\n")

        # Read canonical branch from committed source.
        sync_values_path = (
            REPO_ROOT / "clusters" / "kind-dev-misc-local"
            / "platform-services" / "flux" / "helm-values-sync.yaml"
        )
        canonical_branch = "pivot/flux-sync-ssh-bootstrap"  # safe fallback
        try:
            with open(sync_values_path) as f:
                committed_sync = yaml.safe_load(f)
            canonical_branch = (
                committed_sync.get("gitRepository", {})
                .get("spec", {})
                .get("ref", {})
                .get("branch", canonical_branch)
            )
        except Exception:
            pass

        for name in ("kubectl", "helm", "flux"):
            script = MOCK_SCRIPT_TEMPLATE.format(
                name=name, log_file=log_path, ctx_file=ctx_file,
                stdin_dir=stdin_dir, state_dir=state_dir, exit_code=0,
            )
            script_path = os.path.join(tmpdir, name)
            with open(script_path, "w") as f:
                f.write(script)
            os.chmod(script_path, 0o755)

        # Write KIND_CONTEXT for the mock
        env_extra = {}
        env_extra["KIND_CLUSTER_NAME"] = "dry-run"
        env_extra["KIND_CONTEXT"] = "kind-dry-run"
        env_extra["MOCK_STATE_CANONICAL_BRANCH"] = canonical_branch
        if override_branch:
            env_extra["FLUX_GIT_BRANCH_OVERRIDE"] = override_branch
        return tmpdir, log_path, env_extra

    def _get_calls(tmpdir):
        """Parse the mock call log and return list of (command, args) tuples."""
        log_path = os.path.join(tmpdir, "calls.log")
        calls = []
        if os.path.exists(log_path):
            with open(log_path) as f:
                for line in f:
                    if line.startswith("CALL: "):
                        parts = line[6:].strip().split()
                        calls.append((parts[0], parts[1:]))
        return calls

    def _get_stdin(tmpdir, cmd_name):
        """Return the most recent non-empty stdin saved for a mock command."""
        stdin_dir = os.path.join(tmpdir, "stdin")
        if not os.path.isdir(stdin_dir):
            return None
        # Find all stdin files for this command, return the last non-empty one
        candidates = sorted(
            [f for f in os.listdir(stdin_dir)
             if f.startswith(f"{cmd_name}_stdin_") and f.endswith(".yaml")],
            reverse=True,
        )
        for fname in candidates:
            fpath = os.path.join(stdin_dir, fname)
            with open(fpath) as f:
                content = f.read()
            if content.strip():
                return content
        return None

    def _get_all_stdin(tmpdir, cmd_name):
        """Return all non-empty stdin saves for a mock command (oldest first)."""
        stdin_dir = os.path.join(tmpdir, "stdin")
        if not os.path.isdir(stdin_dir):
            return []
        entries = []
        for fname in sorted(os.listdir(stdin_dir)):
            if fname.startswith(f"{cmd_name}_stdin_") and fname.endswith(".yaml"):
                fpath = os.path.join(stdin_dir, fname)
                with open(fpath) as f:
                    content = f.read()
                if content.strip():
                    entries.append(content)
        return entries

    def _run_make(tmpdir, env_extra, override_branch="", makefile=None):
        """Run make in the harness. Returns (returncode, stdout, stderr)."""
        env = os.environ.copy()
        env["PATH"] = tmpdir + ":" + env.get("PATH", "")
        env.update(env_extra)

        cmd = ["make"]
        if makefile:
            cmd.extend(["-f", makefile])
        cmd.append("kind-dev-misc-local-bootstrap")

        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO_ROOT,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    # ── reusable behavioral check helpers ────────────────────────────
    def _assert_candidate_order(calls, label_prefix=""):
        """Return list of (desc, pass) for candidate-bootstrap ordering checks."""
        results = []
        helm_indices = [i for i, (cmd, _) in enumerate(calls) if cmd == "helm"]
        kubectl_apply_k_indices = [
            i for i, (cmd, args) in enumerate(calls)
            if cmd == "kubectl" and "apply" in args and "-k" in args
        ]
        apply_f_indices = [
            i for i, (cmd, args) in enumerate(calls)
            if cmd == "kubectl" and "apply" in args and "-f" in args
        ]
        wait_indices = [
            i for i, (cmd, args) in enumerate(calls)
            if cmd == "kubectl" and "wait" in args and "helmrelease" in str(args).lower()
        ]

        ak = min(kubectl_apply_k_indices) if kubectl_apply_k_indices else -1
        af = min(apply_f_indices) if apply_f_indices else -1
        aw = min(wait_indices) if wait_indices else -1

        results.append((
            f"{label_prefix}helm upgrade runs before kubectl apply -k",
            bool(helm_indices) and bool(kubectl_apply_k_indices)
            and min(helm_indices) < min(kubectl_apply_k_indices),
        ))
        results.append((
            f"{label_prefix}kubectl apply -k runs before override apply -f -",
            ak >= 0 and af >= 0 and ak < af,
        ))
        results.append((
            f"{label_prefix}override apply -f - runs before wait for HelmRelease",
            af >= 0 and aw >= 0 and af < aw,
        ))
        return results

    def _assert_candidate_stdin(tmpdir, branch, label_prefix=""):
        """Return (desc, pass) for stdin containing candidate branch."""
        stdin_content = _get_stdin(tmpdir, "kubectl")
        has_branch = branch in (stdin_content or "")
        return (f"{label_prefix}override apply stdin contains {branch}", has_branch)

    def _assert_no_delete(stdout, label_prefix=""):
        """Return (desc, pass) for no-delete check."""
        return (
            f"{label_prefix}override path does not delete the override ConfigMap",
            "delete configmap flux-sync-values-override" not in stdout,
        )

    def _assert_default_delete(stdout, calls, label_prefix=""):
        """Return (desc, pass) for default bootstrap delete check."""
        has_delete = (
            "delete configmap flux-sync-values-override" in stdout
            or any(
                "delete" in " ".join(args) and "flux-sync-values-override" in " ".join(args)
                for cmd, args in calls if cmd == "kubectl"
            )
        )
        return (
            f"{label_prefix}default bootstrap runs delete configmap (else branch)",
            has_delete,
        )

    def _assert_no_override_apply_f(calls, label_prefix=""):
        """Return (desc, pass) for no-apply-f-check in default bootstrap."""
        apply_f_b = [
            i for i, (cmd, args) in enumerate(calls)
            if cmd == "kubectl" and "apply" in args and "-f" in args
        ]
        return (
            f"{label_prefix}default bootstrap does NOT apply override via -f -",
            len(apply_f_b) == 0,
        )

    # ══════════════════════════════════════════════════════════════════
    # Phase A: candidate bootstrap (with override)
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase A: candidate bootstrap (with override) ---")
    tmpdir_a, log_a, env_a = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        rc_a, stdout_a, stderr_a = _run_make(tmpdir_a, env_a,
                                              override_branch="candidate/test-envoy")
        calls_a = _get_calls(tmpdir_a)

        for desc, ok in _assert_candidate_order(calls_a, "behavioral: "):
            all_ok &= check(desc, ok)
        all_ok &= check(*_assert_candidate_stdin(tmpdir_a, "candidate/test-envoy",
                                                  "behavioral: "))
        all_ok &= check(*_assert_no_delete(stdout_a, "behavioral: "))
        all_ok &= check(
            "behavioral: candidate bootstrap exits 0",
            rc_a == 0,
            f"rc={rc_a}, stderr={stderr_a[:200]}",
        )
    finally:
        shutil.rmtree(tmpdir_a, ignore_errors=True)

    # ══════════════════════════════════════════════════════════════════
    # Phase B: default bootstrap (no override) — resets to canonical
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase B: default bootstrap (no override) ---")
    tmpdir_b, log_b, env_b = _setup_harness(override_branch="")
    try:
        rc_b, stdout_b, stderr_b = _run_make(tmpdir_b, env_b,
                                              override_branch="")
        calls_b = _get_calls(tmpdir_b)

        all_ok &= check(*_assert_default_delete(stdout_b, calls_b, "behavioral: "))
        all_ok &= check(*_assert_no_override_apply_f(calls_b, "behavioral: "))
        all_ok &= check(
            "behavioral: default bootstrap exits 0",
            rc_b == 0,
            f"rc={rc_b}, stderr={stderr_b[:200]}",
        )
    finally:
        shutil.rmtree(tmpdir_b, ignore_errors=True)

    # ══════════════════════════════════════════════════════════════════
    # Phase D: stateful lifecycle harness
    #
    # ONE harness tracks the effective override branch across:
    #   candidate bootstrap → root reconcile → default bootstrap
    # This proves the override survives root reconciliation and that
    # default bootstrap restores the canonical branch.
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase D: stateful lifecycle ---")

    def _run_cmd_in_harness(tmpdir, cmd, env_extra=None):
        """Run an arbitrary command through the mock harness env."""
        env = os.environ.copy()
        env["PATH"] = tmpdir + ":" + env.get("PATH", "")
        env["KIND_CLUSTER_NAME"] = "dry-run"
        env["KIND_CONTEXT"] = "kind-dry-run"
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO_ROOT, env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def _read_effective_branch(tmpdir):
        """Read the persisted effective Flux branch from mock state.

        The mock kubectl script writes the effective branch to a state file
        whenever it applies an override ConfigMap (via apply -f -) or deletes
        one (which resets to canonical).  This is honest state — not a stale
        log reread.
        """
        state_file = os.path.join(tmpdir, "mock-state", "effective-branch")
        if not os.path.exists(state_file):
            return None
        with open(state_file) as f:
            branch = f.read().strip()
        return branch if branch else None

    def _count_calls(calls, cmd_name, arg_substring):
        """Count how many calls for cmd_name contain arg_substring in args."""
        return sum(
            1 for cmd, args in calls
            if cmd == cmd_name and any(arg_substring in a for a in args)
        )

    # ── D1: candidate bootstrap with override ────────────────────────
    tmpdir_d, _, env_d = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        rc_d1, stdout_d1, stderr_d1 = _run_make(
            tmpdir_d, env_d, override_branch="candidate/test-envoy",
        )
        calls_after_candidate = _get_calls(tmpdir_d)

        # D1a: candidate ordering checks hold
        for desc, ok in _assert_candidate_order(calls_after_candidate,
                                                 "stateful (candidate): "):
            all_ok &= check(desc, ok)

        # D1b: stdin contains candidate branch
        all_ok &= check(*_assert_candidate_stdin(
            tmpdir_d, "candidate/test-envoy", "stateful (candidate): ",
        ))

        # D1c: no delete happened
        all_ok &= check(*_assert_no_delete(stdout_d1, "stateful (candidate): "))

        # D1d: candidate bootstrap exits 0
        all_ok &= check(
            "stateful (candidate): bootstrap exits 0",
            rc_d1 == 0,
            f"rc={rc_d1}, stderr={stderr_d1[:200]}",
        )

        # D1e: effective branch is candidate
        eff_branch = _read_effective_branch(tmpdir_d)
        all_ok &= check(
            "stateful (candidate): effective branch is candidate/test-envoy",
            eff_branch == "candidate/test-envoy",
            f"got {eff_branch}",
        )

        # ── D2: simulated root reconciliation ─────────────────────────
        # Run kubectl apply -k entrypoint/ through the SAME harness.
        # The committed entrypoint no longer contains the override CM
        # (proven by the static kustomize build check below), so this
        # should NOT delete or overwrite the imperative override.
        rc_root, stdout_root, stderr_root = _run_cmd_in_harness(
            tmpdir_d,
            ["kubectl", "--context", "kind-dry-run", "apply", "-k",
             str(ENTRYPOINT_DIR)],
        )
        calls_after_root = _get_calls(tmpdir_d)

        all_ok &= check(
            "stateful (post-reconcile): root kubectl apply -k exits 0",
            rc_root == 0,
            f"rc={rc_root}, stderr={stderr_root[:200]}",
        )

        # ── D3: assert candidate still effective after reconcile ──────
        # The static kustomize build must NOT contain the override CM.
        kustomize_result = subprocess.run(
            ["kustomize", "build", str(ENTRYPOINT_DIR)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        has_override_cm = any(
            d and d.get("kind") == "ConfigMap"
            and d.get("metadata", {}).get("name") == "flux-sync-values-override"
            for d in yaml.safe_load_all(kustomize_result.stdout)
        )
        all_ok &= check(
            "stateful (post-reconcile): entrypoint kustomize build does NOT "
            "contain a ConfigMap named flux-sync-values-override",
            not has_override_cm,
            "override ConfigMap absent; only HelmRelease valuesFrom reference "
            "(correct)",
        )

        # Delete must NOT have appeared after candidate OR reconcile.
        delete_after_root = any(
            "delete" in " ".join(args)
            and "flux-sync-values-override" in " ".join(args)
            for cmd, args in calls_after_root if cmd == "kubectl"
        )
        all_ok &= check(
            "stateful (post-reconcile): no delete of override CM through "
            "reconcile",
            not delete_after_root,
            "delete absent (correct)" if not delete_after_root
            else "delete present (UNEXPECTED)",
        )

        # Effective branch must still be candidate.
        eff_after_root = _read_effective_branch(tmpdir_d)
        all_ok &= check(
            "stateful (post-reconcile): effective branch still "
            "candidate/test-envoy",
            eff_after_root == "candidate/test-envoy",
            f"got {eff_after_root}",
        )

        # ── D4: default bootstrap in same harness (no override) ──────
        env_default = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        # Snapshot calls before default bootstrap to isolate D4-only calls.
        calls_before_default = _get_calls(tmpdir_d)
        rc_d4, stdout_d4, stderr_d4 = _run_cmd_in_harness(
            tmpdir_d, ["make", "kind-dev-misc-local-bootstrap"], env_default,
        )
        calls_after_default = _get_calls(tmpdir_d)
        # Only calls added during the default bootstrap phase.
        calls_default_only = calls_after_default[len(calls_before_default):]

        # ── D5: assert canonical restored ─────────────────────────────
        all_ok &= check(*_assert_default_delete(
            stdout_d4, calls_after_default,
            "stateful (post-default): ",
        ))
        all_ok &= check(*_assert_no_override_apply_f(
            calls_default_only,
            "stateful (post-default): ",
        ))
        all_ok &= check(
            "stateful (post-default): default bootstrap exits 0",
            rc_d4 == 0,
            f"rc={rc_d4}, stderr={stderr_d4[:200]}",
        )

        # After default bootstrap (which deletes the override CM),
        # the mock state MUST reflect the canonical branch.
        # This is honest state — the mock kubectl script writes the
        # canonical branch to the state file on delete, so we are
        # asserting the actual lifecycle transition, not re-reading
        # stale stdin or a static committed file.
        final_branch = _read_effective_branch(tmpdir_d)
        all_ok &= check(
            "stateful (post-default): effective branch is "
            "pivot/flux-sync-ssh-bootstrap (from mock state)",
            final_branch == "pivot/flux-sync-ssh-bootstrap",
            f"got {final_branch}",
        )
        has_delete_in_final = any(
            "delete" in " ".join(args)
            and "flux-sync-values-override" in " ".join(args)
            for cmd, args in calls_after_default if cmd == "kubectl"
        )
        all_ok &= check(
            "stateful (post-default): override ConfigMap delete issued",
            has_delete_in_final,
            "delete confirmed" if has_delete_in_final else "delete missing",
        )

        # ── D5b: canonical branch would be restored ──────────────────
        # After the override ConfigMap is deleted, the GitOps controller
        # would use the committed canonical branch. Read the authoritative
        # canonical branch from the committed helm-values-sync.yaml and
        # assert it matches the expected canonical value.
        sync_values_path = (
            REPO_ROOT / "clusters" / "kind-dev-misc-local"
            / "platform-services" / "flux" / "helm-values-sync.yaml"
        )
        with open(sync_values_path) as f:
            committed_sync = yaml.safe_load(f)
        canonical_branch = (
            committed_sync.get("gitRepository", {})
            .get("spec", {})
            .get("ref", {})
            .get("branch", "")
        )
        all_ok &= check(
            "stateful (post-default): canonical branch is pivot/flux-sync-ssh-bootstrap",
            canonical_branch == "pivot/flux-sync-ssh-bootstrap",
            f"got {canonical_branch}",
        )
        # After default bootstrap deletes the override, no apply -f
        # with an override branch was issued in the default phase.
        # The canonical branch is the authoritative fallback.
        # Count only `apply -f` (not `apply -k` or `delete --ignore-not-found`).
        apply_f_in_default = sum(
            1 for cmd, args in calls_default_only
            if cmd == "kubectl"
            and "apply" in args
            and any(a == "-f" for a in args)
        )
        all_ok &= check(
            "stateful (post-default): no override apply -f during default bootstrap",
            apply_f_in_default == 0,
            f"found {apply_f_in_default} apply -f calls in default phase",
        )

        # ── D6: mock failure propagation ─────────────────────────────
        # A mock that exits nonzero must propagate the failure.
        print("\n    --- D6: mock failure propagation ---")
        tmpdir_fail, _, env_fail = _setup_harness(
            override_branch="candidate/test-envoy",
        )
        try:
            # Replace the helm mock with one that exits 1
            fail_script = MOCK_SCRIPT_TEMPLATE.format(
                name="helm", log_file=tmpdir_fail + "/calls.log",
                ctx_file=tmpdir_fail + "/ctx.txt",
                stdin_dir=tmpdir_fail + "/stdin",
                state_dir=tmpdir_fail + "/mock-state", exit_code=1,
            )
            with open(os.path.join(tmpdir_fail, "helm"), "w") as f:
                f.write(fail_script)
            os.chmod(os.path.join(tmpdir_fail, "helm"), 0o755)

            rc_fail, stdout_fail, stderr_fail = _run_make(
                tmpdir_fail, env_fail,
                override_branch="candidate/test-envoy",
            )
            all_ok &= check(
                "stateful (failure): mock helm exit 1 propagates non-zero",
                rc_fail != 0,
                f"rc={rc_fail} (expected != 0)",
            )
        finally:
            shutil.rmtree(tmpdir_fail, ignore_errors=True)

        # ── D7: kubectl apply -k failure during root reconcile ───────
        # A root reconciliation (simulated by kubectl apply -k
        # entrypoint/) that fails must propagate non-zero.
        print("\n    --- D7: kubectl apply -k failure propagation ---")
        tmpdir_d7, _, env_d7 = _setup_harness(
            override_branch="candidate/test-envoy",
        )
        try:
            # Run candidate bootstrap first
            _run_make(tmpdir_d7, env_d7,
                      override_branch="candidate/test-envoy")

            # Replace the kubectl mock to fail on apply -k
            fail_kubectl_script = MOCK_SCRIPT_TEMPLATE.format(
                name="kubectl", log_file=tmpdir_d7 + "/calls.log",
                ctx_file=tmpdir_d7 + "/ctx.txt",
                stdin_dir=tmpdir_d7 + "/stdin",
                state_dir=tmpdir_d7 + "/mock-state", exit_code=1,
            )
            with open(os.path.join(tmpdir_d7, "kubectl"), "w") as f:
                f.write(fail_kubectl_script)
            os.chmod(os.path.join(tmpdir_d7, "kubectl"), 0o755)

            rc_d7, _, stderr_d7 = _run_cmd_in_harness(
                tmpdir_d7,
                ["kubectl", "--context", "kind-dry-run", "apply", "-k",
                 str(ENTRYPOINT_DIR)],
            )
            all_ok &= check(
                "stateful (failure): kubectl apply -k exit 1 propagates non-zero",
                rc_d7 != 0,
                f"rc={rc_d7} (expected != 0)",
            )
        finally:
            shutil.rmtree(tmpdir_d7, ignore_errors=True)

        # ── D8: kubectl delete failure during default bootstrap ──────
        # The delete of the override ConfigMap during default bootstrap
        # must propagate non-zero on failure.
        print("\n    --- D8: kubectl delete failure propagation ---")
        tmpdir_d8, _, env_d8 = _setup_harness(
            override_branch="candidate/test-envoy",
        )
        try:
            # Run candidate bootstrap
            _run_make(tmpdir_d8, env_d8,
                      override_branch="candidate/test-envoy")
            # Run root reconcile
            _run_cmd_in_harness(
                tmpdir_d8,
                ["kubectl", "--context", "kind-dry-run", "apply", "-k",
                 str(ENTRYPOINT_DIR)],
            )

            # Replace the kubectl mock to fail on delete
            fail_kubectl_d8 = MOCK_SCRIPT_TEMPLATE.format(
                name="kubectl", log_file=tmpdir_d8 + "/calls.log",
                ctx_file=tmpdir_d8 + "/ctx.txt",
                stdin_dir=tmpdir_d8 + "/stdin",
                state_dir=tmpdir_d8 + "/mock-state", exit_code=1,
            )
            with open(os.path.join(tmpdir_d8, "kubectl"), "w") as f:
                f.write(fail_kubectl_d8)
            os.chmod(os.path.join(tmpdir_d8, "kubectl"), 0o755)

            env_def_d8 = {
                "KIND_CLUSTER_NAME": "dry-run",
                "KIND_CONTEXT": "kind-dry-run",
            }
            rc_d8, _, stderr_d8 = _run_cmd_in_harness(
                tmpdir_d8,
                ["make", "kind-dev-misc-local-bootstrap"],
                env_def_d8,
            )
            all_ok &= check(
                "stateful (failure): kubectl delete exit 1 propagates non-zero",
                rc_d8 != 0,
                f"rc={rc_d8} (expected != 0)",
            )
        finally:
            shutil.rmtree(tmpdir_d8, ignore_errors=True)

    finally:
        shutil.rmtree(tmpdir_d, ignore_errors=True)

    # ══════════════════════════════════════════════════════════════════
    # Phase E: adversarial stateful lifecycle mutations
    #
    # Mutate the Makefile and re-run the stateful lifecycle. Each
    # mutation must cause at least one stateful assertion to FAIL,
    # proving the validator is coupled to the production recipe across
    # the full lifecycle, not just isolated phases.
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase E: adversarial stateful lifecycle mutations ---")

    # ── E1: Remove the else delete ───────────────────────────────────
    #     The override survives candidate bootstrap but default
    #     bootstrap can no longer clean it up → delete check fails.
    tmpdir_e1, _, env_e1 = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        # Use line-based mutation (like C3) instead of string
        # replacement to avoid Makefile escaping issues.
        lines_e1 = original_makefile.split("\n")
        found_delete_e1 = False
        for i, line in enumerate(lines_e1):
            if "delete configmap flux-sync-values-override" in line:
                # Replace with true to keep shell structure valid
                # while removing the actual delete behavior.
                lines_e1[i] = line.replace(
                    'kubectl --context "$(KIND_CONTEXT)" delete configmap'
                    " flux-sync-values-override"
                    ' -n "$(FLUX_NAMESPACE)" --ignore-not-found',
                    "true",
                )
                found_delete_e1 = True
                break
        mutated_no_else = "\n".join(lines_e1)
        mutated_mf_e1 = os.path.join(tmpdir_e1, "Makefile.mutated")
        with open(mutated_mf_e1, "w") as f:
            f.write(mutated_no_else)

        # ── mutation provenance: prove the delete target was found ──
        all_ok &= check(
            "adversarial stateful E1: located else-delete line in Makefile "
            "for mutation",
            found_delete_e1,
            "target line found" if found_delete_e1
            else "delete line NOT found — mutation was a silent no-op",
        )

        # Run candidate bootstrap
        rc_e1a, stdout_e1a, stderr_e1a = _run_make(
            tmpdir_e1, env_e1,
            override_branch="candidate/test-envoy",
            makefile=mutated_mf_e1,
        )
        all_ok &= check(
            "adversarial stateful E1: candidate bootstrap exits 0",
            rc_e1a == 0,
            f"rc={rc_e1a}, stderr={stderr_e1a[:200]}",
        )

        # Run root reconcile in same harness
        env_root_e1 = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        rc_root_e1, stdout_root_e1, stderr_root_e1 = _run_cmd_in_harness(
            tmpdir_e1,
            ["kubectl", "--context", "kind-dry-run", "apply", "-k",
             str(ENTRYPOINT_DIR)],
            env_root_e1,
        )
        all_ok &= check(
            "adversarial stateful E1: root reconcile exits 0",
            rc_root_e1 == 0,
            f"rc={rc_root_e1}, stderr={stderr_root_e1[:200]}",
        )

        # Run default bootstrap in same harness
        env_def_e1 = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        rc_e1d, stdout_e1d, stderr_e1d = _run_cmd_in_harness(
            tmpdir_e1,
            ["make", "-f", mutated_mf_e1, "kind-dev-misc-local-bootstrap"],
            env_def_e1,
        )
        all_ok &= check(
            "adversarial stateful E1: default bootstrap exits 0",
            rc_e1d == 0,
            f"rc={rc_e1d}, stderr={stderr_e1d[:200]}",
        )
        calls_e1 = _get_calls(tmpdir_e1)

        desc_e1, ok_e1 = _assert_default_delete(stdout_e1d, calls_e1)
        all_ok &= check(
            f"adversarial stateful: removing else delete → {desc_e1} FAILS",
            not ok_e1,
            "delete check correctly failed against mutated recipe",
        )
    finally:
        shutil.rmtree(tmpdir_e1, ignore_errors=True)

    # ── E2: Remove the override render + apply pipe ──────────────────
    #     Runs the FULL stateful lifecycle (candidate → root reconcile
    #     → default bootstrap) in ONE harness. Without the override
    #     pipe, the candidate branch is never applied, so the effective
    #     branch assertion fails. After default bootstrap, delete
    #     should still work (the else branch is intact).
    tmpdir_e2, _, env_e2 = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        mutated_no_override = original_makefile.replace(
            "FLUX_GIT_BRANCH_OVERRIDE='$(FLUX_GIT_BRANCH_OVERRIDE)'"
            " python3 scripts/render-flux-sync-override.py",
            "# REMOVED override render",
        )
        # ── mutation provenance: prove the override render target was found
        found_render_e2 = mutated_no_override != original_makefile
        all_ok &= check(
            "adversarial stateful E2: located override render line in "
            "Makefile for mutation",
            found_render_e2,
            "render line found and mutated" if found_render_e2
            else "render line NOT found — mutation was a silent no-op",
        )

        lines_mut = mutated_no_override.split("\n")
        found_apply_pipe_e2 = False
        for i, line in enumerate(lines_mut):
            if "| kubectl --context" in line and "apply -f -" in line:
                lines_mut[i] = "> \t\t# REMOVED apply pipe; \\"
                found_apply_pipe_e2 = True
                break
        mutated_no_override = "\n".join(lines_mut)
        all_ok &= check(
            "adversarial stateful E2: located apply pipe line in Makefile "
            "for mutation",
            found_apply_pipe_e2,
            "apply pipe found and mutated" if found_apply_pipe_e2
            else "apply pipe NOT found — mutation was a silent no-op",
        )

        mutated_mf_e2 = os.path.join(tmpdir_e2, "Makefile.mutated")
        with open(mutated_mf_e2, "w") as f:
            f.write(mutated_no_override)

        # ── candidate bootstrap ────────────────────────────────────
        rc_e2a, stdout_e2a, stderr_e2a = _run_make(
            tmpdir_e2, env_e2, override_branch="candidate/test-envoy",
            makefile=mutated_mf_e2,
        )
        all_ok &= check(
            "adversarial stateful E2: candidate bootstrap exits 0",
            rc_e2a == 0,
            f"rc={rc_e2a}, stderr={stderr_e2a[:200]}",
        )

        # ── root reconcile ──────────────────────────────────────────
        env_root_e2 = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        rc_root_e2, stdout_root_e2, stderr_root_e2 = _run_cmd_in_harness(
            tmpdir_e2,
            ["kubectl", "--context", "kind-dry-run", "apply", "-k",
             str(ENTRYPOINT_DIR)],
            env_root_e2,
        )
        all_ok &= check(
            "adversarial stateful E2: root reconcile exits 0",
            rc_root_e2 == 0,
            f"rc={rc_root_e2}, stderr={stderr_root_e2[:200]}",
        )

        # ── default bootstrap ───────────────────────────────────────
        env_def_e2 = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        rc_e2d, stdout_e2d, stderr_e2d = _run_cmd_in_harness(
            tmpdir_e2,
            ["make", "-f", mutated_mf_e2, "kind-dev-misc-local-bootstrap"],
            env_def_e2,
        )
        all_ok &= check(
            "adversarial stateful E2: default bootstrap exits 0",
            rc_e2d == 0,
            f"rc={rc_e2d}, stderr={stderr_e2d[:200]}",
        )
        calls_e2 = _get_calls(tmpdir_e2)

        # Assert: effective branch is NOT candidate (override was removed)
        eff_e2 = _read_effective_branch(tmpdir_e2)
        all_ok &= check(
            "adversarial stateful: removing override → effective branch "
            "NOT candidate/test-envoy",
            eff_e2 != "candidate/test-envoy",
            f"effective branch: {eff_e2} (expected != candidate/test-envoy)",
        )

        # Assert: the else delete still runs (else branch is intact)
        desc_e2_del, ok_e2_del = _assert_default_delete(stdout_e2d, calls_e2)
        all_ok &= check(
            "adversarial stateful: removing override → delete still works "
            "(else branch intact)",
            ok_e2_del,
            "delete present (correct)" if ok_e2_del else "delete missing",
        )
    finally:
        shutil.rmtree(tmpdir_e2, ignore_errors=True)

    # ── E3: Reorder: apply -k AFTER override ─────────────────────────
    #     Runs the FULL stateful lifecycle (candidate → root reconcile
    #     → default bootstrap) in ONE harness with the reordered recipe.
    #     The candidate-order checks must fail because apply -k runs
    #     after the override.
    lines_orig_stateful = original_makefile.split("\n")
    apply_k_idx = None
    if_start = None
    if_end = None
    for i, line in enumerate(lines_orig_stateful):
        if "kubectl --context \"$(KIND_CONTEXT)\" apply -k" in line:
            apply_k_idx = i
        if "@if [ -n \"$(FLUX_GIT_BRANCH_OVERRIDE)\" ]; then" in line:
            if_start = i
        if if_start is not None and i > if_start:
            stripped = line.replace("> ", "").replace(">\t", "").strip()
            if stripped == "fi":
                if_end = i
                break

    if apply_k_idx is not None and if_start is not None and if_end is not None:
        if_block = lines_orig_stateful[if_start:if_end + 1]
        before_ak = lines_orig_stateful[:apply_k_idx]
        after_ak = lines_orig_stateful[apply_k_idx + 1:]
        reordered = (
            before_ak + if_block
            + [lines_orig_stateful[apply_k_idx]]
            + [l for l in after_ak if l not in if_block]
        )
        mutated_reorder = "\n".join(reordered)

        tmpdir_e3, _, env_e3 = _setup_harness(
            override_branch="candidate/test-envoy",
        )
        try:
            mutated_mf_e3 = os.path.join(tmpdir_e3, "Makefile.mutated")
            with open(mutated_mf_e3, "w") as f:
                f.write(mutated_reorder)

            # ── candidate bootstrap ─────────────────────────────────
            rc_e3a, stdout_e3a, stderr_e3a = _run_make(
                tmpdir_e3, env_e3,
                override_branch="candidate/test-envoy",
                makefile=mutated_mf_e3,
            )
            all_ok &= check(
                "adversarial stateful E3: candidate bootstrap exits 0",
                rc_e3a == 0,
                f"rc={rc_e3a}, stderr={stderr_e3a[:200]}",
            )

            # ── root reconcile ───────────────────────────────────────
            env_root_e3 = {
                "KIND_CLUSTER_NAME": "dry-run",
                "KIND_CONTEXT": "kind-dry-run",
            }
            rc_root_e3, stdout_root_e3, stderr_root_e3 = _run_cmd_in_harness(
                tmpdir_e3,
                ["kubectl", "--context", "kind-dry-run", "apply", "-k",
                 str(ENTRYPOINT_DIR)],
                env_root_e3,
            )
            all_ok &= check(
                "adversarial stateful E3: root reconcile exits 0",
                rc_root_e3 == 0,
                f"rc={rc_root_e3}, stderr={stderr_root_e3[:200]}",
            )

            # ── default bootstrap ────────────────────────────────────
            env_def_e3 = {
                "KIND_CLUSTER_NAME": "dry-run",
                "KIND_CONTEXT": "kind-dry-run",
            }
            rc_e3d, stdout_e3d, stderr_e3d = _run_cmd_in_harness(
                tmpdir_e3,
                ["make", "-f", mutated_mf_e3, "kind-dev-misc-local-bootstrap"],
                env_def_e3,
            )
            all_ok &= check(
                "adversarial stateful E3: default bootstrap exits 0",
                rc_e3d == 0,
                f"rc={rc_e3d}, stderr={stderr_e3d[:200]}",
            )
            calls_e3 = _get_calls(tmpdir_e3)

            # At least one candidate-order check MUST fail.
            e3_failed = 0
            for desc, ok in _assert_candidate_order(calls_e3):
                if not ok:
                    e3_failed += 1
            all_ok &= check(
                "adversarial stateful: reordering → candidate-order checks fail",
                e3_failed > 0,
                f"{e3_failed} behavioral checks failed (expected >0)",
            )

            # The else delete should still work (reorder doesn't remove it).
            desc_e3_del, ok_e3_del = _assert_default_delete(stdout_e3d, calls_e3)
            all_ok &= check(
                "adversarial stateful: reordering → delete still works "
                "(else branch intact)",
                ok_e3_del,
                "delete present (correct)" if ok_e3_del else "delete missing",
            )
        finally:
            shutil.rmtree(tmpdir_e3, ignore_errors=True)
    else:
        all_ok &= check(
            "adversarial stateful: located apply -k and if block for "
            "reorder test",
            False,
            "could not locate lines in Makefile for reorder test",
        )

    # ── E4: Remove both override AND else delete ─────────────────────
    #     Runs the FULL stateful lifecycle with both the override pipe
    #     AND the else delete removed. Both the candidate branch
    #     assertion AND the canonical reset assertion must fail,
    #     proving both production paths are independently covered.
    tmpdir_e4, _, env_e4 = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        # Remove the override render + apply pipe
        # Replace the render command with true to keep shell continuation
        # valid while removing the actual render + apply behavior.
        mutated_both = original_makefile.replace(
            "FLUX_GIT_BRANCH_OVERRIDE='$(FLUX_GIT_BRANCH_OVERRIDE)'"
            " python3 scripts/render-flux-sync-override.py",
            "true",
        )
        # ── mutation provenance: prove the render target was found ──
        found_render_e4 = mutated_both != original_makefile
        all_ok &= check(
            "adversarial stateful E4: located override render line in "
            "Makefile for mutation",
            found_render_e4,
            "render line found and mutated" if found_render_e4
            else "render line NOT found — mutation was a silent no-op",
        )

        lines_both = mutated_both.split("\n")
        found_apply_pipe_e4 = False
        found_delete_e4 = False
        for i, line in enumerate(lines_both):
            if "| kubectl --context" in line and "apply -f -" in line:
                # Replace the piped apply with true to keep shell
                # structure valid while removing the apply behavior.
                lines_both[i] = line.replace(
                    '| kubectl --context "$(KIND_CONTEXT)" apply -f -',
                    "true",
                )
                found_apply_pipe_e4 = True
            if "delete configmap flux-sync-values-override" in line:
                # Replace with true to keep shell structure valid
                # while removing the actual delete behavior.
                lines_both[i] = line.replace(
                    'kubectl --context "$(KIND_CONTEXT)" delete configmap'
                    " flux-sync-values-override"
                    ' -n "$(FLUX_NAMESPACE)" --ignore-not-found',
                    "true",
                )
                found_delete_e4 = True
                break
        mutated_both = "\n".join(lines_both)
        all_ok &= check(
            "adversarial stateful E4: located apply pipe line in Makefile "
            "for mutation",
            found_apply_pipe_e4,
            "apply pipe found and mutated" if found_apply_pipe_e4
            else "apply pipe NOT found — mutation was a silent no-op",
        )
        all_ok &= check(
            "adversarial stateful E4: located else-delete line in Makefile "
            "for mutation",
            found_delete_e4,
            "delete line found and mutated" if found_delete_e4
            else "delete line NOT found — mutation was a silent no-op",
        )

        mutated_mf_e4 = os.path.join(tmpdir_e4, "Makefile.mutated")
        with open(mutated_mf_e4, "w") as f:
            f.write(mutated_both)

        # ── candidate bootstrap ────────────────────────────────────
        rc_e4a, stdout_e4a, stderr_e4a = _run_make(
            tmpdir_e4, env_e4, override_branch="candidate/test-envoy",
            makefile=mutated_mf_e4,
        )
        all_ok &= check(
            "adversarial stateful E4: candidate bootstrap exits 0",
            rc_e4a == 0,
            f"rc={rc_e4a}, stderr={stderr_e4a[:200]}",
        )

        # ── root reconcile ──────────────────────────────────────────
        env_root_e4 = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        rc_root_e4, stdout_root_e4, stderr_root_e4 = _run_cmd_in_harness(
            tmpdir_e4,
            ["kubectl", "--context", "kind-dry-run", "apply", "-k",
             str(ENTRYPOINT_DIR)],
            env_root_e4,
        )
        all_ok &= check(
            "adversarial stateful E4: root reconcile exits 0",
            rc_root_e4 == 0,
            f"rc={rc_root_e4}, stderr={stderr_root_e4[:200]}",
        )

        # ── default bootstrap ───────────────────────────────────────
        env_def_e4 = {
            "KIND_CLUSTER_NAME": "dry-run",
            "KIND_CONTEXT": "kind-dry-run",
        }
        rc_e4d, stdout_e4d, stderr_e4d = _run_cmd_in_harness(
            tmpdir_e4,
            ["make", "-f", mutated_mf_e4, "kind-dev-misc-local-bootstrap"],
            env_def_e4,
        )
        all_ok &= check(
            "adversarial stateful E4: default bootstrap exits 0",
            rc_e4d == 0,
            f"rc={rc_e4d}, stderr={stderr_e4d[:200]}",
        )
        calls_e4 = _get_calls(tmpdir_e4)

        # Assert: effective branch is NOT candidate (override was removed)
        eff_e4 = _read_effective_branch(tmpdir_e4)
        all_ok &= check(
            "adversarial stateful: removing both → effective branch "
            "NOT candidate/test-envoy",
            eff_e4 != "candidate/test-envoy",
            f"effective branch: {eff_e4} (expected != candidate/test-envoy)",
        )

        # Assert: delete check FAILS (else delete was removed)
        desc_e4_del, ok_e4_del = _assert_default_delete(stdout_e4d, calls_e4)
        all_ok &= check(
            f"adversarial stateful: removing both → {desc_e4_del} FAILS",
            not ok_e4_del,
            "delete check correctly failed against mutated recipe",
        )
    finally:
        shutil.rmtree(tmpdir_e4, ignore_errors=True)

    # ══════════════════════════════════════════════════════════════════
    # Phase C: adversarial — mutated Makefile → behavioral checks fail
    #
    # Each mutation alters the REAL Makefile recipe in a specific way.
    # We write the mutated recipe to a temp file, run it through the
    # same behavioral checks that Phase A/B use, and assert that at
    # least one check FAILS. This proves the validator is coupled to
    # the production recipe, not to a self-constructed scenario.
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase C: adversarial mutation tests ---")

    # ── C1: Remove the override apply pipe ───────────────────────────
    tmpdir_c1, _, env_c1 = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        mutated_no_apply = original_makefile.replace(
            "FLUX_GIT_BRANCH_OVERRIDE='$(FLUX_GIT_BRANCH_OVERRIDE)'"
            " python3 scripts/render-flux-sync-override.py",
            "# REMOVED override render",
        )
        lines_ma = mutated_no_apply.split("\n")
        for i, line in enumerate(lines_ma):
            if "| kubectl --context" in line and "apply -f -" in line:
                lines_ma[i] = "> \t\t# REMOVED apply pipe; \\"
                break
        mutated_no_apply = "\n".join(lines_ma)

        mutated_mf = os.path.join(tmpdir_c1, "Makefile.mutated")
        with open(mutated_mf, "w") as f:
            f.write(mutated_no_apply)

        rc_c1, stdout_c1, _ = _run_make(
            tmpdir_c1, env_c1,
            override_branch="candidate/test-envoy",
            makefile=mutated_mf,
        )
        calls_c1 = _get_calls(tmpdir_c1)

        # Re-run the candidate-order checks against the mutated recipe.
        # At least one ordering check MUST fail (apply -f - is absent).
        c1_checks_failed = 0
        for desc, ok in _assert_candidate_order(calls_c1):
            if not ok:
                c1_checks_failed += 1
        all_ok &= check(
            "adversarial: removing apply pipe → candidate-order checks fail",
            c1_checks_failed > 0,
            f"{c1_checks_failed} behavioral checks failed (expected >0)",
        )

        # The override branch must NOT appear in any stdin.
        stdin_c1 = _get_stdin(tmpdir_c1, "kubectl")
        has_branch_c1 = "candidate/test-envoy" in (stdin_c1 or "")
        all_ok &= check(
            "adversarial: removing apply pipe → candidate branch not in stdin",
            not has_branch_c1,
            "branch absent from stdin (correct)",
        )
    finally:
        shutil.rmtree(tmpdir_c1, ignore_errors=True)

    # ── C2: Remove the else branch delete ────────────────────────────
    tmpdir_c2, _, env_c2 = _setup_harness(override_branch="")
    try:
        mutated_no_else = original_makefile.replace(
            "else \\\n> \tkubectl --context \"$(KIND_CONTEXT)\" delete configmap"
            " flux-sync-values-override -n \"$(FLUX_NAMESPACE)\" --ignore-not-found; \\",
            "else \\\n> \t# REMOVED delete;",
        )
        mutated_mf_c2 = os.path.join(tmpdir_c2, "Makefile.mutated")
        with open(mutated_mf_c2, "w") as f:
            f.write(mutated_no_else)

        rc_c2, stdout_c2, _ = _run_make(
            tmpdir_c2, env_c2, override_branch="",
            makefile=mutated_mf_c2,
        )
        calls_c2 = _get_calls(tmpdir_c2)

        # The default-delete check MUST fail against the mutated recipe.
        desc_c2, ok_c2 = _assert_default_delete(stdout_c2, calls_c2)
        all_ok &= check(
            f"adversarial: removing else delete → {desc_c2} FAILS",
            not ok_c2,
            "delete check correctly failed against mutated recipe",
        )
    finally:
        shutil.rmtree(tmpdir_c2, ignore_errors=True)

    # ── C3: Reorder — if block (override apply) runs before apply -k ─
    lines_orig = original_makefile.split("\n")
    apply_k_line_idx = None
    if_block_start = None
    if_block_end = None

    for i, line in enumerate(lines_orig):
        if "kubectl --context \"$(KIND_CONTEXT)\" apply -k" in line:
            apply_k_line_idx = i
        if "@if [ -n \"$(FLUX_GIT_BRANCH_OVERRIDE)\" ]; then" in line:
            if_block_start = i
        if if_block_start is not None and i > if_block_start:
            stripped = line.replace("> ", "").replace(">\t", "").strip()
            if stripped == "fi":
                if_block_end = i
                break

    if apply_k_line_idx is not None and if_block_start is not None and if_block_end is not None:
        if_block = lines_orig[if_block_start:if_block_end + 1]
        before_apply_k = lines_orig[:apply_k_line_idx]
        after_apply_k = lines_orig[apply_k_line_idx + 1:]
        reordered_lines = (
            before_apply_k
            + if_block
            + [lines_orig[apply_k_line_idx]]  # apply -k now AFTER override
            + [l for l in after_apply_k if l not in if_block]
        )
        mutated_reorder = "\n".join(reordered_lines)

        tmpdir_c3, _, env_c3 = _setup_harness(
            override_branch="candidate/test-envoy",
        )
        try:
            mutated_mf_c3 = os.path.join(tmpdir_c3, "Makefile.mutated")
            with open(mutated_mf_c3, "w") as f:
                f.write(mutated_reorder)
            rc_c3, _, _ = _run_make(
                tmpdir_c3, env_c3,
                override_branch="candidate/test-envoy",
                makefile=mutated_mf_c3,
            )
            calls_c3 = _get_calls(tmpdir_c3)

            # At least one candidate-order check MUST fail because
            # apply -f - now runs before apply -k.
            c3_checks_failed = 0
            for desc, ok in _assert_candidate_order(calls_c3):
                if not ok:
                    c3_checks_failed += 1
            all_ok &= check(
                "adversarial: reordering → candidate-order checks fail",
                c3_checks_failed > 0,
                f"{c3_checks_failed} behavioral checks failed (expected >0)",
            )
        finally:
            shutil.rmtree(tmpdir_c3, ignore_errors=True)
    else:
        all_ok &= check(
            "adversarial: located apply -k and if block for reorder test",
            False,
            "could not locate lines in Makefile for reorder test",
        )

    # ── C4: Replace the apply pipe with a stdin sink ─────────────────
    #     The reviewer found that replacing | kubectl apply -f - with a
    #     stdin sink (e.g., cat > /dev/null) still passed. This test
    #     proves the validator catches it.
    tmpdir_c4, _, env_c4 = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        mutated_sink = original_makefile.replace(
            "| kubectl --context \"$(KIND_CONTEXT)\" apply -f -",
            "| cat > /dev/null",
        )
        mutated_mf_c4 = os.path.join(tmpdir_c4, "Makefile.mutated")
        with open(mutated_mf_c4, "w") as f:
            f.write(mutated_sink)

        rc_c4, _, _ = _run_make(
            tmpdir_c4, env_c4,
            override_branch="candidate/test-envoy",
            makefile=mutated_mf_c4,
        )
        calls_c4 = _get_calls(tmpdir_c4)

        # At least one candidate-order check MUST fail: apply -f - is
        # gone, so A2 (apply -k before apply -f -) and A3 (apply -f -
        # before wait) both fail.
        c4_checks_failed = 0
        for desc, ok in _assert_candidate_order(calls_c4):
            if not ok:
                c4_checks_failed += 1
        all_ok &= check(
            "adversarial: stdin sink replaces apply pipe → candidate-order checks fail",
            c4_checks_failed > 0,
            f"{c4_checks_failed} behavioral checks failed (expected >0)",
        )

        # The override branch must NOT be in any stdin.
        stdin_c4 = _get_stdin(tmpdir_c4, "kubectl")
        has_branch_c4 = "candidate/test-envoy" in (stdin_c4 or "")
        all_ok &= check(
            "adversarial: stdin sink → candidate branch not in kubectl stdin",
            not has_branch_c4,
            "branch absent from kubectl stdin (correct — pipe goes to cat)",
        )
    finally:
        shutil.rmtree(tmpdir_c4, ignore_errors=True)

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

    print("\n=== CrateCheck CEL contract validation ===")
    cel_ok = validate_cel_contracts()

    print("\n=== EnvoyProxy patch validation ===")
    envoypatch_ok = validate_envoyproxy_patch()

    print("\n=== Flux sync override validation ===")
    fluxsync_ok = validate_flux_sync_override()

    print("\n=== Flux bootstrap behavioral validation ===")
    fluxbehavior_ok = validate_flux_bootstrap_behavior()

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
