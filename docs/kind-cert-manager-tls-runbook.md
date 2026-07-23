# kind cert-manager TLS runbook

This runbook validates the cert-manager vertical slice on the kind-first local path. cert-manager runs as a GitOps-managed platform service in `core-cert-manager`; CrateCheck remains the generic application service validation surface.

The kind-first local path consumes cert-manager through the reusable Vanilla composition at `compositions/vanilla/entrypoint/`; it no longer owns a separate kind-local cert-manager service binding.

## Scope

The local-only issuer chain is:

1. `ClusterIssuer/kubecrate-local-selfsigned` issues `Certificate/cratecheck-local-ca` in `core-cert-manager`.
2. `ClusterIssuer/kubecrate-local-ca` uses that CA Secret.
3. `Certificate/cratecheck-tls` issues `Secret/cratecheck-tls` in `cratecheck` for `cratecheck.local`.
4. Envoy Gateway terminates HTTPS with that Secret and routes to CrateCheck.

This does not add public ACME, DNS-01, production issuer policy, external PKI, or browser acceptance.

## Static validation

```sh
kustomize build clusters/kind-dev-misc-local/entrypoint >/tmp/kubecrate-entrypoint.yaml
python3 scripts/validate-kubernetes-manifests.py
python3 -m pytest -q tests/test_cert_manager_tls_contract.py tests/test_validate_cratecheck_status.py
openspec validate introduce-cert-manager-certificate-management --type change --strict --json --no-interactive
```

## Disposable-cluster validation

Use the direct runner against the exact pushed QA branch and commit. It refuses a remote mismatch, creates its own disposable kind cluster, proves the active context, and deletes the exact cluster on exit.

```sh
KUBECRATE_PR_BRANCH=<exact-qa-branch> \
KUBECRATE_PR_NUMBER=<pr-number> \
KUBECRATE_EXPECTED_COMMIT=<full-commit-sha> \
./scripts/direct-kind-flux-e2e.sh
```

To validate an already merged PR at exact current `main`, select the explicit
identity mode. This also requires the referenced PR to be closed and merged with
the expected commit as its merge commit, and makes Flux reconcile `main`:

```sh
KUBECRATE_E2E_IDENTITY_MODE=current-main \
KUBECRATE_PR_NUMBER=<merged-pr-number> \
KUBECRATE_EXPECTED_COMMIT=<full-main-commit-sha> \
./scripts/direct-kind-flux-e2e.sh
```

The cert-manager phase waits for both Flux Kustomizations, extracts only `ca.crt` into a private temporary directory, and verifies HTTPS with hostname and CA validation:

```sh
curl --fail --cacert "$CA_FILE" \
  --resolve cratecheck.local:10443:127.0.0.1 \
  https://cratecheck.local:10443/status.json
```

`/status.json` is authoritative. The runner requires every ESO, Envoy, cert-manager, and CrateCheck check to be green.

## Controlled red and restore

Only run mutations on the runner-created disposable cluster. The bounded scenario:

1. suspends `Kustomization/cert-manager-local-issuer`;
2. deletes `Certificate/cratecheck-tls` while retaining its issued Secret so Envoy and trusted HTTPS remain healthy;
3. immediately reads CrateCheck through its direct port-forward;
4. requires exactly `cert-manager-tls-certificate-ready` to be red while the TLS Secret, Envoy, trusted HTTPS, and every unrelated check stay green;
5. resumes and reconciles the Kustomization;
6. waits for certificate readiness;
7. re-reads the restored CA and proves trusted HTTPS plus all-green JSON.

The EXIT trap resumes/reconciles a suspended issuer Kustomization before deleting the exact disposable cluster. Runtime key and certificate material is never committed or printed.
