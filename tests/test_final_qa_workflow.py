#!/usr/bin/env python3
"""Static contracts for the safeguarded exact-tree final QA workflow."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "final-qa-exact-tree.sh"
MAKEFILE = ROOT / "Makefile"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def ordered(text: str, *tokens: str) -> None:
    positions = [text.index(token) for token in tokens]
    assert positions == sorted(positions), dict(zip(tokens, positions))


def test_workflow_is_executable_and_shell_syntax_is_valid() -> None:
    assert SCRIPT.stat().st_mode & 0o111
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_exact_candidate_is_published_then_remote_sha_and_tree_are_verified() -> None:
    text = source()
    ordered(
        text,
        'CANDIDATE_SHA="$(git rev-parse "${CANDIDATE}^{commit}")"',
        'git push "${REMOTE}" "${CANDIDATE_SHA}:refs/heads/${QA_BRANCH}"',
        'REMOTE_SHA="$(git ls-remote',
        'REMOTE_TREE="$(git rev-parse "${REMOTE_SHA}^{tree}")"',
        'test "${REMOTE_TREE}" = "${CANDIDATE_TREE}"',
        'kind create cluster --name "${CLUSTER}"',
    )


def test_runtime_overlay_avoids_candidate_tree_mutation() -> None:
    text = source()
    assert "QA_VALUES" in text
    assert "render-final-qa-flux-source.py" in text
    assert "git diff --quiet" in text
    assert "sed -i" not in text
    assert "git checkout" not in text


def test_guardrails_reject_shared_names_and_protected_branches() -> None:
    text = source()
    for token in ("kind-dev-misc-local", "kubecrate-fix-eso", "main", "master", "default"):
        assert token in text
    assert text.count("assert_context") >= 7


def test_preexisting_identity_checks_are_fail_closed_and_precede_mutation() -> None:
    text = source()
    ordered(
        text,
        'if test "$(remote_branch_state)" != absent',
        'if test "$(cluster_state)" != absent',
        'git push "${REMOTE}" "${CANDIDATE_SHA}:refs/heads/${QA_BRANCH}"',
        'kind create cluster --name "${CLUSTER}"',
    )
    assert "QA branch exists or absence could not be proved" in text
    assert "QA cluster exists or absence could not be proved" in text
    assert "case \"${state_rc}\" in 0) printf 'present" in text


def test_mutating_cluster_commands_use_explicit_context_and_guards() -> None:
    text = source()
    mutation_fragments = (
        'helm upgrade --install flux-system',
        'kubectl --context "${CONTEXT}" apply -f -',
        'flux --context "${CONTEXT}" reconcile source git',
        'flux --context "${CONTEXT}" reconcile kustomization flux-system',
        'flux --context "${CONTEXT}" suspend kustomization',
        'kubectl --context "${CONTEXT}" delete secret',
        'flux --context "${CONTEXT}" resume kustomization',
        'flux --context "${CONTEXT}" reconcile kustomization external-secrets-operator-smoke',
    )
    for fragment in mutation_fragments:
        position = text.index(fragment)
        assert "assert_context" in text[max(0, position - 240):position], fragment
    assert '--kube-context "${CONTEXT}"' in text


def test_created_deploy_key_is_validated_before_readback_and_cleanup_is_fail_closed() -> None:
    text = source()
    ordered(text, 'KEY_JSON="$(gh api -X POST', 'created key id must be an integer', 'KEY_READ="$(gh api')
    assert 'test "$(key_state)" = absent || cleanup_failed=true' in text
    assert 'test "$(remote_branch_state)" = absent || cleanup_failed=true' in text
    assert 'test "$(cluster_state)" = absent || cleanup_failed=true' in text


def test_green_red_green_captures_json_and_real_browser_ui() -> None:
    text = source()
    run = text[text.index('capture_green "baseline"'):]
    ordered(
        run,
        'capture_green "baseline"',
        'controlled_red',
        'capture_red',
        'restore_source_secret',
        'capture_green "restored"',
    )
    assert "status.json" in text
    assert "--headless" in text
    assert "EXPECTED_CHECKS=7" in text
    assert "restore_if_needed" in text
    assert text.index("capture_red", text.index('capture_green "baseline"')) < text.index(
        "restore_source_secret", text.index('capture_green "baseline"')
    )


def test_cleanup_trap_verifies_exact_key_branch_and_cluster_absence() -> None:
    text = source()
    assert "trap cleanup EXIT INT TERM" in text
    for token in (
        'repos/${REPO}/keys/${KEY_ID}',
        'git push "${REMOTE}" --delete "${QA_BRANCH}"',
        'kind delete cluster --name "${CLUSTER}"',
        "cleanup verification failed",
    ):
        assert token in text


def test_make_wrapper_delegates_to_authoritative_script() -> None:
    make = MAKEFILE.read_text(encoding="utf-8")
    assert "final-qa-exact-tree:" in make
    assert "scripts/final-qa-exact-tree.sh" in make
