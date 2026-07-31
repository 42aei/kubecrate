# kind cert-manager TLS runbook

cert-manager runs as a GitOps-managed platform service in `core-cert-manager`, reconciled
through the reusable Vanilla composition at `compositions/vanilla/entrypoint/`. The kind-first
local path no longer owns a separate kind-local cert-manager service binding.

The cert-manager vertical-slice proof — the local issuer chain, the `cratecheck-tls`
Certificate, the Envoy smoke HTTPS path, and the CrateCheck status surface that evaluates them —
is consumer-side validation. It lives in the smoke suite at
[42aei/kubecrate-kind-smoke](https://github.com/42aei/kubecrate-kind-smoke):

- `platform-services/cert-manager/local-issuer/` holds the issuer chain:
  `ClusterIssuer/kubecrate-local-selfsigned` issues `Certificate/cratecheck-local-ca` in
  `core-cert-manager`, `ClusterIssuer/kubecrate-local-ca` uses that CA Secret, and
  `Certificate/cratecheck-tls` issues `Secret/cratecheck-tls` in `cratecheck` for
  `cratecheck.local`, which the Envoy smoke Gateway terminates.
- `scripts/kind-smoke-e2e.sh` and the invokable `kind-smoke` workflow prove the chain end to
  end on a disposable kind cluster against a pinned kubecrate commit, including the
  controlled-red `cert-manager` phase through CrateCheck `/status.json`.

This repository intentionally does not carry public ACME, DNS-01, production issuer policy,
external PKI, or browser acceptance fixtures.

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

The smoke flow renders a private disposable cluster, reconciles the pinned kubecrate Vanilla
entrypoint plus the smoke fixtures, and requires every cert-manager CrateCheck check
(`cert-manager-helmrelease-ready`, `cert-manager-selfsigned-issuer-ready`,
`cert-manager-ca-certificate-ready`, `cert-manager-ca-issuer-ready`,
`cert-manager-tls-certificate-ready`, `cert-manager-tls-secret-exists`) to be green before and
after its controlled-red scenario. See the smoke repository README for the full contract.
