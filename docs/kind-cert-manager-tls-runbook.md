# kind cert-manager TLS validation runbook

This runbook validates the cert-manager certificate management slice on the kind-first local path. It assumes the Flux/bootstrap slice is already reconciled.

## Scope

The slice proves TLS certificate issuance through a local self-signed CA chain: a self-signed ClusterIssuer issues a CA Certificate in `core-cert-manager`, which backs a CA ClusterIssuer that issues an end-entity TLS Certificate for CrateCheck. The CA Certificate Secret is created in `core-cert-manager` so the CA ClusterIssuer can read it through cert-manager's `--cluster-resource-namespace` setting. It does not install public ACME, DNS-01, production issuer policy, multi-environment certificate strategy, TLS termination on a Gateway/Route, or a service-specific status app.

## Local access model

The kind config defines a minimal single-control-plane cluster with no pre-provisioned port mappings. Certificate validation uses `kubectl` inspection and CrateCheck `/status.json`; HTTPS termination through an ingress Gateway is deferred.

## QA source / branch override

To reconcile a disposable QA cluster against this exact candidate branch instead of the shared default branch, pass `FLUX_GIT_BRANCH_OVERRIDE` at bootstrap time:

```sh
make kind-dev-misc-local-bootstrap FLUX_GIT_BRANCH_OVERRIDE=kubecrate/cratecheck-restack-cert-manager
```

This injects the branch into the Flux HelmRelease at install time, so the `GitRepository` first reconciles the candidate rather than the default branch. No post-bootstrap patch is required.

The committed default value for `FLUX_GIT_BRANCH` is `pivot/flux-sync-ssh-bootstrap`. The override mechanism is a Makefile variable that sets the Helm `git.branch` value; it is not Makefile-only authoritative orchestration — the authoritative Helm value path is `clusters/kind-dev-misc-local/platform-services/flux/helm-values.yaml` with the branch parameter.

Verify the override took effect:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n flux-system get gitrepository flux-system -o jsonpath='{.spec.ref.branch}' && echo
```

Confirm the exact commit revision:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n flux-system get gitrepository flux-system -o jsonpath='{.status.artifact.revision}' && echo
```

## Evidence commands

Confirm the intended context before inspecting or mutating anything:

```sh
QA_CLUSTER="${QA_CLUSTER:-kind-dev-misc-local}"
kubectl config current-context
kubectl --context "kind-${QA_CLUSTER}" get nodes
```

After GitOps-managed operation reconciles this branch, inspect cert-manager and the local issuer path:

```sh
flux --context "kind-${QA_CLUSTER}" get kustomizations -n flux-system
kubectl --context "kind-${QA_CLUSTER}" -n core-cert-manager get deployments,pods
kubectl --context "kind-${QA_CLUSTER}" get clusterissuers.cert-manager.io
kubectl --context "kind-${QA_CLUSTER}" -n core-cert-manager get certificates.cert-manager.io cratecheck-local-ca
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck get certificates.cert-manager.io,secrets cratecheck-tls
```

Verify the CA Certificate has issued:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n core-cert-manager get secret cratecheck-local-ca -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | head -20
```

Verify the TLS Certificate has issued:

```sh
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck get secret cratecheck-tls -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | head -20
```

Assert CrateCheck cert-manager checks are green:

```sh
# Start port-forward once and keep alive for the entire evidence session
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck port-forward svc/cratecheck 8080:8080 &
PF_PID=$!
sleep 2

