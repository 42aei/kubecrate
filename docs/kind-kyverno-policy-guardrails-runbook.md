# Kind Kyverno policy guardrails runbook

Kyverno runs as a GitOps-managed platform service in `core-kyverno`, reconciled through the
reusable Vanilla composition at `compositions/vanilla/entrypoint/`. The kind-first local path
no longer owns a separate kind-local Kyverno service binding.

The policy vertical-slice proof — the `require-ns-label` ClusterPolicy fixture, the labeled
`kyverno-smoke-allowed` Namespace consumer fixture, and the CrateCheck status surface that
evaluates them — is consumer-side validation. It lives in the smoke suite at
[42aei/kubecrate-kind-smoke](https://github.com/42aei/kubecrate-kind-smoke):

- `platform-services/kyverno/policy/` holds the single `require-ns-label` ClusterPolicy, which
  enforces `kubecrate.io/validated: "true"` only for namespaces named `kyverno-smoke-*` with
  the denial message `Namespace requires kubecrate.io/validated=true`.
- `platform-services/kyverno/consumer/` holds the labeled `kyverno-smoke-allowed` Namespace,
  a real allowed admission proof.
- `scripts/kind-smoke-e2e.sh` and the invokable `kind-smoke` workflow prove the slice end to
  end on a disposable kind cluster against a pinned kubecrate commit, including the
  controlled-red `kyverno-clusterpolicy-ready` phase through CrateCheck `/status.json`.

## Static validation

```sh
python3 scripts/validate-kubernetes-manifests.py
python3 tests/validate-vanilla-composition.py
```

## Runtime validation

Validate a kubecrate substrate change against the smoke suite, locally or via its
`workflow_dispatch` kind CI:

```sh
git clone https://github.com/42aei/kubecrate-kind-smoke.git
cd kubecrate-kind-smoke
KUBECRATE_REF=<full-kubecrate-commit-sha> ./scripts/kind-smoke-e2e.sh
```

The smoke flow reconciles the pinned kubecrate Vanilla entrypoint plus the smoke fixtures and
requires every Kyverno CrateCheck check (`kyverno-helmrelease-ready`,
`kyverno-clusterpolicy-ready`, `kyverno-smoke-namespace-exists`) to be green before and after
its controlled-red scenario. See the smoke repository README for the full contract.
