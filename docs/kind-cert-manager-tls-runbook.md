# kind cert-manager TLS validation runbook

This runbook validates the cert-manager certificate management slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled.

## Scope

The slice proves TLS certificate issuance through a local self-signed CA chain: a self-signed ClusterIssuer issues a CA Certificate, which backs a CA ClusterIssuer that issues an end-entity TLS Certificate for CrateCheck. It does not install public ACME, DNS-01, production issuer policy, multi-environment certificate strategy, or a service-specific status app.

## Local access model

The kind config maps:

- host `127.0.0.1:10443` to Envoy Gateway HTTPS node port `30443`

The local TLS hostname is `cratecheck.local`. Public DNS is not required; use `curl --resolve` or an equivalent local host mapping. Existing kind clusters must be recreated before the HTTPS host port is available.

## Evidence commands

Confirm the intended context before inspecting or mutating anything:

```sh
kubectl config current-context
kubectl --context kind-kind-dev-misc-local get nodes
```

After GitOps-managed operation reconciles this branch, inspect cert-manager and the local issuer path:

```sh
flux --context kind-kind-dev-misc-local get kustomizations -n flux-system
kubectl --context kind-kind-dev-misc-local -n core-cert-manager get deployments,pods
kubectl --context kind-kind-dev-misc-local get clusterissuers.cert-manager.io
kubectl --context kind-kind-dev-misc-local -n cratecheck get certificates.cert-manager.io,secrets cratecheck-local-ca cratecheck-tls
```

Verify the CA Certificate has issued:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck get secret cratecheck-local-ca -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | head -20
```

Verify the TLS Certificate has issued:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck get secret cratecheck-tls -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | head -20
```

Assert CrateCheck cert-manager checks are green:

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
sleep 2
curl -s http://localhost:8080/status.json | python3 -c '
import json,sys
payload = json.load(sys.stdin)
checks = {c["id"]: c for c in payload["checks"]}
cm_ids = ["cert-manager-helmrelease-ready", "cert-manager-selfsigned-issuer-ready",
          "cert-manager-ca-certificate-ready", "cert-manager-ca-issuer-ready",
          "cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
for cid in cm_ids:
    if cid in checks:
        c = checks[cid]
        print(f"{c['state']:>6} {cid}: {c.get('summary', '')}")
'
kill %1 2>/dev/null
```

## Controlled red test

Only run this on an authorized disposable QA cluster or with explicit approval for the exact target.

A reversible red test is to temporarily delete the TLS Certificate, verify CrateCheck reports `cert-manager-tls-certificate-ready` and `cert-manager-tls-secret-exists` as non-green, then restore the Certificate resource and verify green again.

Do not claim final success from static rendering alone. Capture context, Flux status, cert-manager resources, issuer/certificate readiness, TLS Secret existence, CrateCheck `/status.json`, and red-test evidence.