python3 << 'PYEOF'
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c["id"]: c for c in payload["checks"]}
cm_ids = ["cert-manager-helmrelease-ready", "cert-manager-selfsigned-issuer-ready",
          "cert-manager-ca-certificate-ready", "cert-manager-ca-issuer-ready",
          "cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
all_green = True
for cid in cm_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  MISSING {cid}: check not found in status payload")
        all_green = False
        continue
    is_green = c["state"] == "green"
    if not is_green:
        all_green = False
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')}")
if not all_green:
    print("BASELINE FAILED: not all cert-manager checks are green")
    sys.exit(1)
else:
    print("BASELINE OK: all cert-manager checks are green")
PYEOF
```

## Controlled red test

Only run this on an authorized disposable QA cluster or with explicit approval for the exact target.

The red test verifies that CrateCheck detects cert-manager path breakage and recovers after restoration. Because Flux GitOps reconciliation will immediately restore deleted resources, the test suspends the local issuer Kustomization first.

The red mutation deletes both the TLS Certificate and its Secret so that BOTH the certificate-readiness check and the secret-existence check go red. Deleting only the Certificate leaves the Secret behind (cert-manager does not garbage-collect the Secret on Certificate deletion), which would falsely keep the secret-existence check green.

The port-forward started in the baseline section remains active throughout. Do not kill it until the final step.

### 1. Verify all cert-manager checks are green (pre-red baseline)

Already verified in the evidence section above. All six cert-manager check IDs must show `green`.

### 2. Suspend the cert-manager-local-issuer Flux Kustomization

This prevents Flux from immediately reconciling the deleted resources:

```sh
flux --context "kind-${QA_CLUSTER}" suspend kustomization cert-manager-local-issuer -n flux-system
```

### 3. Delete both the TLS Certificate and TLS Secret to trigger red state

```sh
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck delete certificate cratecheck-tls
kubectl --context "kind-${QA_CLUSTER}" -n cratecheck delete secret cratecheck-tls
```

### 4. Wait for CrateCheck to detect the breakage, then verify red state

CrateCheck polls every 30 seconds. Wait for two intervals to ensure an updated evaluation:

```sh
echo "Waiting for CrateCheck to detect breakage (polling every 30s)..."
sleep 65
```

Verify both checks are non-green (red or yellow or missing):

```sh
python3 << 'PYEOF'
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c["id"]: c for c in payload["checks"]}
red_ids = ["cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
all_red = True
for cid in red_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  MISSING {cid}: check not found in status payload (implicitly non-green)")
        continue
    is_red = c["state"] != "green"
    if not is_red:
        all_red = False
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')} (expected non-green={is_red})")
if not all_red:
    print("RED TEST FAILED: expected non-green for both TLS checks")
    sys.exit(1)
else:
    print("RED TEST OK: both TLS checks are non-green")
PYEOF
```

Also capture UI evidence: open `http://localhost:8080/` in a browser while the port-forward is active and screenshot the red cert-manager rows.

Note: other cert-manager checks (helmrelease-ready, selfsigned-issuer-ready, ca-certificate-ready, ca-issuer-ready) should remain green — only the two TLS checks should be red.

### 5. Resume the Kustomization to restore green state

```sh
flux --context "kind-${QA_CLUSTER}" resume kustomization cert-manager-local-issuer -n flux-system
flux --context "kind-${QA_CLUSTER}" reconcile kustomization cert-manager-local-issuer -n flux-system --timeout 180s
```

### 6. Wait and verify CrateCheck returns to green

Wait for cert-manager to issue the new certificate and CrateCheck to detect it:

```sh
echo "Waiting for cert-manager to issue new certificate and CrateCheck to detect it..."
sleep 65
```

Verify all six checks are green again:

```sh
python3 << 'PYEOF'
import json, sys, urllib.request
payload = json.loads(urllib.request.urlopen('http://localhost:8080/status.json').read())
checks = {c["id"]: c for c in payload["checks"]}
cm_ids = ["cert-manager-helmrelease-ready", "cert-manager-selfsigned-issuer-ready",
          "cert-manager-ca-certificate-ready", "cert-manager-ca-issuer-ready",
          "cert-manager-tls-certificate-ready", "cert-manager-tls-secret-exists"]
all_green = True
for cid in cm_ids:
    c = checks.get(cid)
    if c is None:
        print(f"  MISSING {cid}: check not found in status payload")
        all_green = False
        continue
    is_green = c["state"] == "green"
    if not is_green:
        all_green = False
    print(f"{c['state']:>6} {cid}: {c.get('summary', '')}")
if not all_green:
    print("RESTORE GREEN FAILED: not all cert-manager checks returned to green")
    sys.exit(1)
else:
    print("RESTORE GREEN OK: all cert-manager checks returned to green")
PYEOF
```

Also capture UI evidence: open `http://localhost:8080/` in a browser while the port-forward is active and screenshot the green cert-manager rows.

### 7. Clean up port-forward

```sh
kill $PF_PID 2>/dev/null
```

Do not claim final success from static rendering alone. Capture context, Flux status, cert-manager resources, issuer/certificate readiness, TLS Secret existence, CrateCheck `/status.json`, UI screenshots, and the full green→red→restore-green evidence cycle.
