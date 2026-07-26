# Retained local demo

## Run

Prerequisites: Linux or macOS, Docker, `git`, `kind`, `kubectl`, `kustomize`, `helm`, `flux`, `curl`, `python3`, `base64`, `timeout`, and `make`. Ports `10080` and `10443` must be free.

From a clean branch whose `HEAD` is available from its remote using your normal Git credentials:

```sh
make local-check
make local-up
```

`local-up` creates or reuses the `kubecrate-local` kind cluster, bootstraps Flux with the existing SSH deploy-key flow, reconciles the exact checked-out commit after deploy-key registration, waits for the stack to become green, and leaves the cluster running.

## Open the demo

- UI: <http://127.0.0.1:10080/>
- JSON: <http://127.0.0.1:10080/status.json>
- HTTPS JSON: `https://cratecheck.local:10443/status.json`

Verify HTTPS with the generated local CA:

```sh
curl --fail \
  --cacert .tmp/kubecrate-local/cratecheck-ca.crt \
  --resolve cratecheck.local:10443:127.0.0.1 \
  https://cratecheck.local:10443/status.json
```

## Inspect

```sh
make local-status
make local-evidence
```

`local-status` is read-only and exits non-zero unless the cluster, Flux revision, platform services, application service, HTTP, and HTTPS checks are green.

The latest sanitized evidence is in `.tmp/kubecrate-local/evidence/latest/`. Its machine-readable entrypoint is `summary.json` with schema `kubecrate.retained-demo.evidence/v1`.

For direct inspection, use the recorded context:

```sh
kubectl --context kind-kubecrate-local get pods -A
flux --context kind-kubecrate-local get all -A
```

## Recover

Restart the existing kind nodes and rerun status checks:

```sh
make local-restart
```

Delete and rebuild the recorded demo cluster:

```sh
make local-recreate
```

After a failed `local-up`, the cluster and sanitized evidence are retained for inspection. Recreate is destructive only for the recorded demo-owned cluster.

## Stop

```sh
make local-down
```

`local-down` deletes only the recorded demo-owned cluster, proves it is absent, and retains the latest evidence.

## Source and cluster overrides

The workflow requires a clean checkout and an exact remote branch match before creating a cluster. By default this preflight uses your current Git credentials only to prove that the selected remote/ref advertises the exact checked-out commit; those credentials are not copied into the cluster.

Flux authenticates to the GitOps source through the existing `flux2-sync` SSH deploy-key flow. Bootstrap creates `Secret/flux-system-sync` with generated SSH identity material, prints the generated public key from `identity.pub`, and waits for GitOps readiness after you register that public key as a deploy key with the Git provider. The private key remains in-cluster.

For a future anonymously readable public fork or source, explicitly opt into anonymous mode:

```sh
KUBECRATE_LOCAL_SOURCE_URL=https://github.com/you/kubecrate.git \
KUBECRATE_LOCAL_SOURCE_REF=my-branch \
KUBECRATE_LOCAL_ANONYMOUS_SOURCE=1 \
make local-check
```

Anonymous mode renders Flux without a Git credential Secret. It is for future public sources only and is not the current private-repository default.

Use `KUBECRATE_LOCAL_CLUSTER=kubecrate-local-<name>` with every lifecycle command to select another demo-owned cluster name. Multiple retained demos cannot run concurrently because the host ports are fixed.

Lifecycle behavior is implemented in [`scripts/local-demo.sh`](../scripts/local-demo.sh). The destructive direct QA runner is separate.
