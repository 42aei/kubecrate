# Retained local demo

This is the supported public demo for Kubecrate's kind-first local path. It creates a named kind cluster, performs bootstrap installation of Flux, enters GitOps-managed operation at the exact public Git commit you checked out, proves the complete current stack is green, and leaves the cluster running for inspection. It uses no GitHub CLI, token, deploy key, Doppler secret, private image, or organization setting.

The demo is production-inspired, not production-ready. It is a local reference path, not the cluster-provider agnostic `point at a cluster and install` product boundary. The destructive controlled-red QA runner is separate and is not invoked here.

## Supported prerequisites

- Linux or macOS with a running Docker daemon
- `git`, `kind`, `kubectl`, `kustomize`, `helm`, `flux`, `curl`, `python3`, `base64`, `timeout`, and `make`
- enough Docker capacity for a two-node kind cluster and the platform services
- host ports `10080` and `10443` available
- anonymous outbound access to GitHub, GHCR, and the public Helm/chart repositories used by the manifests

Use current stable tool releases. The repository pins chart versions where the stack requires repeatability; it does not install host tools for you.

## Clone upstream or use a public fork

Clone an anonymously readable repository and select a pushed branch whose head is the exact commit you will run:

```sh
git clone https://github.com/42aei/kubecrate.git
cd kubecrate
git switch main
```

For a public fork, clone the fork instead. The workflow derives the public HTTPS source from `origin` and the selected ref from the current branch. If your checkout layout is unusual, supply runtime-only overrides:

```sh
KUBECRATE_LOCAL_SOURCE_URL=https://github.com/you/kubecrate.git \
KUBECRATE_LOCAL_SOURCE_REF=my-public-branch \
make local-check
```

Overrides are not written into tracked files. Detached HEADs require `KUBECRATE_LOCAL_SOURCE_REF`. Local-only commits and dirty worktrees are intentionally refused because Flux cannot reconcile their exact contents.

## Preflight

```sh
make local-check
```

Preflight checks host tools, Docker, a clean checkout, public source derivation, anonymous Git access, and exact equality between local `HEAD` and the selected remote branch. The anonymous remote query runs with isolated Git configuration, credentials, askpass, HOME, and netrc state while retaining normal public TLS verification. These source checks complete before any kind cluster creation. A failure prints `phase=...`, preserves the useful command exit status, and names exact recovery commands. Existing ownership state is not rewritten and evidence is not replaced for dirty, inaccessible-source, or render preflight failures.

The default retained cluster is `kubecrate-local` with context `kind-kubecrate-local`. A different demo-owned name can be selected for every lifecycle command with `KUBECRATE_LOCAL_CLUSTER=<name>`, but it must be `kubecrate-local` or `kubecrate-local-<lowercase-alphanumeric-segment>` (additional hyphen-separated segments are allowed). Every command validates this restrictive identity before state writes, kind inventory, Docker, Kubernetes, Helm, Flux, or deletion. Protected, ambiguous, and unrelated names are refused. Because the endpoint ports are fixed, running multiple retained demos concurrently is not supported.

## Bring it up and wait for green

```sh
make local-up
```

Up creates the named persistent kind cluster when absent, waits with bounded timeouts, installs Flux through the existing Helm bootstrap path, renders the existing entrypoint with anonymous HTTPS Git access, and reconciles the exact selected commit. It validates:

- Flux controllers, exact GitRepository artifact revision, root sync, and every child Kustomization
- External Secrets Operator and its projected-secret smoke consumer
- Envoy Gateway, Gateway API resources, and the host ingress path
- cert-manager, its local CA and Certificate, and trusted HTTPS
- Kyverno, its enforcing ClusterPolicy, and allowed smoke namespace
- the CrateCheck application service and its full exact-green JSON schema

Repeated `local-up` is state-aware: a matching retained cluster is converged and revalidated. A different source candidate is refused; use explicit recreate. A failed up records `.tmp/kubecrate-local/state.json`, captures bounded sanitized evidence, and leaves any created cluster inspectable rather than silently deleting it.

## Endpoints

After green:

- UI: <http://127.0.0.1:10080/>
- JSON: <http://127.0.0.1:10080/status.json>
- trusted local HTTPS JSON: `https://cratecheck.local:10443/status.json`
- local CA: `.tmp/kubecrate-local/cratecheck-ca.crt`

Use the issued CA and preserve the hostname for HTTPS verification:

```sh
curl --fail --cacert .tmp/kubecrate-local/cratecheck-ca.crt \
  --resolve cratecheck.local:10443:127.0.0.1 \
  https://cratecheck.local:10443/status.json
```

Do not use `-k`; successful trusted HTTPS is part of the demo proof.

## Read-only status and inspection

```sh
make local-status
```

Status is read-only and uses the recorded explicit context. It reports nodes, exact Flux revision, Git source and all Kustomizations, controller and workload readiness, HelmReleases, service-native ESO/Envoy/cert-manager/Kyverno resources, full CrateCheck JSON, HTTP, and trusted HTTPS. It exits non-zero if any required proof is missing or non-green.

Additional read-only exploration should also use the explicit context:

```sh
kubectl --context kind-kubecrate-local get pods -A
flux --context kind-kubecrate-local get all -A
kubectl --context kind-kubecrate-local get events -A --sort-by=.lastTimestamp
```

## Diagnostics and retained evidence

```sh
make local-evidence
```

The stable latest bundle is `.tmp/kubecrate-local/evidence/latest/`. Its stable machine contract is `summary.json` with schema identifier `kubecrate.retained-demo.evidence/v1`. It reports result and phase plus structured context, nodes, expected/observed exact revision, Flux children, controllers, workloads, native consumers, CrateCheck, and HTTP/HTTPS endpoints. Each section names captured artifacts or an explicit unavailable state; human command output remains separate and concise. Evidence collection has minimal prerequisites and still creates a bounded parseable summary when Docker, cluster tools, source rendering, or the endpoint are unavailable. Every retained diagnostic stream, including curl stderr, uses the same conservative sanitizer for token/password/Authorization/Bearer/credential-URL forms.

Useful recovery order after a failure is:

```sh
make local-evidence
make local-status
# inspect the explicit context, then choose restart, recreate, or down
```

## Restart or recreate explicitly

Restart the existing kind node containers and re-run complete status validation:

```sh
make local-restart
```

Delete only the recorded demo-owned cluster, prove absence, then build it again from the currently selected exact public source:

```sh
make local-recreate
```

Recreate is intentionally destructive for the recorded demo cluster. It does not run automatically after a failed up.

## Tear down explicitly

```sh
make local-down
```

Down requires coherent workflow-owned state, refuses protected or ambiguous cluster identities, deletes only the recorded cluster, and proves that exact cluster is absent before clearing active state. The latest sanitized evidence remains at the documented path. If state is missing or does not match the cluster/context identity, down refuses rather than guessing; inspect `kind get clusters` and recover the ownership decision manually.