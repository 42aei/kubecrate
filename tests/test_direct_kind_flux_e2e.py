#!/usr/bin/env python3
"""Focused tests for the direct kind+Flux E2E runner."""

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "direct-kind-flux-e2e.sh"
RENDERER = ROOT / "scripts" / "render-direct-flux-source.py"
HELPER = ROOT / "scripts" / "final_qa_helpers.py"

EXPECTED_COMMIT = "3cfb4e320eff8d2a738cb36fd2420862b1db45c3"
PR_BRANCH = "kubecrate/cratecheck-restack-eso"


def test_runner_uses_short_bounded_observation_waits() -> None:
    runner = RUNNER.read_text()
    assert runner.count('sleep "${KUBECRATE_E2E_OBSERVE_SECONDS:-3}"') == 3
    assert 'KUBECRATE_E2E_OBSERVE_SECONDS:-35' not in runner


def init_repo(path: Path, content: str) -> str:
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "e2e@test"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "E2E"], check=True)
    (path / "tracked").write_text(content)
    subprocess.run(["git", "-C", path, "add", "."], check=True)
    subprocess.run(["git", "-C", path, "commit", "-qm", content], check=True)
    return subprocess.check_output(
        ["git", "-C", path, "rev-parse", "HEAD"], text=True
    ).strip()


def fake_command(bindir: Path, name: str, script: str) -> Path:
    path = bindir / name
    path.write_text(f"#!/usr/bin/env bash\n{script}\n")
    path.chmod(0o755)
    return path


# ── Shell syntax ─────────────────────────────────────────────────────────────

def test_runner_is_executable_and_syntax_valid() -> None:
    assert RUNNER.stat().st_mode & 0o111
    assert subprocess.run(["bash", "-n", str(RUNNER)]).returncode == 0


def test_renderer_is_executable_and_syntax_valid() -> None:
    assert RENDERER.stat().st_mode & 0o111
    assert subprocess.run(["python3", "-m", "py_compile", str(RENDERER)]).returncode == 0


# ── Revision mismatch ────────────────────────────────────────────────────────

