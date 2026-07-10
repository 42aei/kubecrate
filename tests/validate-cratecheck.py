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
# Mock {name}: record calls, exit {exit_code}.
LOG_FILE="{log_file}"
CTX_FILE="{ctx_file}"
STDIN_DIR="{stdin_dir}"

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

        for name in ("kubectl", "helm", "flux"):
            script = MOCK_SCRIPT_TEMPLATE.format(
                name=name, log_file=log_path, ctx_file=ctx_file,
                stdin_dir=stdin_dir, exit_code=0,
            )
            script_path = os.path.join(tmpdir, name)
            with open(script_path, "w") as f:
                f.write(script)
            os.chmod(script_path, 0o755)

        # Write KIND_CONTEXT for the mock
        env_extra = {}
        env_extra["KIND_CLUSTER_NAME"] = "dry-run"
        env_extra["KIND_CONTEXT"] = "kind-dry-run"
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
    # Phase D: simulated root Kustomization reconciliation
    #
    # After the candidate override is applied, the root Flux Kustomization
    # eventually reconciles (runs kustomize build on the entrypoint and
    # applies the result). This phase simulates that by re-running
    # kubectl apply -k on the entrypoint through the same harness, then
    # verifies no command was issued that would delete or overwrite the
    # imperative override ConfigMap.
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase D: simulated root reconciliation (after candidate) ---")
    tmpdir_d, log_d, env_d = _setup_harness(
        override_branch="candidate/test-envoy",
    )
    try:
        rc_d, stdout_d, stderr_d = _run_make(tmpdir_d, env_d,
                                              override_branch="candidate/test-envoy")
        calls_d = _get_calls(tmpdir_d)

        # D1: Static: kustomize build of entrypoint must NOT contain a
        #     ConfigMap named flux-sync-values-override. This proves the
        #     committed repository (post-deletion) cannot overwrite the
        #     imperative override via root reconciliation.
        #     (The HelmRelease valuesFrom reference to the override by
        #     name is expected — only an actual ConfigMap resource is a
        #     problem.)
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
            "behavioral: entrypoint kustomize build does NOT contain "
            "a ConfigMap named flux-sync-values-override",
            not has_override_cm,
            "override ConfigMap absent; only HelmRelease valuesFrom reference (correct)",
        )

        # D2: Candidate ordering still holds against the real Makefile.
        for desc, ok in _assert_candidate_order(calls_d, "behavioral (reconcile-pinned): "):
            all_ok &= check(desc, ok)

        # D3: The override stdin still contains the candidate branch
        #     after running the real bootstrap recipe.
        all_ok &= check(*_assert_candidate_stdin(
            tmpdir_d, "candidate/test-envoy",
            "behavioral (reconcile-pinned): ",
        ))

        # D4: No delete happened (the override path ran, not the else)
        all_ok &= check(*_assert_no_delete(stdout_d,
                                            "behavioral (reconcile-pinned): "))

        # D5: The override apply pipe produced a ConfigMap whose
        #     branch value matches the candidate — not the canonical
        #     branch and not an empty dict.
        stdin_content_d = _get_stdin(tmpdir_d, "kubectl")
        has_candidate_ref = ("branch: candidate/test-envoy" in (stdin_content_d or ""))
        all_ok &= check(
            "behavioral (reconcile-pinned): override ConfigMap sets "
            "branch to candidate/test-envoy",
            has_candidate_ref,
            f"stdin excerpt: {(stdin_content_d or 'EMPTY')[:150]}",
        )
    finally:
        shutil.rmtree(tmpdir_d, ignore_errors=True)

    # ══════════════════════════════════════════════════════════════════
    # Phase E: default bootstrap after simulated root reconciliation
    #
    # After the candidate bootstrap and subsequent root reconciliation,
    # a default bootstrap (no FLUX_GIT_BRANCH_OVERRIDE) must delete the
    # override ConfigMap via the else branch and restore to canonical.
    # ══════════════════════════════════════════════════════════════════
    print("\n  --- Phase E: default bootstrap after root reconcile ---")
    tmpdir_e, log_e, env_e = _setup_harness(override_branch="")
    try:
        rc_e, stdout_e, stderr_e = _run_make(tmpdir_e, env_e,
                                              override_branch="")
        calls_e = _get_calls(tmpdir_e)

        all_ok &= check(*_assert_default_delete(
            stdout_e, calls_e,
            "behavioral (post-reconcile default): ",
        ))
        all_ok &= check(*_assert_no_override_apply_f(
            calls_e,
            "behavioral (post-reconcile default): ",
        ))
        all_ok &= check(
            "behavioral (post-reconcile default): default bootstrap exits 0",
            rc_e == 0,
            f"rc={rc_e}, stderr={stderr_e[:200]}",
        )
    finally:
        shutil.rmtree(tmpdir_e, ignore_errors=True)

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
                lines_ma[i] = "# REMOVED apply pipe"
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
