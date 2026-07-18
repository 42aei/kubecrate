#!/usr/bin/env python3
"""Static contracts for the safeguarded exact-tree final QA workflow."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "final-qa-exact-tree.sh"
LIFECYCLE = ROOT / "scripts" / "final-qa-lifecycle.sh"
MAKEFILE = ROOT / "Makefile"
MANIFEST_WORKFLOW = ROOT / ".github/workflows/kubernetes-manifest-linting.yaml"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8") + "\n" + LIFECYCLE.read_text(encoding="utf-8")


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
        'test "$(git rev-parse HEAD)" = "${CANDIDATE_SHA}"',
        'test "$(git write-tree)" = "${CANDIDATE_TREE}"',
        'final_qa_helpers.py create-ref',
        'kind create cluster --name "${CLUSTER}"',
    )


def test_runtime_overlay_avoids_candidate_tree_mutation() -> None:
    text = source()
    assert "QA_VALUES" in text
    assert "render-final-qa-flux-source.py" in text
    assert "git diff --quiet" in text
    assert "sed -i" not in text
    assert "git checkout" not in text
    qa_values_start = text.index('cat >"${QA_VALUES}"')
    qa_values = text[qa_values_start:text.index("\nEOF", qa_values_start)]
    assert "branch: ${QA_BRANCH}" in qa_values
    assert "url:" not in qa_values
    assert "secret:" not in qa_values
    assert "kustomization:" not in qa_values
    assert '--expected-branch "${QA_BRANCH}"' in text


def test_standard_make_validation_requires_pinned_helm_render() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = makefile[makefile.index("validate-flux-sync-values:"):]
    assert "tests/validate-flux-sync-values.py --helm-render" in recipe
    validator = (ROOT / "tests/validate-flux-sync-values.py").read_text(encoding="utf-8")
    main = validator[validator.index('if __name__ == "__main__":'):]
    assert main.index("run_all_contract_checks()") < main.index(
        "test_helm_1146_render_matches_generated_sync_resource_contract()"
    )


def test_contract_check_runner_propagates_failure() -> None:
    validator = ROOT / "tests/validate-flux-sync-values.py"
    spec = importlib.util.spec_from_file_location("validate_flux_sync_values", validator)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fail() -> None:
        raise RuntimeError("sentinel contract failure")

    fail.__name__ = module.CONTRACT_CHECKS[0].__name__
    checks = (fail, *module.CONTRACT_CHECKS[1:])
    with pytest.raises(RuntimeError, match="sentinel contract failure"):
        module.run_all_contract_checks(checks)


def test_manifest_ci_installs_pinned_helm_and_runs_standard_validation() -> None:
    workflow = MANIFEST_WORKFLOW.read_text(encoding="utf-8")
    assert "azure/setup-helm@b9e51907a09c216f16ebe8536097933489208112" in workflow
    assert "version: v3.16.4" in workflow
    assert "run: make validate-flux-sync-values" in workflow


def test_guardrails_reject_shared_names_and_protected_branches() -> None:
    text = source()
    for token in ("kind-dev-misc-local", "kubecrate-fix-eso", "main", "master", "default"):
        assert token in text
    assert text.count("assert_context") >= 7


def test_kind_name_constraint_is_checked_before_remote_or_cluster_mutation() -> None:
    text = source()
    validation = '[[ "${CLUSTER}" =~ ^[a-z0-9.-]+$ ]]'
    ordered(
        text,
        validation,
        'final_qa_helpers.py create-ref',
        'kind create cluster --name "${CLUSTER}"',
    )
    assert text.index(validation) < text.index("scripts/preflight-flux-deploy-key.py")


def test_preexisting_identity_checks_are_fail_closed_and_precede_mutation() -> None:
    text = source()
    ordered(
        text,
        'if test "$(cluster_state)" != absent',
        'final_qa_helpers.py create-ref',
        'kind create cluster --name "${CLUSTER}"',
    )

    assert "QA cluster exists or absence could not be proved" in text
    assert "GitHub create-ref API is atomic" in text


def test_mutating_cluster_commands_use_explicit_context_and_guards() -> None:
    text = source()
    mutation_fragments = (
        'helm upgrade --install flux-system',
        'kubectl --context "${CONTEXT}" apply -f -',
        'flux --context "${CONTEXT}" reconcile source git',
        'flux --context "${CONTEXT}" reconcile kustomization "${SYNC_NAME}"',
        'flux --context "${CONTEXT}" suspend kustomization',
        'kubectl --context "${CONTEXT}" delete externalsecret',
        'final_qa_helpers.py restore --context "${CONTEXT}"',
    )
    for fragment in mutation_fragments:
        position = text.index(fragment)
        assert "assert_context" in text[max(0, position - 240):position], fragment
    assert '--kube-context "${CONTEXT}"' in text


def test_created_deploy_key_is_validated_before_readback_and_cleanup_is_fail_closed() -> None:
    text = source()
    run = text[text.index('kubectl --context "${CONTEXT}" apply -f -'):]
    ordered(
        run,
        'kubectl --context "${CONTEXT}" apply -f -',
        'wait_for_flux_identity',
        'final_qa_helpers.py create-deploy-key',
        'kubectl --context "${CONTEXT}" wait --for=condition=Ready "helmrelease/${SYNC_NAME}"',
        'flux --context "${CONTEXT}" reconcile source git',
    )
    sync_wait = 'kubectl --context "${CONTEXT}" wait --for=condition=Ready "helmrelease/${SYNC_NAME}"'
    assert run.index(sync_wait) > run.index('final_qa_helpers.py create-deploy-key')
    assert 'final_qa_helpers.py cleanup-deploy-key-markers' in text
    assert 'final_qa_helpers.py cleanup-ref-markers' in text
    assert 'test "$(cluster_state)" = absent || cleanup_failed=true' in text


def test_identity_wait_is_bounded_private_and_context_guarded() -> None:
    text = source()
    wait = text[text.index("wait_for_flux_identity()") : text.index("protected_branch()")]
    assert 'KUBECRATE_QA_IDENTITY_TIMEOUT' in wait
    assert 'KUBECRATE_QA_IDENTITY_POLL_INTERVAL' in wait
    assert 'assert_context' in wait
    assert '-o json' in wait
    assert 'extract-public-key' in wait
    assert 'jsonpath=' not in wait
    assert "identity public key was not generated before timeout" in wait
    assert 'write-public-key' in text
    assert '>"${EVIDENCE}/private/identity.pub"' not in text


def test_green_red_green_captures_json_and_real_browser_ui() -> None:
    text = source()
    run = text[text.index('capture_green "baseline"'):]
    ordered(
        run,
        'capture_green "baseline"',
        'controlled_red',
        'capture_red',
        'restore_if_needed',
    )
    assert "status.json" in text
    assert "--headless" in text
    assert "EXPECTED_CHECKS=7" in text
    assert "restore_if_needed" in text
    assert text.index("capture_red", text.index('capture_green "baseline"')) < text.index(
        "restore_if_needed", text.index('capture_green "baseline"')
    )


def test_cleanup_trap_verifies_exact_key_branch_and_cluster_absence() -> None:
    text = source()
    assert "trap cleanup EXIT" in text
    for token in (
        'cleanup-deploy-key-markers',
        'final_qa_helpers.py cleanup-ref-markers',
        'kind delete cluster --name "${CLUSTER}"',
        "cleanup verification failed",
    ):
        assert token in text


def test_make_wrapper_delegates_to_authoritative_script() -> None:
    make = MAKEFILE.read_text(encoding="utf-8")
    assert "final-qa-exact-tree:" in make
    assert "scripts/final-qa-exact-tree.sh" in make
