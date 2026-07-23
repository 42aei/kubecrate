#!/usr/bin/env python3
"""Focused tests for the direct kind+Flux E2E runner."""

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "direct-kind-flux-e2e.sh"
RENDERER = ROOT / "scripts" / "render-direct-flux-source.py"
STATUS_VALIDATOR = ROOT / "scripts" / "validate-cratecheck-status.py"
ENVOY_RUNBOOK = ROOT / "docs" / "kind-envoy-gateway-ingress-runbook.md"

EXPECTED_COMMIT = "a" * 40
PR_BRANCH = "kubecrate/envoy-after-eso-minimal-qa"


def test_runner_uses_on_demand_status_without_observation_waits() -> None:
    runner = RUNNER.read_text()
    assert "KUBECRATE_E2E_OBSERVE_SECONDS" not in runner
    assert 'EXPECTED_COMMIT="${KUBECRATE_EXPECTED_COMMIT:-$(git rev-parse HEAD)}"' in runner
    assert "3cfb4e320eff8d2a738cb36fd2420862b1db45c3" not in runner


def test_runner_uses_json_only_eso_envoy_cert_manager_and_kyverno_status_contract() -> None:
    runner = RUNNER.read_text()

    assert "chromium" not in runner.lower()
    assert "CRATECHECK_UI_URL" not in runner
    assert "validate_status_html" not in runner
    assert "status.html" not in runner

    validations = [
        line.strip()
        for line in runner.splitlines()
        if line.strip().startswith("validate_status_json ") and "; then" not in line
    ]
    assert validations == [
        'validate_status_json green "${TMPDIR}/baseline-status.json"',
        'validate_status_json eso-red "${TMPDIR}/red-status.json"',
        'validate_status_json green "${TMPDIR}/restored-status.json"',
        'validate_status_json green "${TMPDIR}/envoy-baseline-status.json"',
        'validate_status_json envoy-red "${TMPDIR}/envoy-red-status.json"',
        'validate_status_json green "${TMPDIR}/envoy-restored-status.json"',
        'validate_status_json green "${TMPDIR}/cert-manager-baseline-status.json"',
        'validate_status_json cert-manager-red "${TMPDIR}/cert-manager-red-status.json"',
        'validate_status_json green "${TMPDIR}/cert-manager-restored-status.json"',
        'validate_status_json green "${TMPDIR}/kyverno-baseline-status.json"',
        'validate_status_json kyverno-red "${TMPDIR}/kyverno-red-status.json"',
        'validate_status_json green "${TMPDIR}/kyverno-restored-status.json"',
    ]