def test_revision_mismatch_fails_before_cluster_creation(tmp_path: Path) -> None:
    """Runner fails when remote branch SHA differs from expected."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    init_repo(repo, "mismatch")

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    # git ls-remote returns a wrong SHA.
    fake_command(bindir, "git", f'''echo "git $*" >>"{log}"
if [[ "$*" == *"ls-remote"* ]]; then
  echo "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb {PR_BRANCH}"
  exit 0
fi
exec /usr/bin/git "$@"''')
    # gh must output a valid token and PR head for preflight to reach the ls-remote check.
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth token"* ]]; then printf 'dummy-token'; exit 0
elif [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0
elif [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0
fi
exit 0''')
    for name in ("kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, result.stderr
    stderr = result.stderr
    assert "SHA" in stderr and "!=" in stderr, stderr
    calls = log.read_text() if log.exists() else ""
    assert "create cluster" not in calls, "must not create cluster after revision mismatch"


# ── Shared/wrong context refusal ─────────────────────────────────────────────

def test_shared_cluster_name_refused_before_mutation() -> None:
    """Runner has guards that refuse known shared cluster names."""
    text = RUNNER.read_text()
    # Verify the guard exists in the code.
    assert "kind-dev-misc-local|kubecrate-fix-eso" in text, \
        "missing shared cluster name guard"
    assert "refusing shared cluster" in text
    # Guard placement: after cluster name is computed, before kind create.
    case_pos = text.index("kind-dev-misc-local|kubecrate-fix-eso")
    kind_create_pos = text.index("kind create cluster")
    assert case_pos < kind_create_pos, "shared cluster guard must precede kind create"


# ── Credential sentinel non-leakage ──────────────────────────────────────────

_SENTINEL_TOKEN = "ghp_testSentinelToken1234567890abc"

def test_token_never_appears_in_stdout_stderr_or_log(tmp_path: Path) -> None:
    """Token is never leaked to stdout, stderr, or command logs."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")

    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")

    init_repo(repo, "token-leak")

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == "auth token" ]]; then printf '%s' '{_SENTINEL_TOKEN}'; exit 0
elif [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0
elif [[ "$*" == *"api"* ]]; then echo '{{"head":{{"sha":"{EXPECTED_COMMIT}"}}}}'; exit 0
fi
exit 0''')
    fake_command(bindir, "git", f'''echo "git $*" >>"{log}"
if [[ "$*" == *"ls-remote"* ]]; then echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0; fi
exec /usr/bin/git "$@"''')
    for name in ("kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)

    calls = log.read_text() if log.exists() else ""
    combined = result.stdout + result.stderr + calls
    assert _SENTINEL_TOKEN not in combined, "token leaked in output or logs"


# ── Renderer correctness ─────────────────────────────────────────────────────

def test_renderer_replaces_ssh_with_https() -> None:
    """Renderer substitutes SSH URL with HTTPS and disables SSH key generation."""
    input_yaml = """apiVersion: v1
kind: ConfigMap
metadata:
  name: flux-sync-values
  namespace: flux-system
data:
  values.yaml: |
    secret:
      create: true
      generate:
        sshKeyAlgorithm: ed25519
    gitRepository:
      spec:
        url: ssh://git@github.com/42aei/kubecrate.git
        interval: 1m
        ref:
          branch: kubecrate/cratecheck-restack-eso
    kustomization:
      spec:
        interval: 1m
        path: ./clusters/kind-dev-misc-local/entrypoint
        prune: true
"""
    result = subprocess.run(
        ["python3", str(RENDERER), "--https-url", "https://github.com/42aei/kubecrate.git"],
        input=input_yaml, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr

    output = result.stdout
    assert "ssh://" not in output
    assert "https://github.com/42aei/kubecrate.git" in output
    assert "create: true" not in output
    assert "create: false" in output
    assert "sshKeyAlgorithm" not in output
    assert "secretRef" in output


def test_renderer_rejects_missing_or_multiple_configmaps() -> None:
    """Renderer fails on zero or multiple flux-sync-values ConfigMaps."""
    result = subprocess.run(
        ["python3", str(RENDERER), "--https-url", "https://example.com"],
        input="apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: other\n",
        text=True, capture_output=True, timeout=10)
    assert result.returncode != 0

    cm = """apiVersion: v1
kind: ConfigMap
metadata:
  name: flux-sync-values
  namespace: flux-system
data:
  values.yaml: "{}"
"""
    result = subprocess.run(
        ["python3", str(RENDERER), "--https-url", "https://example.com"],
        input=cm + "\n---\n" + cm, text=True, capture_output=True, timeout=10)
    assert result.returncode != 0


# ── Runner context guard ─────────────────────────────────────────────────────

def test_runner_assert_context_before_every_mutation() -> None:
    """Every mutation command is preceded by an explicit context guard."""
    text = RUNNER.read_text()
    assert_contexts = text.count("assert_context")
    assert assert_contexts >= 6, f"expected at least 6 assert_context calls, got {assert_contexts}"

    # Find the main-flow mutation section (after "Flux Bootstrap" header).
    main_start = text.index("# ── Flux Bootstrap")
    main_text = text[main_start:]

    for fragment in (
        "helm upgrade --install flux-system",
        "kubectl --context \"${CONTEXT}\" apply -f -",
        "flux --context \"${CONTEXT}\" reconcile source git",
        "flux --context \"${CONTEXT}\" reconcile kustomization \"${SYNC_NAME}\"",
    ):
        position = main_text.index(fragment)
        preceding = main_text[max(0, position - 600):position]
        assert "assert_context" in preceding, f"no assert_context before {fragment[:50]}"

    # Also verify the controlled-red mutations.
    assert 'assert_context\nflux --context "${CONTEXT}" suspend kustomization' in text
    assert 'assert_context\nkubectl --context "${CONTEXT}" delete secret' in text

    assert '--kube-context "${CONTEXT}"' in text


# ── Cleanup trap ─────────────────────────────────────────────────────────────

def test_cleanup_trap_installed_and_restores_before_cluster_delete() -> None:
    """Cleanup trap is installed, restores before deleting, and verifies absence."""
    text = RUNNER.read_text()

    assert "trap cleanup EXIT" in text
    assert "trap 'exit 130' INT" in text
    assert "trap 'exit 143' TERM" in text

    cleanup_func = text[text.index("cleanup()"):text.index("cluster_state()")]
    assert "resume kustomization external-secrets-operator-smoke" in cleanup_func
    assert "kind delete cluster" in cleanup_func
    assert 'test "$(cluster_state)" = absent' in cleanup_func

    assert "RED_STATE=restore_required" in text
    assert "RED_STATE=none" in text


# ── Runner preflight ordering ────────────────────────────────────────────────

def test_preflight_checks_precede_cluster_creation() -> None:
    """Required preflight checks all run before kind create cluster."""
    text = RUNNER.read_text()
    preflight_tokens = [
        "gh auth status",
        "gh api user",
        "gh auth token",
        "git ls-remote",
        "gh api",
        "git diff --quiet",
    ]
    kind_create_pos = text.index("kind create cluster")
    for token in preflight_tokens:
        pos = text.index(token)
        assert pos < kind_create_pos, f"{token} must precede kind create cluster"


# ── ESO projected value assertion ────────────────────────────────────────────

def run_decode_smoke_value(tmp_path: Path, encoded: str) -> subprocess.CompletedProcess[str]:
    """Execute the runner's real decode helper with a faithful kubectl response."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    fake_command(bindir, "kubectl", f"printf '%s' '{encoded}'")
    helper_source = RUNNER.read_text().split("# ── Preflight", 1)[0]
    script = helper_source + "\nCONTEXT=kind-test\ndecode_smoke_value eso-smoke-projected\n"
    return subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
        text=True, capture_output=True, timeout=10)


def test_decode_smoke_value_accepts_canonical_base64(tmp_path: Path) -> None:
    encoded = base64.b64encode(b"kubecrate-eso-smoke-ok").decode()
    result = run_decode_smoke_value(tmp_path, encoded)
    assert result.returncode == 0, result.stderr
    assert encoded not in result.stdout + result.stderr
    assert "kubecrate-eso-smoke-ok" not in result.stdout + result.stderr


def test_decode_smoke_value_rejects_noncanonical_pad_bits(tmp_path: Path) -> None:
    canonical = base64.b64encode(b"kubecrate-eso-smoke-ok").decode()
    noncanonical = "a3ViZWNyYXRlLWVzby1zbW9rZS1vax=="
    assert noncanonical != canonical
    assert base64.b64decode(noncanonical) == base64.b64decode(canonical)

    result = run_decode_smoke_value(tmp_path, noncanonical)
    assert result.returncode != 0
    assert "not canonical base64" in result.stderr
    assert noncanonical not in result.stdout + result.stderr
    assert "kubecrate-eso-smoke-ok" not in result.stdout + result.stderr


def test_projected_secret_value_check_is_strict() -> None:
    """Runner uses decode_smoke_value helper with strict base64 and exact value checks."""
    text = RUNNER.read_text()
    assert "kubecrate-eso-smoke-ok" in text
    # The strict helper replaces inline pipelines; verify its error messages exist.
    assert "value not valid base64" in text
    assert "could not decode" in text
    assert "Secret value mismatch" in text
    # Old loose pipelines must be gone.
    assert "base64 -d 2>/dev/null || true" not in text
    # Both projected and restored paths use the helper.
    assert text.count("decode_smoke_value eso-smoke-projected") == 2


# ── Interrupt cleanup test ───────────────────────────────────────────────────

def test_interrupt_handlers_are_trapped(tmp_path: Path) -> None:
    """SIGINT triggers cleanup that deletes the cluster."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "interrupt")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    deleted = tmp_path / "cluster-deleted"
    barrier = tmp_path / "barrier"
    cluster_created = tmp_path / "cluster-created"
    cluster_name_file = tmp_path / "cluster-name"

    # Single dispatch script for all commands.  Hang on helm --install to keep
    # the runner alive until we signal it.
    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 0
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{cluster_name_file}" && test -f "{cluster_created}" && test ! -f "{deleted}"; then
      cat "{cluster_name_file}"
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then touch "{deleted}"; exit 0; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
elif [[ $name == helm ]]; then
  if [[ "$*" == *"--install"* ]]; then touch "{barrier}"; while :; do sleep 1; done; fi
  exit 0
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}

    process = subprocess.Popen(
        [str(RUNNER)], cwd=repo, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    # Wait for the helm install barrier.
    deadline = time.monotonic() + 15
    while not barrier.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)

    if process.poll() is not None:
        stdout, stderr = process.communicate(timeout=2)
        calls = log.read_text() if log.exists() else ""
        raise AssertionError(
            f"runner exited before helm install (rc={process.returncode})\n"
            f"stdout={stdout}\nstderr={stderr}\ncalls={calls}")

    if not barrier.exists():
        stdout, stderr = process.communicate(timeout=2)
        calls = log.read_text() if log.exists() else ""
        raise AssertionError(
            f"helm --install barrier not reached within deadline\n"
            f"stdout={stdout}\nstderr={stderr}\ncalls={calls}")

    os.killpg(process.pid, 2)  # SIGINT
    stdout, stderr = process.communicate(timeout=10)

    assert deleted.exists(), (
        f"cluster was not deleted on interrupt (rc={process.returncode})\n"
        f"stdout={stdout}\nstderr={stderr}\n"
        f"calls={log.read_text() if log.exists() else ''}")


# ── Renderer smoke with kustomize output ─────────────────────────────────────

def test_renderer_handles_full_kustomize_pipeline(tmp_path: Path) -> None:
    """Integration: kustomize build + renderer works end-to-end."""
    if not shutil.which("kustomize"):
        pytest.skip("kustomize not installed")
    base = tmp_path / "render-test"; base.mkdir()
    (base / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - cm.yaml\n")
    (base / "cm.yaml").write_text("""apiVersion: v1
kind: ConfigMap
metadata:
  name: flux-sync-values
  namespace: flux-system
data:
  values.yaml: |
    secret:
      create: true
    gitRepository:
      spec:
        url: ssh://git@github.com/42aei/kubecrate.git
        ref:
          branch: kubecrate/cratecheck-restack-eso
    kustomization:
      spec:
        path: ./clusters/kind-dev-misc-local/entrypoint
""")
    result = subprocess.run(
        ["bash", "-c",
         f"kustomize build {base} | python3 {RENDERER} --https-url https://github.com/42aei/kubecrate.git"],
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "https://github.com/42aei/kubecrate.git" in result.stdout
    assert "ssh://" not in result.stdout
    assert "secretRef" in result.stdout


# ── Readiness failure ─────────────────────────────────────────────────────────

def test_eso_readiness_gate_targets_rendered_deployment(tmp_path: Path) -> None:
    """The shipped readiness commands wait for the Helm release's Deployment name."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "kubectl.log"
    fake_command(bindir, "kubectl", f'''echo "$*" >>"{log}"
if [[ "$*" == *"config current-context"* ]]; then printf 'kind-test'; fi
exit 0''')
    text = RUNNER.read_text()
    readiness = text.split("# Wait for ESO and CrateCheck deployments.", 1)[1].split(
        "# ── ESO Validation", 1)[0]
    script = "set -Eeuo pipefail\nCONTEXT=kind-test\n" + (
        "fail() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
        "assert_context() { actual=\"$(kubectl config current-context)\"; "
        "test \"${actual}\" = \"${CONTEXT}\" || fail wrong-context; }\n"
    ) + readiness
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "deployment/external-secrets " in calls
    assert "deployment/external-secrets-operator" not in calls


def test_readiness_failure_exits_nonzero_and_cleanup_runs(tmp_path: Path) -> None:
    """Runner exits non-zero when a required workload never becomes Ready."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "readiness-fail")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    deleted = tmp_path / "cluster-deleted"
    cluster_name_file = tmp_path / "cluster-name"
    cluster_created = tmp_path / "cluster-created"
    kubectl_wait_count = tmp_path / "kubectl-wait-count"

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 0
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{cluster_name_file}" && test -f "{cluster_created}" && test ! -f "{deleted}"; then
      cat "{cluster_name_file}"
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then touch "{deleted}"; exit 0; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  if [[ "$*" == *" wait "* ]] || [[ "$*" == *" wait" ]]; then
    count=$(test -f "{kubectl_wait_count}" && cat "{kubectl_wait_count}" || echo 0)
    echo $((count + 1)) >"{kubectl_wait_count}"
    if test $count -ge 4; then exit 1; fi
    exit 0
  fi
  exit 0
elif [[ $name == flux ]]; then
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner should fail on readiness timeout (rc={result.returncode})"
    assert deleted.exists(), "cluster must be deleted after readiness failure"


# ── Cleanup failure ──────────────────────────────────────────────────────────

def test_cleanup_failure_exits_nonzero_when_cluster_remains(tmp_path: Path) -> None:
    """Runner exits non-zero when kind delete fails and cluster is still present."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "cleanup-fail")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    deleted = tmp_path / "cluster-deleted"
    cluster_name_file = tmp_path / "cluster-name"
    cluster_created = tmp_path / "cluster-created"
    exit_early = tmp_path / "exit-early"

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 0
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{exit_early}"; then
      if test -f "{cluster_name_file}" && test -f "{cluster_created}"; then
        cat "{cluster_name_file}"
      fi
      exit 0
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then touch "{deleted}"; exit 0; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  exit 0
elif [[ $name == helm ]]; then
  if [[ "$*" == *"--install"* ]]; then touch "{exit_early}"; exit 1; fi
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner should fail when cleanup leaves cluster present (rc={result.returncode})"
    stderr = result.stderr
    assert "cleanup verification failed" in stderr, f"expected cleanup failure message, got: {stderr}"
    assert deleted.exists(), "kind delete was called (even though cleanup still fails)"


# ── Fix 1: Partial-create cleanup ────────────────────────────────────────────

def test_partial_create_cleanup_deletes_exact_name(tmp_path: Path) -> None:
    """Partial-create: kind exits non-zero but cluster listed; cleanup deletes exact name."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "partial-create")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    deleted = tmp_path / "cluster-deleted"
    cluster_name_file = tmp_path / "cluster-name"
    cluster_created = tmp_path / "cluster-created"

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 1
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{cluster_created}" && test ! -f "{deleted}"; then
      cat "{cluster_name_file}"
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then
    touch "{deleted}"
    exit 0
  fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must exit non-zero on partial create (rc={result.returncode})"
    assert deleted.exists(), "cleanup must delete cluster after partial create"


# ── Fix 2: Strict base64 decode ──────────────────────────────────────────────

def test_decode_smoke_value_validates_base64_and_exact_value() -> None:
    """decode_smoke_value uses canonical base64 regex and exact value check."""
    text = RUNNER.read_text()
    # Verify the helper exists and contains all validation steps.
    assert "decode_smoke_value()" in text
    assert 'test "${decoded}" = "kubecrate-eso-smoke-ok"' in text
    assert '[[ "${encoded}" =~ ^[A-Za-z0-9+/]*={0,2}$ ]]' in text
    assert "value not valid base64" in text
    assert "could not decode" in text
    assert "smoke-test field empty" in text
    # Verify no raw base64 -d with || true remains.
    assert "base64 -d 2>/dev/null || true" not in text, "loose base64 decode with || true still present"
    # Both projected and restored checks call the helper exactly twice.
    assert text.count("decode_smoke_value eso-smoke-projected") == 2


def test_malformed_base64_decode_fails_at_projected_check(tmp_path: Path) -> None:
    """Runner fails when projected Secret contains non-base64 characters."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "malformed-b64")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    cluster_name_file = tmp_path / "cluster-name"
    deleted = tmp_path / "cluster-deleted"
    cluster_created = tmp_path / "cluster-created"

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 0
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{cluster_name_file}" && test -f "{cluster_created}" && test ! -f "{deleted}"; then
      cat "{cluster_name_file}"
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then touch "{deleted}"; exit 0; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  if [[ "$*" == *"get gitrepository"* ]]; then
    printf 'main@sha1:%s' '{EXPECTED_COMMIT}'; exit 0
  fi
  if [[ "$*" == *"get secret eso-smoke-projected"* ]]; then
    printf '!!!not!valid!base64!!!'; exit 0
  fi
  if [[ "$*" == *"apply -f -"* ]]; then cat >/dev/null; exit 0; fi
  exit 0
elif [[ $name == helm ]]; then exit 0
elif [[ $name == flux ]]; then exit 0
elif [[ $name == kustomize ]]; then
  echo "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: flux-sync-values\n  namespace: flux-system\ndata:\n  values.yaml: |\n    secret:\n      create: true\n    gitRepository:\n      spec:\n        url: ssh://git@github.com/42aei/kubecrate.git\n    kustomization:\n      spec:\n        path: ./clusters/kind-dev-misc-local/entrypoint"
  exit 0
elif [[ $name == python3 ]]; then
  exec "{shutil.which('python3')}" "$@"
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must fail on malformed base64 (rc={result.returncode})"
    assert "not valid base64" in result.stderr, f"expected base64 validation failure, got: {result.stderr}"


def test_wrong_base64_value_fails_at_projected_check(tmp_path: Path) -> None:
    """Runner fails when projected Secret decodes to wrong value."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "wrong-value")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    cluster_name_file = tmp_path / "cluster-name"
    deleted = tmp_path / "cluster-deleted"
    cluster_created = tmp_path / "cluster-created"
    wrong_b64 = base64.b64encode(b"wrong-secret-value").decode()

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 0
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{cluster_name_file}" && test -f "{cluster_created}" && test ! -f "{deleted}"; then
      cat "{cluster_name_file}"
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then touch "{deleted}"; exit 0; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  if [[ "$*" == *"get gitrepository"* ]]; then
    printf 'main@sha1:%s' '{EXPECTED_COMMIT}'; exit 0
  fi
  if [[ "$*" == *"get secret eso-smoke-projected"* ]]; then
    printf '%s' '{wrong_b64}'; exit 0
  fi
  if [[ "$*" == *"apply -f -"* ]]; then cat >/dev/null; exit 0; fi
  exit 0
elif [[ $name == helm ]]; then exit 0
elif [[ $name == flux ]]; then exit 0
elif [[ $name == kustomize ]]; then
  echo "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: flux-sync-values\n  namespace: flux-system\ndata:\n  values.yaml: |\n    secret:\n      create: true\n    gitRepository:\n      spec:\n        url: ssh://git@github.com/42aei/kubecrate.git\n    kustomization:\n      spec:\n        path: ./clusters/kind-dev-misc-local/entrypoint"
  exit 0
elif [[ $name == python3 ]]; then
  exec "{shutil.which('python3')}" "$@"
elif [[ $name == base64 ]]; then
  exec /usr/bin/base64 "$@"
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must fail on wrong decoded value (rc={result.returncode})"
    assert "Secret value mismatch" in result.stderr, f"expected value mismatch, got: {result.stderr}"


# ── Fix 3: Identity guard ────────────────────────────────────────────────────

def test_identity_guard_rejects_wrong_user(tmp_path: Path) -> None:
    """Runner fails before cluster creation when active user is not faksibot."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    init_repo(repo, "wrong-user")

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'octocat'; exit 0
fi
exit 0''')
    for name in ("git", "kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must fail on wrong user (rc={result.returncode})"
    assert "expected faksibot" in result.stderr, f"expected identity rejection, got: {result.stderr}"
    calls = log.read_text() if log.exists() else ""
    assert "create cluster" not in calls, "must not create cluster for wrong user"


def test_identity_guard_rejects_empty_user(tmp_path: Path) -> None:
    """Runner fails when gh api user returns empty string."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    init_repo(repo, "empty-user")

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf ''; exit 0
fi
exit 0''')
    for name in ("git", "kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must fail on empty user (rc={result.returncode})"
    assert "expected faksibot" in result.stderr, f"expected identity rejection, got: {result.stderr}"
    calls = log.read_text() if log.exists() else ""
    assert "auth token" not in calls, "must not retrieve token for empty user"


def test_identity_guard_rejects_api_failure(tmp_path: Path) -> None:
    """Runner fails when gh api user command exits non-zero."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    init_repo(repo, "api-fail")

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then exit 1
fi
exit 0''')
    for name in ("git", "kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must fail on API failure (rc={result.returncode})"
    stderr = result.stderr
    assert "expected faksibot" in stderr, f"expected identity rejection for API failure, got: {stderr}"
    calls = log.read_text() if log.exists() else ""
    assert "auth token" not in calls, "must not retrieve token after API failure"


# ── Fix 4: ESO deployment wait propagation ───────────────────────────────────

def test_eso_deployment_wait_failure_propagates(tmp_path: Path) -> None:
    """ESO deployment wait failure propagates non-zero (no || true)."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for d in ("kind", "clusters/kind-dev-misc-local/platform-services/flux",
              "clusters/kind-dev-misc-local/entrypoint"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    (repo / "clusters/kind-dev-misc-local/entrypoint/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n"
        "  - ../platform-services/flux\n")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
    init_repo(repo, "eso-wait-fail")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    deleted = tmp_path / "cluster-deleted"
    cluster_name_file = tmp_path / "cluster-name"
    cluster_created = tmp_path / "cluster-created"
    eso_wait_failed = tmp_path / "eso-wait-failed"

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' '{EXPECTED_COMMIT}'; exit 0; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"create cluster"* ]]; then
    touch "{cluster_created}"
    for arg; do if [[ "$prev" == --name ]]; then echo "$arg" >"{cluster_name_file}"; fi; prev="$arg"; done
    exit 0
  fi
  if [[ "$*" == *"get clusters"* ]]; then
    if test -f "{cluster_name_file}" && test -f "{cluster_created}" && test ! -f "{deleted}"; then
      cat "{cluster_name_file}"
    fi
    exit 0
  fi
  if [[ "$*" == *"delete cluster"* ]]; then touch "{deleted}"; exit 0; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then
    if test -f "{cluster_name_file}"; then printf 'kind-%s' "$(cat "{cluster_name_file}")"; fi
    exit 0
  fi
  if [[ "$*" == *"get gitrepository flux-system-sync"* ]]; then
    printf 'main@sha1:{EXPECTED_COMMIT}'
    exit 0
  fi
  if [[ "$*" == *" wait "* ]] || [[ "$*" == *" wait" ]]; then
    # Let every earlier readiness check succeed; fail only at the exact ESO gate.
    if [[ "$*" == *"deployment/external-secrets "* && "$*" == *"-n core-external-secrets-operator"* ]]; then
      touch "{eso_wait_failed}"
      exit 42
    fi
    exit 0
  fi
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "{EXPECTED_COMMIT}\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64", "chromium"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": EXPECTED_COMMIT,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 42, (
        f"runner must propagate the fake ESO deployment wait rc=42, got {result.returncode}; "
        f"stderr: {result.stderr}"
    )
    calls = log.read_text()
    eso_wait_call = (
        "wait --for=condition=Available deployment/external-secrets "
        "-n core-external-secrets-operator --timeout=180s"
    )
    assert eso_wait_failed.exists(), (
        f"fake must return nonzero only at the exact ESO readiness gate; calls:\n{calls}"
    )
    assert eso_wait_call in calls, f"exact ESO readiness gate was not reached; calls:\n{calls}"
    assert "deployment/external-secrets-operator" not in calls
    assert deleted.exists(), "cleanup must run after ESO wait failure"
    cluster_name = cluster_name_file.read_text().strip()
    assert cluster_name.startswith("kubecrate-e2e-")
    assert f"delete cluster --name {cluster_name}" in calls, (
        f"cleanup must delete the exact disposable cluster {cluster_name}; calls:\n{calls}"
    )
