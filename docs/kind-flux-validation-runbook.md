# kind-first Flux validation runbook for AI agents

This runbook describes how AI agents should deploy and validate the `kind-dev-misc-local` path when they need a live proof of GitOps-managed operation and the validation status application service.

Use this alongside `AGENTS.md`, `docs/ai-repository-guide.md`, `docs/kind-local-workflow.md`, and `docs/bootstrap-installation-contract.md`. Do not use this runbook as permission to bypass OpenSpec scope or repository placement rules.

## Goal

Deploy the kind-first local path so Flux reconciles the repository and the `validation-status` application service reports status from live Kubernetes API output.

Successful evidence includes:

- a reachable `kind-dev-misc-local` cluster,
- Flux controllers installed,
- `GitRepository/flux-system` ready,
- `Kustomization/flux-system` ready,
- `HelmRelease/flux-system` and `HelmRelease/flux-system-sync` ready,
- `Deployment/validation-status` available with Service endpoints,
- `/status.json` returning `overallStatus: green`, and
- browser or screenshot inspection of the status UI.

## Prerequisites

Install or make available:

- `docker`
- `kind`
- `kubectl`
- `kustomize`
- `helm`
- `flux`
- `gh` authenticated to GitHub with admin permission on `42aei/kubecrate` when registering deploy keys
- `make`
- `python3`

Verify:

```sh
gh auth status
kind version
kubectl version --client=true
kustomize version
helm version --short
flux version --client
docker version --format '{{.Server.Version}}'
```

## Choose the Git branch Flux should reconcile

For normal repository validation, use the branch that contains the changes under review. Do not point Flux at `main` unless `main` contains the manifests being validated.

The branch is configured in:

```text
clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync.yaml
```

For a review branch, set:

```yaml
gitRepository:
  spec:
    url: ssh://git@github.com/42aei/kubecrate.git
    ref:
      branch: <branch-containing-the-change>
```

Commit and push the branch before asking Flux to reconcile it.

## Create the kind cluster and bootstrap Flux

From the repository root:

```sh
make kind-dev-misc-local-recreate
make kind-dev-misc-local-bootstrap
```

`make kind-dev-misc-local-bootstrap` installs the Flux controllers, applies the entrypoint, and prints the Flux public deploy key when the generated `flux-system` Secret is present.

If the target branch is private, Flux cannot fetch it until GitHub trusts the public key in the cluster Secret.

## Register the Flux deploy key in GitHub

Preferred path for AI agents with repo admin permission:

```sh
PUBLIC_KEY="$$(kubectl --context kind-kind-dev-misc-local \
  -n flux-system get secret flux-system \
  -o jsonpath='{.data.identity\.pub}' | base64 -d)"

gh api repos/42aei/kubecrate/keys \
  --method POST \
  -f title="kubecrate kind-dev-misc-local flux $$(date -u +%Y%m%dT%H%M%SZ)" \
  -f key="$$PUBLIC_KEY" \
  -F read_only=true
```

If GitHub says the key already exists, list keys and verify that the matching key is present:

```sh
gh api repos/42aei/kubecrate/keys --jq '.[] | {id,title,read_only,verified,key}'
```

Do not commit private keys to the repository. If you create a temporary keypair manually, store it outside the repo, add only the public key to GitHub, and load the private key into the in-cluster `flux-system` Secret.

## Reconcile and verify Flux

```sh
make kind-dev-misc-local-await-gitops
flux --context kind-kind-dev-misc-local get all -A
```

Expected Flux resources:

- `GitRepository/flux-system`: `READY=True`
- `Kustomization/flux-system`: `READY=True`
- `HelmRelease/flux-system`: `READY=True`
- `HelmRelease/flux-system-sync`: `READY=True`

If `GitRepository/flux-system` fails with `ssh: unable to authenticate`, the deploy key is missing, duplicated incorrectly, or the in-cluster Secret does not contain the matching private key.

## Validate the status app

Check the workload:

```sh
kubectl --context kind-kind-dev-misc-local -n validation-status get deploy,svc,pod,endpoints -o wide
kubectl --context kind-kind-dev-misc-local -n validation-status wait \
  --for=condition=Available deployment/validation-status --timeout=180s
```

Port-forward for inspection:

```sh
kubectl --context kind-kind-dev-misc-local -n validation-status \
  port-forward --address 0.0.0.0 svc/validation-status 18080:80
```

Validate the JSON contract:

```sh
curl -fsS http://127.0.0.1:18080/status.json | python3 -m json.tool
```

The app must compute enabled checks from live Kubernetes API output. It should report green only when these are healthy in the cluster:

- base app health: Deployment availability, Service, and Endpoints
- Flux Git source readiness
- Flux Kustomization readiness
- Flux controller HelmRelease readiness
- Flux sync HelmRelease readiness

Future platform service checks stay `not_configured` until their slice enables real consumption validation.

## Evidence to report

When done, report:

- branch and revision Flux reconciled,
- Flux `get all` output or equivalent ready states,
- validation-status Deployment/Service/Endpoint evidence,
- `/status.json` summary,
- UI visual inspection evidence,
- the inspection URL, and
- any remaining caveats.

On Christian's Hermes VM, expose temporary inspection URLs through the VM NetBird address rather than a public address.
