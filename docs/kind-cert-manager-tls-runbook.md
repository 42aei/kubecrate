# kind cert-manager TLS validation runbook

This runbook validates the cert-manager certificate management slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled.

## Scope

The slice proves TLS certificate issuance through a local self-signed CA chain: a self-signed ClusterIssuer issues a CA Certificate in `core-cert-manager`, which backs a CA ClusterIssuer that issues an end-entity TLS Certificate for CrateCheck. The CA Certificate Secret is created in `core-cert-manager` so the CA ClusterIssuer can read it through cert-manager's `--cluster-resource-namespace` setting. It does not install public ACME, DNS-01, production issuer policy, multi-environment certificate strategy, TLS termination on a Gateway/Route, or a service-specific status app.

## Local access model

The kind config defines a minimal single-control-plane cluster with no pre-provisioned port mappings. Certificate validation uses `kubectl` inspection and CrateCheck `/status.json`; HTTPS termination through an ingress Gateway is deferred.

## QA source / branch override

To reconcile a disposable QA cluster against this exact candidate branch instead of the shared default branch, patch the Flux `GitRepository` source after bootstrap:

```sh
# After bootstrap, override the GitRepository branch to the candidate
kubectl --context "kind-${QA_CLUSTER}" -n flux-system patch gitrepository flux-system --type merge \
  -p '{"spec":{"ref":{"branch":"kubecrate/cratecheck-restack-cert-manager"}}}'

# Reconcile so Flux picks up the branch change
flux --context "kind-${QA_CLUSTER}" reconcile source git flux-system -n flux-system --timeout 180s
flux --context "kind-${QA_CLUSTER}" reconcile kustomization flux-system -n flux-system --timeout 180s
```

Verify the override took effect:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n flux-system get gitrepository flux-system -o jsonpath='{.spec.ref.branch}'
```

Return the source to the default branch after QA evidence is captured:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n flux-system patch gitrepository flux-system --type merge \
  -p '{"spec":{"ref":{"branch":"main"}}}'
flux --context "kind-${QA_CLUSTER}" reconcile source git flux-system -n flux-system --timeout 180s
```

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
kubectl --context kind-kind-dev-misc-local -n core-cert-manager get certificates.cert-manager.io cratecheck-local-ca
kubectl --context kind-kind-dev-misc-local -n cratecheck get certificates.cert-manager.io,secrets cratecheck-tls
```

Verify the CA Certificate has issued:

```sh
kubectl --context kind-kind-dev-misc-local -n core-cert-manager get secret cratecheck-local-ca -o jsonpath='{.data.tls\\.crt}' | base64 -d | openssl x509 -text -noout | head -20
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

The red test verifies that CrateCheck detects cert-manager path breakage and recovers after restoration. Because Flux GitOps reconciliation will immediately restore deleted resources, the test suspends the local issuer Kustomization first.

### 1. Verify all cert-manager checks are green (pre-red baseline)

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
all_green = True
for cid in cm_ids:
    if cid in checks:
        c = checks[cid]
        is_green = c["state"] == "green"
        if not is_green:
            all_green = False
        print(f"{c[\"state\"]:>6} {cid}: {c.get(\"summary\", \"\")}")
if not all_green:
    print("PRE-RED BASELINE FAILED: not all cert-manager checks are green")
    sys.exit(1)
'
kill %1 2>/dev/null
```

### 2. Suspend the cert-manager-local-issuer Flux Kustomization

This prevents Flux from immediately reconciling the deleted Certificate:

```sh
flux --context kind-kind-dev-misc-local suspend kustomization cert-manager-local-issuer -n flux-system
```

### 3. Delete the TLS Certificate to trigger red state

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck delete certificate cratecheck-tls
```

### 4. Verify CrateCheck reports red for the TLS Certificate checks

```sh
kubectl --context kind-kind-dev-misc-local -n cratecheck port-forward svc/cratecheck 8080:8080 &
sleep 2
curl -s http://localhost:8080/status.json | python3 -c '
import json,sys
payload = json.load(sys.stdin)
checks = {c["id"]: c for c in payload["checks"]}
for cid in ["cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]:
    if cid in checks:
        c = checks[cid]
        is_red = c["state"] != "green"
        print(f"{c[\"state\"]:>6} {cid}: {c.get(\"summary\", \"\")} (red expected={is_red})")
'
kill %1 2>/dev/null
```

Also capture UI evidence: open `http://localhost:8080/` in a browser while the port-forward is active and screenshot the red cert-manager rows.

### 5. Resume the Kustomization to restore green state

```sh
flux --context kind-kind-dev-misc-local resume kustomization cert-manager-local-issuer -n flux-system
flux --context kind-kind-dev-misc-local reconcile kustomization cert-manager-local-issuer -n flux-system --timeout 180s
```

### 6. Verify CrateCheck returns to green

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
all_green = True
for cid in cm_ids:
    if cid in checks:
        c = checks[cid]
        is_green = c["state"] == "green"
        if not is_green:
            all_green = False
        print(f"{c[\"state\"]:>6} {cid}: {c.get(\"summary\", \"\")}")
if not all_green:
    print("RESTORE GREEN FAILED: not all cert-manager checks returned to green")
    sys.exit(1)
'
kill %1 2>/dev/null
```

Also capture UI evidence: open `http://localhost:8080/` in a browser while the port-forward is active and screenshot the green cert-manager rows.

Do not claim final success from static rendering alone. Capture context, Flux status, cert-manager resources, issuer/certificate readiness, TLS Secret existence, CrateCheck `/status.json`, UI screenshots, and the full green→red→restore-green evidence cycle.