def test_envoy_runbook_python_snippets_execute_and_baseline_enforces_green() -> None:
    snippets = re.findall(r"python3 -c '\n(.*?)\n'", ENVOY_RUNBOOK.read_text(), re.DOTALL)
    assert len(snippets) == 5

    green = {
        "status": "green",
        "checks": [{"id": "envoy-httproute-ready", "status": "green"}],
    }
    red = {
        "status": "red",
        "checks": [{"id": "envoy-httproute-ready", "status": "red"}],
    }
    for snippet in snippets:
        compile(snippet, str(ENVOY_RUNBOOK), "exec")
        status = red if "expected non-green after red test" in snippet else green
        result = subprocess.run(
            ["python3", "-c", snippet], input=json.dumps(status), text=True,
            capture_output=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr

    baseline = next(snippet for snippet in snippets if "GREEN baseline confirmed" in snippet)
    result = subprocess.run(
        ["python3", "-c", baseline], input=json.dumps(red), text=True,
        capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert "expected green" in result.stderr


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


def run_candidate_identity_case(
    tmp_path: Path,
    *,
    expected_commit: str | None = None,
    staged: bool = False,
    unstaged: bool = False,
    relevant_untracked: bool = False,
    python_import_shadow: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Run the shipped preflight until the fake kind-create sentinel."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    local_head = init_repo(repo, "candidate-identity")
    expected_commit = expected_commit or local_head

    if staged:
        (repo / "tracked").write_text("staged-shadow")
        subprocess.run(["git", "-C", repo, "add", "tracked"], check=True)
    if unstaged:
        (repo / "tracked").write_text("unstaged-shadow")
    if relevant_untracked:
        shadow = repo / "clusters/kind-dev-misc-local/entrypoint/local-shadow.yaml"
        shadow.parent.mkdir(parents=True)
        shadow.write_text("kind: ConfigMap\n")
    if python_import_shadow:
        (repo / "scripts/yaml.py").write_text(
            "raise RuntimeError('untracked yaml shadow imported')\n"
        )

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "git", f'''echo "git $*" >>"{log}"
if [[ "$*" == *"ls-remote"* ]]; then
  echo "{expected_commit}\trefs/heads/{PR_BRANCH}"
  exit 0
fi
exec /usr/bin/git "$@"''')
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth token"* ]]; then printf 'dummy-token'; exit 0
elif [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0
elif [[ "$*" == *"pulls/"* ]]; then printf '%s' '{expected_commit}'; exit 0
fi
exit 0''')
    fake_command(bindir, "kind", f'''echo "kind $*" >>"{log}"
if [[ "$*" == *"get clusters"* ]]; then exit 0; fi
if [[ "$*" == *"create cluster"* ]]; then exit 23; fi
exit 0''')
    for name in ("kubectl", "helm", "flux", "kustomize", "curl", "python3", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": expected_commit,
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    return result, log.read_text() if log.exists() else "", local_head


def test_local_candidate_identity_gate_accepts_matching_clean_tree(tmp_path: Path) -> None:
    result, calls, _ = run_candidate_identity_case(tmp_path)
    assert result.returncode == 23, result.stderr
    assert "gh auth token" in calls
    assert "kind create cluster" in calls


def test_local_candidate_identity_gate_rejects_mismatched_clean_head(tmp_path: Path) -> None:
    result, calls, local_head = run_candidate_identity_case(
        tmp_path, expected_commit="b" * 40)
    assert result.returncode != 0
    assert f"local HEAD {local_head} != expected {'b' * 40}" in result.stderr
    assert "gh auth token" not in calls
    assert "kind create cluster" not in calls


@pytest.mark.parametrize(
    ("state", "error"),
    [
        ("staged", "worktree has staged changes"),
        ("unstaged", "worktree has unstaged changes"),
        ("relevant_untracked", "relevant local input paths contain untracked files"),
        ("python_import_shadow", "scripts contains untracked Python import candidates"),
    ],
)
def test_local_candidate_identity_gate_rejects_shadowing_state_before_mutation(
    tmp_path: Path, state: str, error: str,
) -> None:
    result, calls, _ = run_candidate_identity_case(
        tmp_path,
        staged=state == "staged",
        unstaged=state == "unstaged",
        relevant_untracked=state == "relevant_untracked",
        python_import_shadow=state == "python_import_shadow",
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert "gh auth token" not in calls
    assert "kind create cluster" not in calls


# ── Shell syntax ─────────────────────────────────────────────────────────────

def test_runner_is_executable_and_syntax_valid() -> None:
    assert RUNNER.stat().st_mode & 0o111
    assert subprocess.run(["bash", "-n", str(RUNNER)]).returncode == 0


def test_runner_renders_configured_envoy_host_ports_into_kind_config(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "kind").mkdir(parents=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    init_repo(repo, "port-render")
    run_tmp = tmp_path / "run-tmp"
    run_tmp.mkdir()
    helper_source = RUNNER.read_text().split("# ── Preflight", 1)[0]
    script = helper_source + f'''\n
TMPDIR={str(run_tmp)!r}
ENVOY_HTTP_HOST_PORT=12080
ENVOY_HTTPS_HOST_PORT=12443
validate_host_port KUBECRATE_E2E_ENVOY_HTTP_HOST_PORT "${{ENVOY_HTTP_HOST_PORT}}"
validate_host_port KUBECRATE_E2E_ENVOY_HTTPS_HOST_PORT "${{ENVOY_HTTPS_HOST_PORT}}"
test "${{ENVOY_HTTP_HOST_PORT}}" != "${{ENVOY_HTTPS_HOST_PORT}}"
render_kind_config
printf '%s\n' "${{KIND_CONFIG_RENDERED}}"
'''
    result = subprocess.run(
        ["bash", "-c", script], cwd=repo, text=True,
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    rendered = Path(result.stdout.strip()).read_text()
    assert "containerPort: 30080" in rendered
    assert "hostPort: 12080" in rendered
    assert "containerPort: 30443" in rendered
    assert "hostPort: 12443" in rendered
    assert "hostPort: 10080" not in rendered
    assert "hostPort: 10443" not in rendered


def test_runner_rejects_invalid_or_duplicate_envoy_host_ports() -> None:
    text = RUNNER.read_text()
    assert 'ENVOY_STATUS_URL="http://127.0.0.1:${ENVOY_HTTP_HOST_PORT}/status.json"' in text
    assert 'ENVOY_TLS_STATUS_URL="https://cratecheck.local:${ENVOY_HTTPS_HOST_PORT}/status.json"' in text
    assert 'kind create cluster --name "${CLUSTER}" --config "${KIND_CONFIG_RENDERED}"' in text
    assert 'test "${ENVOY_HTTP_HOST_PORT}" != "${ENVOY_HTTPS_HOST_PORT}"' in text

    helper_source = text.split("# ── Preflight", 1)[0]
    script = helper_source + '''\n
ENVOY_HTTP_HOST_PORT="$1"
ENVOY_HTTPS_HOST_PORT="$2"
validate_host_port KUBECRATE_E2E_ENVOY_HTTP_HOST_PORT "${ENVOY_HTTP_HOST_PORT}"
validate_host_port KUBECRATE_E2E_ENVOY_HTTPS_HOST_PORT "${ENVOY_HTTPS_HOST_PORT}"
test "${ENVOY_HTTP_HOST_PORT}" != "${ENVOY_HTTPS_HOST_PORT}" || \
  fail "Envoy HTTP and HTTPS host ports must differ"
'''
    cases = [
        ("12080", "12443", True, ""),
        ("not-a-port", "12443", False, "numeric TCP host port"),
        ("0", "12443", False, "between 1 and 65535"),
        ("12080", "12080", False, "must differ"),
    ]
    for http_port, https_port, valid, error in cases:
        result = subprocess.run(
            ["bash", "-c", script, "port-test", http_port, https_port],
            cwd=ROOT, text=True, capture_output=True, timeout=10,
        )
        assert (result.returncode == 0) is valid, result.stderr
        if error:
            assert error in result.stderr


@pytest.mark.parametrize(
    ("revision", "valid"),
    [
        (f"main@sha1:{EXPECTED_COMMIT}", True),
        (f"refs/heads/main@sha1:{EXPECTED_COMMIT}", True),
        (f"main@sha1:{EXPECTED_COMMIT}0", False),
        (f"main@sha1:0{EXPECTED_COMMIT}", False),
        ("main@sha1:" + "b" * 40, False),
        ("", False),
        (f"sha1:{EXPECTED_COMMIT}", False),
        (f"main@sha256:{EXPECTED_COMMIT}", False),
    ],
)
def test_flux_artifact_revision_contract(revision: str, valid: bool) -> None:
    """Exercise the runner's exact artifact-revision validator in isolation."""
    runner = RUNNER.read_text()
    start = runner.index("validate_artifact_revision()")
    end = runner.index("\n}\n", start) + 3
    function = runner[start:end]
    command = f'''set -Eeuo pipefail
EXPECTED_COMMIT={EXPECTED_COMMIT!r}
fail() {{ printf '%s\\n' "$*" >&2; exit 1; }}
{function}
validate_artifact_revision "$1"
'''
    result = subprocess.run(
        ["bash", "-c", command, "revision-test", revision],
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert (result.returncode == 0) is valid, result.stderr


def test_renderer_is_executable_and_syntax_valid() -> None:
    assert RENDERER.stat().st_mode & 0o111
    assert subprocess.run(["python3", "-m", "py_compile", str(RENDERER)]).returncode == 0


# ── Revision mismatch ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("remote_main", "pr_state", "pr_merged", "merge_commit", "accepted", "error"),
    [
        (EXPECTED_COMMIT, "closed", "true", EXPECTED_COMMIT, True, ""),
        ("b" * 40, "closed", "true", EXPECTED_COMMIT, False, "remote branch main SHA"),
        (EXPECTED_COMMIT, "closed", "true", "b" * 40, False, "merge commit"),
        (EXPECTED_COMMIT, "open", "false", EXPECTED_COMMIT, False, "not closed and merged"),
    ],
)
def test_current_main_identity_mode_fails_closed_before_cluster_creation(
    tmp_path: Path, remote_main: str, pr_state: str, pr_merged: str,
    merge_commit: str, accepted: bool, error: str,
) -> None:
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    local_candidate = init_repo(repo, "current-main")
    remote_main = local_candidate if remote_main == EXPECTED_COMMIT else remote_main
    merge_commit = local_candidate if merge_commit == EXPECTED_COMMIT else merge_commit

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "git", f'''echo "git $*" >>"{log}"
if [[ "$*" == *"ls-remote"* ]]; then
  echo "{remote_main}\trefs/heads/main"
  exit 0
fi
exec /usr/bin/git "$@"''')
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth token"* ]]; then printf 'dummy-token'; exit 0
elif [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0
elif [[ "$*" == *"pulls/"* ]]; then printf '%s\\t%s\\t%s\\n' '{pr_state}' '{pr_merged}' '{merge_commit}'; exit 0
elif [[ "$*" == *"--method POST"* ]]; then exit 0
elif [[ "$*" == *"--method DELETE"* ]]; then exit 0
elif [[ "$*" == *"git/ref/heads/"* && "$*" == *"--jq"* ]]; then
  printf 'refs/heads/%s\\tcommit\\t%s\\n' "$KUBECRATE_E2E_QA_BRANCH" "$KUBECRATE_EXPECTED_COMMIT"; exit 0
elif [[ "$*" == *"git/ref/heads/"* ]]; then printf 'gh: Not Found (HTTP 404)' >&2; exit 1
fi
exit 0''')
    fake_command(bindir, "kind", f'''echo "kind $*" >>"{log}"
if [[ "$*" == *"get clusters"* ]]; then exit 0; fi
if [[ "$*" == *"create cluster"* ]]; then exit 23; fi
exit 0''')
    for name in ("kubectl", "helm", "flux", "kustomize", "curl", "python3", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_E2E_IDENTITY_MODE": "current-main",
           "KUBECRATE_EXPECTED_COMMIT": local_candidate,
           "KUBECRATE_E2E_QA_BRANCH": "kubecrate-qa-settled-main-test",
           "KUBECRATE_PR_NUMBER": "21"}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    calls = log.read_text()
    if accepted:
        assert result.returncode == 23, result.stderr
        assert "create cluster" in calls
        assert "--method POST repos/42aei/kubecrate/git/refs" in calls
        assert "ref=refs/heads/kubecrate-qa-settled-main-test" in calls
        assert "--method DELETE repos/42aei/kubecrate/git/refs/heads/kubecrate-qa-settled-main-test" in calls
    else:
        assert result.returncode != 0
        assert error in result.stderr
        assert "create cluster" not in calls


def test_current_main_mode_renders_flux_disposable_qa_branch() -> None:
    text = RUNNER.read_text()
    assert 'SOURCE_BRANCH="${QA_BRANCH}"' in text
    assert '--branch "${SOURCE_BRANCH}"' in text


def test_current_main_uses_and_cleans_owned_disposable_ref(tmp_path: Path) -> None:
    """Exercise create/read/use/recheck/delete/absence through the shipped runner."""
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    for directory in (
        "kind",
        "clusters/kind-dev-misc-local/platform-services/flux",
        "clusters/kind-dev-misc-local/entrypoint",
    ):
        (repo / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    (repo / "clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml").write_text("{}\n")
    local_candidate = init_repo(repo, "current-main-owned-ref-lifecycle")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    ref_state = tmp_path / "ref-state"
    cluster_state = tmp_path / "cluster-state"
    cluster_name = tmp_path / "cluster-name"
    rendered = tmp_path / "rendered.yaml"
    qa_branch = "kubecrate-qa-settled-main-lifecycle"

    fake_command(bindir, "git", f'''echo "git $*" >>"{log}"
if [[ "$*" == *"ls-remote"* ]]; then echo "$KUBECRATE_EXPECTED_COMMIT refs/heads/main"; exit 0; fi
exec /usr/bin/git "$@"''')
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth token"* ]]; then printf 'dummy-token'; exit 0
elif [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0
elif [[ "$*" == *"pulls/"* ]]; then printf 'closed\\ttrue\\t%s\\n' "$KUBECRATE_EXPECTED_COMMIT"; exit 0
elif [[ "$*" == *"--method POST"* ]]; then
  test ! -e "{ref_state}" || exit 1
  touch "{ref_state}"; exit 0
elif [[ "$*" == *"--method DELETE"* ]]; then
  test -e "{ref_state}" || exit 1
  rm "{ref_state}"; exit 0
elif [[ "$*" == *"git/ref/heads/"* && "$*" == *"--jq"* ]]; then
  test -e "{ref_state}" || exit 1
  printf 'refs/heads/%s\\tcommit\\t%s\\n' "$KUBECRATE_E2E_QA_BRANCH" "$KUBECRATE_EXPECTED_COMMIT"; exit 0
elif [[ "$*" == *"git/ref/heads/"* ]]; then
  test ! -e "{ref_state}" || exit 0
  printf 'gh: Not Found (HTTP 404)' >&2; exit 1
fi
exit 0''')
    fake_command(bindir, "kind", f'''echo "kind $*" >>"{log}"
if [[ "$*" == *"create cluster"* ]]; then
  previous=''; for argument; do if [[ "$previous" == --name ]]; then printf '%s' "$argument" >"{cluster_name}"; fi; previous="$argument"; done
  touch "{cluster_state}"; exit 0
elif [[ "$*" == *"delete cluster"* ]]; then rm -f "{cluster_state}"; exit 0
elif [[ "$*" == *"get clusters"* ]]; then
  if test -e "{cluster_state}"; then cat "{cluster_name}"; printf '\\n'; fi
  exit 0
fi
exit 0''')
    fake_command(bindir, "kubectl", f'''echo "kubectl $*" >>"{log}"
if [[ "$*" == *"config current-context"* ]]; then printf 'kind-%s' "$(cat "{cluster_name}")"; exit 0
elif [[ "$*" == *"apply -f -"* ]]; then cat >"{rendered}"; exit 42
fi
exit 0''')
    fake_command(bindir, "kustomize", '''cat <<'YAML'
apiVersion: v1
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
        ref:
          branch: main
    kustomization:
      spec:
        path: ./clusters/kind-dev-misc-local/entrypoint
YAML''')
    fake_command(bindir, "python3", f'exec {shlex.quote(sys.executable)} "$@"')
    for name in ("helm", "flux", "curl", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_E2E_IDENTITY_MODE": "current-main",
           "KUBECRATE_EXPECTED_COMMIT": local_candidate,
           "KUBECRATE_E2E_QA_BRANCH": qa_branch,
           "KUBECRATE_PR_NUMBER": "21"}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)

    assert result.returncode == 42, result.stderr
    assert not ref_state.exists()
    assert not cluster_state.exists()
    assert f"branch: {qa_branch}" in rendered.read_text()
    calls = log.read_text().splitlines()
    create = next(i for i, call in enumerate(calls) if "--method POST" in call)
    reads = [i for i, call in enumerate(calls) if "git/ref/heads/" in call and "--jq" in call]
    delete = next(i for i, call in enumerate(calls) if "--method DELETE" in call)
    absence = next(i for i, call in enumerate(calls) if i > delete and "git/ref/heads/" in call)
    render_apply = next(i for i, call in enumerate(calls) if "kubectl" in call and "apply -f -" in call)
    assert len(reads) == 2
    assert create < reads[0] < render_apply < reads[1] < delete < absence


@pytest.mark.parametrize(
    ("scenario", "expected_error", "expect_delete"),
    [
        ("pre-existing", "ref creation failed", False),
        ("mismatched-readback", "readback did not match", False),
        ("changed-before-cleanup", "cleanup verification failed", False),
    ],
)
def test_current_main_disposable_ref_failures_refuse_cluster_and_unsafe_delete(
    tmp_path: Path, scenario: str, expected_error: str, expect_delete: bool,
) -> None:
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    local_candidate = init_repo(repo, "current-main-ref-failure")
    changed = "b" * 40
    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    get_count = tmp_path / "get-count"
    fake_command(bindir, "git", f'''echo "git $*" >>"{log}"
if [[ "$*" == *"ls-remote"* ]]; then echo "$KUBECRATE_EXPECTED_COMMIT refs/heads/main"; exit 0; fi
exec /usr/bin/git "$@"''')
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth token"* ]]; then printf 'dummy-token'; exit 0
elif [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0
elif [[ "$*" == *"pulls/"* ]]; then printf 'closed\\ttrue\\t%s\\n' "$KUBECRATE_EXPECTED_COMMIT"; exit 0
elif [[ "$*" == *"--method POST"* ]]; then
  if [[ {scenario!r} == pre-existing ]]; then printf 'gh: Reference already exists (HTTP 422)' >&2; exit 1; fi
  exit 0
elif [[ "$*" == *"--method DELETE"* ]]; then exit 0
elif [[ "$*" == *"git/ref/heads/"* && "$*" == *"--jq"* ]]; then
  count=0; test ! -f "{get_count}" || count=$(cat "{get_count}"); count=$((count + 1)); echo "$count" >"{get_count}"
  if [[ {scenario!r} == mismatched-readback || ( {scenario!r} == changed-before-cleanup && $count -gt 1 ) ]]; then
    printf 'refs/heads/%s\\tcommit\\t%s\\n' "$KUBECRATE_E2E_QA_BRANCH" '{changed}'
  else
    printf 'refs/heads/%s\\tcommit\\t%s\\n' "$KUBECRATE_E2E_QA_BRANCH" "$KUBECRATE_EXPECTED_COMMIT"
  fi
  exit 0
elif [[ "$*" == *"git/ref/heads/"* ]]; then printf 'gh: Not Found (HTTP 404)' >&2; exit 1
fi
exit 0''')
    fake_command(bindir, "kind", f'''echo "kind $*" >>"{log}"
if [[ "$*" == *"get clusters"* ]]; then exit 0; fi
if [[ "$*" == *"create cluster"* ]]; then exit 23; fi
exit 0''')
    for name in ("kubectl", "helm", "flux", "kustomize", "curl", "python3", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_E2E_IDENTITY_MODE": "current-main",
           "KUBECRATE_EXPECTED_COMMIT": local_candidate,
           "KUBECRATE_E2E_QA_BRANCH": "kubecrate-qa-settled-main-test",
           "KUBECRATE_PR_NUMBER": "21"}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0
    calls = log.read_text()
    if scenario == "changed-before-cleanup":
        assert "create cluster" in calls
    else:
        assert "create cluster" not in calls
    assert ("--method DELETE" in calls) is expect_delete
    assert expected_error in result.stderr

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
elif [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0
fi
exit 0''')
    for name in ("kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
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

_SENTINEL_TOKEN = "«redacted:ghp_…»"

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
if [[ "$*" == *"ls-remote"* ]]; then echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0; fi
exec /usr/bin/git "$@"''')
    for name in ("kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
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
        ["python3", str(RENDERER), "--https-url", "https://github.com/42aei/kubecrate.git",
         "--branch", PR_BRANCH],
        input=input_yaml, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr

    output = result.stdout
    assert "ssh://" not in output
    assert "https://github.com/42aei/kubecrate.git" in output
    assert "create: true" not in output
    assert "create: false" in output
    assert "sshKeyAlgorithm" not in output
    assert "secretRef" in output
    assert f"branch: {PR_BRANCH}" in output


def test_renderer_rejects_missing_or_multiple_configmaps() -> None:
    """Renderer fails on zero or multiple flux-sync-values ConfigMaps."""
    result = subprocess.run(
        ["python3", str(RENDERER), "--https-url", "https://example.com",
         "--branch", PR_BRANCH],
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
        ["python3", str(RENDERER), "--https-url", "https://example.com",
         "--branch", PR_BRANCH],
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
    assert ('assert_context\nkubectl --context "${CONTEXT}" delete externalsecret '
            'eso-smoke-projection') in text
    assert 'delete secret eso-smoke-source' not in text

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

    assert "RED_STATE=eso_restore_required" in text
    assert "RED_STATE=envoy_restore_required" in text
    assert "RED_STATE=cert_manager_restore_required" in text
    assert "RED_STATE=kyverno_restore_required" in text
    assert "RED_STATE=none" in text


def test_success_cleanup_leaves_no_failure_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    run_tmp = tmp_path / "run-tmp"
    run_tmp.mkdir()
    helper_source = RUNNER.read_text().split("# ── Preflight", 1)[0]
    script = helper_source + f'''\n
EVIDENCE_ROOT={str(evidence)!r}
TMPDIR={str(run_tmp)!r}
CLUSTER_CREATED=false
cleanup
'''
    result = subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert not evidence.exists()
    assert not run_tmp.exists()


def test_failure_evidence_prefers_cert_manager_red_over_stale_envoy_green(
    tmp_path: Path,
) -> None:
    """The real evidence helper records the active cert-manager failure phase."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    for name in ("kubectl", "flux"):
        fake_command(bindir, name, "exit 0")
    evidence = tmp_path / "evidence"
    run_tmp = tmp_path / "run-tmp"; run_tmp.mkdir()
    (run_tmp / "envoy-restored-status.json").write_text(json.dumps({
        "status": "green",
        "checks": [{"id": "envoy-httproute-ready", "status": "green"}],
    }))
    (run_tmp / "cert-manager-red-status.json").write_text(json.dumps({
        "status": "red",
        "checks": [
            {"id": "cert-manager-tls-certificate-ready", "status": "red"},
        ],
    }))
    (run_tmp / "flux-https-secret.yaml").write_text(
        "kind: Secret\npassword: evidence-test-token\n"
    )

    helper_source = RUNNER.read_text().split("# ── Preflight", 1)[0]
    script = helper_source + f'''\n
EVIDENCE_ROOT={str(evidence)!r}
TMPDIR={str(run_tmp)!r}
CLUSTER='kubecrate-e2e-cert-manager-red'
CONTEXT='kind-kubecrate-e2e-cert-manager-red'
CURRENT_PHASE='cert-manager-controlled-red'
FAILURE_ASSERTION='forced cert-manager red evidence regression'
write_failure_evidence
'''
    result = subprocess.run(
        ["bash", "-c", script], cwd=ROOT,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    bundle = evidence / "kubecrate-e2e-cert-manager-red"
    assert json.loads((bundle / "status-verdict.json").read_text()) == {
        "checks": [
            {"id": "cert-manager-tls-certificate-ready", "status": "red"},
        ],
        "status": "red",
    }
    evidence_text = "".join(item.read_text() for item in bundle.iterdir())
    assert "evidence-test-token" not in evidence_text
    assert "kind: Secret" not in evidence_text


def test_hung_failure_evidence_is_bounded_and_cleanup_completes(tmp_path: Path) -> None:
    """A hung evidence read is diagnosed without blocking restore or exact cleanup."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    evidence = tmp_path / "evidence"
    run_tmp = tmp_path / "run-tmp"; run_tmp.mkdir()
    secret_manifest = run_tmp / "flux-https-secret.yaml"
    secret_manifest.write_text("kind: Secret\npassword: evidence-test-token\n")
    deleted = tmp_path / "cluster-deleted"
    cluster = "kubecrate-e2e-hung-evidence"
    context = f"kind-{cluster}"

    dispatch = f'''echo "$0 $*" >>"{log}"
name=$(basename "$0")
if [[ $name == flux ]]; then
  if [[ "$*" == *"get kustomizations"* ]]; then while :; do sleep 1; done; fi
  exit 0
elif [[ $name == kubectl ]]; then
  if [[ "$*" == *"config current-context"* ]]; then printf '%s' '{context}'; fi
  exit 0
elif [[ $name == kind ]]; then
  if [[ "$*" == *"delete cluster --name {cluster}"* ]]; then touch "{deleted}"; exit 0; fi
  if [[ "$*" == *"get clusters"* ]] && test ! -f "{deleted}"; then printf '%s\n' '{cluster}'; fi
  exit 0
fi
exit 0'''
    for name in ("flux", "kubectl", "kind"):
        fake_command(bindir, name, dispatch)

    helper_source = RUNNER.read_text().split("# ── Preflight", 1)[0]
    script = helper_source + f'''\n
EVIDENCE_ROOT={str(evidence)!r}
TMPDIR={str(run_tmp)!r}
CLUSTER={cluster!r}
CONTEXT={context!r}
CLUSTER_CREATED=true
RED_STATE=eso_restore_required
TOKEN=evidence-test-token
CURRENT_PHASE=controlled-red
FAILURE_ASSERTION='forced failure for hung evidence regression'
set +e
false
cleanup
'''
    started = time.monotonic()
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
             "KUBECRATE_E2E_EVIDENCE_TIMEOUT": "1s"},
        text=True, capture_output=True, timeout=8,
    )
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert elapsed < 8
    assert deleted.exists(), "exact generated cluster must be deleted after evidence timeout"
    calls = log.read_text()
    assert "resume kustomization external-secrets-operator-smoke" in calls
    assert f"delete cluster --name {cluster}" in calls
    assert calls.count("get clusters") >= 2, "cleanup must verify authoritative absence"
    assert not run_tmp.exists(), "temporary credentials and state must be removed"
    readiness = (evidence / cluster / "readiness.txt").read_text()
    assert "flux-kustomizations unavailable: evidence command timed out after 1s" in readiness
    evidence_text = "".join(item.read_text() for item in (evidence / cluster).iterdir())
    assert "evidence-test-token" not in evidence_text
    assert "kind: Secret" not in evidence_text


def test_controlled_red_deletes_directly_observed_externalsecret_and_restores_in_order() -> None:
    """Red is immediate, while restore reconciles before exact projected-value proof."""
    text = RUNNER.read_text()
    red = text[text.index("# ── Controlled Red"):text.index("# ── Restore Green")]
    assert "delete externalsecret eso-smoke-projection" in red
    assert "delete secret eso-smoke-source" not in red
    restore = text[text.index("# ── Restore Green"):]
    ordered = [
        'resume kustomization external-secrets-operator-smoke',
        'reconcile kustomization external-secrets-operator-smoke',
        'wait --for=condition=Ready',
        'decode_smoke_value eso-smoke-projected',
        'validate_status_json green',
    ]
    positions = [restore.index(fragment) for fragment in ordered]
    assert positions == sorted(positions)


def test_envoy_scenario_is_bounded_and_restores_exact_route() -> None:
    text = RUNNER.read_text()
    scenario = text[text.index("# ── Envoy Gateway Scenario"):text.index("# Kill port-forward")]
    assert scenario.count("patch httproute envoy-smoke-cratecheck") == 2
    assert '"value":9999' in scenario
    assert '"value":8080' in scenario
    assert "suspend kustomization envoy-gateway-smoke" in scenario
    assert "resume kustomization envoy-gateway-smoke" in scenario
    assert 'validate_status_json envoy-red "${TMPDIR}/envoy-red-status.json"' in scenario
    assert 'curl --fail --silent --show-error "${ENVOY_STATUS_URL}"' in scenario
    red_validator = scenario.index("validate_status_json envoy-red")
    restore = scenario.index('"value":8080')
    final_green = scenario.rindex("validate_status_json green")
    assert red_validator < restore < final_green


def test_cert_manager_scenario_uses_trusted_https_and_exact_red_restore() -> None:
    text = RUNNER.read_text()
    scenario = text[text.index("# ── cert-manager TLS Scenario"):text.index("# Kill port-forward")]
    assert '--cacert "${TMPDIR}/cratecheck-ca.crt"' in scenario
    assert '--resolve "cratecheck.local:${ENVOY_HTTPS_HOST_PORT}:127.0.0.1"' in scenario
    assert 'cratecheck.local:10443:127.0.0.1' not in scenario
    assert "suspend kustomization cert-manager-local-issuer" in scenario
    assert "delete certificate cratecheck-tls" in scenario
    assert "delete secret cratecheck-tls" not in scenario
    assert 'validate_status_json cert-manager-red "${TMPDIR}/cert-manager-red-status.json"' in scenario
    assert "resume kustomization cert-manager-local-issuer" in scenario
    assert "reconcile kustomization cert-manager-local-issuer" in scenario
    assert scenario.rindex("validate_status_json green") > scenario.index("resume kustomization")


def test_kyverno_scenario_proves_exact_deny_and_bounded_red_restore() -> None:
    text = RUNNER.read_text()
    admission = text[text.index("# Prove the policy admitted"):text.index("CURRENT_PHASE=kyverno-green")]
    assert "create namespace kyverno-smoke-denied" in admission
    assert "test \"${deny_rc}\" -ne 0" in admission
    assert 'assert_kyverno_denial_reason "${deny_output}"' in admission
    assert 'KYVERNO_DENIAL_REASON="Namespace requires kubecrate.io/validated=true"' in text

    scenario = text[text.index("# ── Kyverno Policy Scenario"):text.index("# Kill port-forward")]
    assert "suspend kustomization kyverno-smoke-policy" in scenario
    assert "delete clusterpolicy require-ns-label" in scenario
    assert 'validate_status_json kyverno-red "${TMPDIR}/kyverno-red-status.json"' in scenario
    assert "resume kustomization kyverno-smoke-policy" in scenario
    assert "reconcile kustomization kyverno-smoke-policy" in scenario
    assert scenario.rindex("validate_status_json green") > scenario.index("resume kustomization")


def test_kyverno_denial_reason_matches_real_kubectl_output() -> None:
    """The exact policy reason survives Kyverno's kubectl error serialization."""
    helper_source = RUNNER.read_text().split("# ── Preflight", 1)[0]
    observed = """Error from server: admission webhook "validate.kyverno.svc-fail" denied the request:

resource Namespace//kyverno-smoke-denied was blocked due to the following policies

require-ns-label:
  require-validated-label: 'validation error: Namespace requires kubecrate.io/validated=true.
    rule require-validated-label failed at path /metadata/labels/kubecrate.io/validated/'
"""
    script = (
        helper_source
        + "\nassert_kyverno_denial_reason \"$1\"\n"
    )
    result = subprocess.run(
        ["bash", "-c", script, "kyverno-denial-test", observed],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr

    wrong_reason = observed.replace(
        "Namespace requires kubecrate.io/validated=true",
        "Namespace was denied for an unspecified reason",
    )
    rejected = subprocess.run(
        ["bash", "-c", script, "kyverno-denial-test", wrong_reason],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert rejected.returncode != 0
    assert "did not contain the exact policy reason" in rejected.stderr


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
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
elif [[ $name == helm ]]; then
  if [[ "$*" == *"--install"* ]]; then touch "{barrier}"; while :; do sleep 1; done; fi
  exit 0
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
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
         f"kustomize build {base} | python3 {RENDERER} --https-url https://github.com/42aei/kubecrate.git --branch {PR_BRANCH}"],
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "https://github.com/42aei/kubecrate.git" in result.stdout
    assert "ssh://" not in result.stdout
    assert "secretRef" in result.stdout
    assert f"branch: {PR_BRANCH}" in result.stdout


# ── Readiness failure ─────────────────────────────────────────────────────────

def test_child_flux_readiness_precedes_workload_access() -> None:
    """Child Kustomizations become Ready in dependency order before workloads."""
    text = RUNNER.read_text()
    ordered_commands = [
        'kustomization/external-secrets-operator -n "${FLUX_NAMESPACE}"',
        'kustomization/external-secrets-operator-smoke -n "${FLUX_NAMESPACE}"',
        'kustomization/cratecheck -n "${FLUX_NAMESPACE}"',
        'kustomization/envoy-gateway -n "${FLUX_NAMESPACE}"',
        'kustomization/envoy-gateway-smoke -n "${FLUX_NAMESPACE}"',
        "deployment/cratecheck -n cratecheck",
        "deployment/external-secrets -n core-external-secrets-operator",
        "decode_smoke_value eso-smoke-projected",
    ]
    positions = [text.index(command) for command in ordered_commands]
    assert positions == sorted(positions), (
        "Flux child readiness must follow dependency order and precede namespace, "
        "workload, and projected Secret access"
    )


def test_cratecheck_child_failure_prevents_workload_access(tmp_path: Path) -> None:
    """A non-Ready CrateCheck child stops the runner before namespace access."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "kubectl.log"
    fake_command(bindir, "kubectl", f'''echo "$*" >>"{log}"
if [[ "$*" == *"config current-context"* ]]; then printf 'kind-test'; exit 0; fi
if [[ "$*" == *"kustomization/cratecheck "* ]]; then exit 42; fi
exit 0''')
    text = RUNNER.read_text()
    readiness = text.split("# Wait for Flux child Kustomizations in dependency order.", 1)[1].split(
        "# Verify the projected Secret value exactly", 1
    )[0]
    script = "set -Eeuo pipefail\nCONTEXT=kind-test\nFLUX_NAMESPACE=flux-system\n" + (
        "fail() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
        "assert_context() { actual=\"$(kubectl config current-context)\"; "
        "test \"${actual}\" = \"${CONTEXT}\" || fail wrong-context; }\n"
    ) + readiness
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 42, result.stderr
    calls = log.read_text()
    assert "kustomization/cratecheck " in calls
    assert "deployment/cratecheck" not in calls
    assert "deployment/external-secrets" not in calls


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
    evidence = tmp_path / "evidence"
    run_tmp_root = tmp_path / "run-tmp"
    run_tmp_root.mkdir()

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    printf 'main@sha1:%s' "$KUBECRATE_EXPECTED_COMMIT"
    exit 0
  fi
  if [[ "$*" == *"kustomization/cratecheck "* ]]; then exit 1; fi
  if [[ "$*" == *" wait "* ]] || [[ "$*" == *" wait" ]]; then exit 0; fi
  exit 0
elif [[ $name == flux ]]; then
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
           "KUBECRATE_PR_BRANCH": PR_BRANCH,
           "KUBECRATE_E2E_EVIDENCE_DIR": str(evidence),
           "KUBECRATE_E2E_TMP_ROOT": str(run_tmp_root)}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner should fail on readiness timeout (rc={result.returncode})"
    assert deleted.exists(), "cluster must be deleted after readiness failure"
    bundles = list(evidence.iterdir())
    assert len(bundles) == 1
    bundle = bundles[0]
    summary = (bundle / "summary.txt").read_text()
    assert f"candidate={env['KUBECRATE_EXPECTED_COMMIT']}" in summary
    assert f"ref={PR_BRANCH}" in summary
    assert "phase=flux-child-readiness" in summary
    assert "assertion=cratecheck Kustomization became Ready" in summary
    assert "cluster=kubecrate-e2e-" in summary
    assert "context=kind-kubecrate-e2e-" in summary
    assert (bundle / "readiness.txt").is_file()
    assert json.loads((bundle / "status-verdict.json").read_text()) == {
        "status": "not-observed"
    }
    evidence_text = "".join(item.read_text() for item in bundle.iterdir())
    assert "test-token" not in evidence_text
    assert "kind: Secret" not in evidence_text
    assert list(run_tmp_root.iterdir()) == []


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
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
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
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must exit non-zero on partial create (rc={result.returncode})"
    assert deleted.exists(), "cleanup must delete cluster after partial create"


# ── Projected value integration failures ─────────────────────────────────────

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
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    printf 'main@sha1:%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0
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
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
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
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    printf 'main@sha1:%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0
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
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode != 0, f"runner must fail on wrong decoded value (rc={result.returncode})"
    assert "Secret value mismatch" in result.stderr, f"expected value mismatch, got: {result.stderr}"


# ── Identity guard ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("user_script", "expected_user", "forbidden_call"),
    [
        ("printf 'octocat'; exit 0", "octocat", "create cluster"),
        ("printf ''; exit 0", "unknown", "auth token"),
        ("exit 1", "unknown", "auth token"),
    ],
)
def test_identity_guard_rejects_unexpected_user(
    tmp_path: Path, user_script: str, expected_user: str, forbidden_call: str
) -> None:
    repo = tmp_path / "repo"; repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    (repo / "kind").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "kind" / "config.yaml", repo / "kind" / "config.yaml")
    init_repo(repo, "wrong-user")

    bindir = tmp_path / "bin"; bindir.mkdir(); log = tmp_path / "calls.log"
    fake_command(bindir, "gh", f'''echo "gh $*" >>"{log}"
if [[ "$*" == *"auth status"* ]]; then exit 0
elif [[ "$*" == *"api user"* ]]; then {user_script}
fi
exit 0''')
    fake_command(bindir, "git", f'echo "git $*" >>"{log}"; exec /usr/bin/git "$@"')
    for name in ("kind", "kubectl", "helm", "flux", "kustomize",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, f'echo "{name} $*" >>"{log}"; exit 0')

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)

    assert result.returncode != 0
    assert f"expected faksibot, got {expected_user}" in result.stderr
    calls = log.read_text() if log.exists() else ""
    assert forbidden_call not in calls


# ── ESO deployment wait propagation ──────────────────────────────────────────

def test_envoy_gateway_programmed_wait_failure_propagates(tmp_path: Path) -> None:
    """The exact smoke Gateway Programmed gate fails closed and cleans up."""
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
    init_repo(repo, "envoy-gateway-wait-fail")

    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.log"
    deleted = tmp_path / "cluster-deleted"
    cluster_name_file = tmp_path / "cluster-name"
    cluster_created = tmp_path / "cluster-created"
    gateway_wait_failed = tmp_path / "gateway-wait-failed"

    dispatch = f'''#!/usr/bin/env bash
echo "$0 $*" >>"{log}"
name=$(basename $0)
if [[ $name == gh ]]; then
  if [[ "$*" == *"auth token"* ]]; then printf 'test-token'; exit 0; fi
  if [[ "$*" == *"auth status"* ]]; then exit 0; fi
  if [[ "$*" == *"api user"* ]]; then printf 'faksibot'; exit 0; fi
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    printf 'main@sha1:%s' "$KUBECRATE_EXPECTED_COMMIT"
    exit 0
  fi
  if [[ "$*" == *" wait "* ]] || [[ "$*" == *" wait" ]]; then
    if [[ "$*" == *"--for=condition=Programmed"* && "$*" == *"gateway/kubecrate-envoy-smoke"* && "$*" == *"-n core-envoy-gateway"* ]]; then
      touch "{gateway_wait_failed}"
      exit 42
    fi
    exit 0
  fi
  exit 0
elif [[ $name == git ]]; then
  if [[ "$*" == *"ls-remote"* ]]; then
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
           "KUBECRATE_PR_BRANCH": PR_BRANCH}
    result = subprocess.run(
        [str(RUNNER)], cwd=repo, env=env, text=True, capture_output=True, timeout=30)

    assert result.returncode == 42, (
        f"runner must propagate the Gateway Programmed wait rc=42, got {result.returncode}; "
        f"stderr: {result.stderr}"
    )
    assert gateway_wait_failed.exists(), "the exact Gateway Programmed gate was not reached"
    calls = log.read_text()
    assert (
        "wait --for=condition=Programmed gateway/kubecrate-envoy-smoke "
        "-n core-envoy-gateway --timeout=300s"
    ) in calls
    smoke_ready = calls.index(
        "wait --for=condition=Ready kustomization/envoy-gateway-smoke "
        "-n flux-system --timeout=300s"
    )
    gateway_programmed = calls.index(
        "wait --for=condition=Programmed gateway/kubecrate-envoy-smoke "
        "-n core-envoy-gateway --timeout=300s"
    )
    assert smoke_ready < gateway_programmed
    assert "deployment/cratecheck" not in calls
    assert "deployment/external-secrets" not in calls
    cluster_name = cluster_name_file.read_text().strip()
    assert f"delete cluster --name {cluster_name}" in calls


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
  if [[ "$*" == *"api"* ]]; then printf '%s' "$KUBECRATE_EXPECTED_COMMIT"; exit 0; fi
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
    printf 'main@sha1:%s' "$KUBECRATE_EXPECTED_COMMIT"
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
    echo "$KUBECRATE_EXPECTED_COMMIT\trefs/heads/{PR_BRANCH}"; exit 0
  fi
  exec /usr/bin/git "$@"
fi
exit 0
'''
    for name in ("gh", "kind", "kubectl", "helm", "flux", "kustomize", "git",
                 "curl", "python3", "base64"):
        fake_command(bindir, name, dispatch)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
           "KUBECRATE_EXPECTED_COMMIT": subprocess.check_output(
               ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip(),
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
