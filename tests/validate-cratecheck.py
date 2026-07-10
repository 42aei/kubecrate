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
