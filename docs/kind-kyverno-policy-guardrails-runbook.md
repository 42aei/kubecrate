# Kind Kyverno policy guardrails runbook

This runbook describes the Kyverno vertical slice on the kind-first local path. Kyverno is a platform service reconciled through GitOps-managed operation in `core-kyverno`; the labeled namespace fixture is an application service consumer.

The kind-first local path consumes Kyverno through the reusable Vanilla composition at `compositions/vanilla/entrypoint/`; it no longer owns a separate kind-local Kyverno service binding.

## Bounded contract

The single `require-ns-label` ClusterPolicy enforces `kubecrate.io/validated: "true"` only for namespaces named `kyverno-smoke-*`. The narrow match keeps the proof isolated from existing platform services and application services. CrateCheck remains the single status surface and adds three checks:

- `kyverno-helmrelease-ready`
- `kyverno-clusterpolicy-ready`
- `kyverno-smoke-namespace-exists`

The repository runner performs the operational proof. It preserves the durable Flux `main` default and supports the existing exact PR-head and exact current-main identity modes.

## Disposable exact-candidate validation

Do not target the shared `kind-dev-misc-local` cluster. After the candidate is pushed and a PR exists, run the existing disposable-cluster command with the exact candidate identity:

```sh
KUBECRATE_PR_BRANCH=<candidate-branch> \
KUBECRATE_PR_NUMBER=<pr-number> \
KUBECRATE_EXPECTED_COMMIT=<exact-40-character-sha> \
scripts/direct-kind-flux-e2e.sh
```

The runner verifies the active disposable context before mutation, renders the existing entrypoint with a runtime-only source override, and proves:

1. the Kyverno controller, smoke policy, and consumer fixture Flux units become Ready in dependency order;
2. `kyverno-smoke-allowed` exists with the required label, proving a real allowed admission;
3. creating `kyverno-smoke-denied` without the label fails and includes the exact reason `Namespace requires kubecrate.io/validated=true`;
4. the complete CrateCheck `/status.json` contract is green;
5. after suspending the policy Flux unit and deleting only `require-ns-label`, exactly `kyverno-clusterpolicy-ready` is red while every unrelated check remains green;
6. Flux restores the policy and the complete JSON contract returns to green;
7. the exact disposable cluster is deleted, with bounded sanitized failure evidence retained only on failure.

The runner intentionally does not add browser or UI acceptance for this slice.

## Static validation

Before live QA, run:

```sh
python3 scripts/validate-kubernetes-manifests.py
python3 tests/validate-cratecheck.py --render
pytest -q
openspec validate introduce-kyverno-policy-guardrails \
  --type change --strict --json --no-interactive
git diff --check
```

Static validation does not replace the disposable runtime proof. Final QA must also inspect the intended context, nodes, Flux resources, controller/workload health, and recent relevant events or logs before returning a pass.
