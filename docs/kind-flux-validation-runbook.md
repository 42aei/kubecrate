# kind reference setup guide

This guide is the general setup path for the Kubecrate `kind-dev-misc-local` reference environment. It is written for AI agents and users who need to create a local kind cluster, hand off to Flux, deploy application services, and collect evidence.

Use this alongside `AGENTS.md`, `docs/ai-repository-guide.md`, `docs/kind-local-workflow.md`, and `docs/bootstrap-installation-contract.md`. This guide does not bypass OpenSpec scope, repository placement rules, or current phase guardrails.

## What this setup proves

A successful setup proves that this cluster binding can reach GitOps-managed operation:

- a local kind cluster exists and is reachable,
- Flux controllers are installed,
- Flux can authenticate to GitHub and fetch the configured branch,
- Flux can reconcile `clusters/kind-dev-misc-local/entrypoint`,
- configured platform services and application services are applied by Flux, and
- the `kubecrate-status` application service reports live Kubernetes API status for the configured resources.

## Required tools

Install or make available on the machine running the setup:

```sh
gh auth status
kind version
kubectl version --client=true
kustomize version
helm version --short
flux version --client
docker version --format '{{.Server.Version}}'
make --version
python3 --version
```

The GitHub CLI account must be able to read the target private repository. It needs repository admin permission only when registering repository deploy keys.

## GitHub deploy-key prerequisite

For private repositories, Flux needs an SSH identity that GitHub accepts. The preferred Kubecrate path is a read-only repository deploy key registered on `42aei/kubecrate`.

The 42aei organization must allow repository deploy keys. Check it with:

```sh
gh api orgs/42aei --jq '{deploy_keys_enabled_for_repositories}'
```

The required value is:

```json
{"deploy_keys_enabled_for_repositories":true}
```

If the value is `false`, GitHub rejects new repo deploy keys with a message like:

```text
Deploy keys are disabled for this repository
```

In that case, an organization owner must enable deploy keys for repositories before the repo-level deploy-key path can be used. A temporary GitHub account SSH key can unblock local validation, but it is broader than a repo deploy key and should not be treated as the preferred steady-state setup.

## Choose the branch Flux reconciles

Flux follows the branch configured in:

```text
clusters/kind-dev-misc-local/platform-services/flux/helm-values-sync.yaml
```

For review work, set the source to the branch containing the changes under validation:

```yaml
gitRepository:
  spec:
    url: ssh://git@github.com/42aei/kubecrate.git
    ref:
      branch: <branch-containing-the-change>
```

Commit and push that branch before reconciling Flux. Do not point Flux at `main` unless `main` contains the manifests being validated.

## Create or recreate the cluster

From the repository root:

```sh
make kind-dev-misc-local-recreate
```

This deletes any existing `kind-dev-misc-local` cluster, creates a fresh cluster from `kind/config.yaml`, and waits for nodes to become Ready.

## Bootstrap Flux

```sh
make kind-dev-misc-local-bootstrap
```

This installs Flux controllers, applies the kind entrypoint, and prints the public key from the in-cluster `flux-system` Secret.

## Register the Flux public key as a repo deploy key

After bootstrap, capture the public key:

```sh
PUBLIC_KEY="$(kubectl --context kind-kind-dev-misc-local \
  -n flux-system get secret flux-system \
  -o jsonpath='{.data.identity\.pub}' | base64 -d)"
```

If org deploy keys are enabled, register it as a read-only deploy key:

```sh
gh api repos/42aei/kubecrate/keys \
  --method POST \
  -f title="kubecrate kind-dev-misc-local flux $(date -u +%Y%m%dT%H%M%SZ)" \
  -f key="$PUBLIC_KEY" \
  -F read_only=true
```

List existing keys when debugging:

```sh
gh api repos/42aei/kubecrate/keys --jq '.[] | {id,title,read_only,verified,key}'
```

Never commit private keys. If you temporarily load a manually generated SSH key into the cluster, keep it outside the repository and document that it is a local validation workaround.

## Reconcile and verify GitOps-managed operation

```sh
make kind-dev-misc-local-await-gitops
flux --context kind-kind-dev-misc-local get all -A
```

Expected ready resources include:

- `GitRepository/flux-system`
- `Kustomization/flux-system`
- `HelmRelease/flux-system`
- `HelmRelease/flux-system-sync`

If `GitRepository/flux-system` reports `ssh: unable to authenticate`, check:

1. org deploy keys are enabled,
2. the public key from the cluster Secret is registered on the repository,
3. the cluster Secret still contains the matching private key,
4. `known_hosts` exists in the Secret, and
5. the configured branch exists and is readable.

## Configure kubecrate-status checks

The validation app is configured by ConfigMap, not by hardcoded monitored resources in the app code:

```text
application-services/kubecrate-status/base/status-config.yaml
```

Each enabled check declares the Kubernetes API resource path or workload tuple it monitors. The app reads the mounted `/config/config.json`, calls the Kubernetes API with its ServiceAccount, and reports status in `/status.json` and the UI.

When adding monitored resources:

1. Add or edit a check in `status-config.yaml`.
2. Ensure `application-services/kubecrate-status/base/rbac.yaml` grants only the required `get` access for the configured resource type.
3. Keep future platform service checks `not_configured` until the slice has real consumption validation.
4. Run static rendering and live reconciliation before claiming success.

## Inspect the validation app

Check the workload:

```sh
kubectl --context kind-kind-dev-misc-local -n kubecrate-status get deploy,svc,pod,endpoints -o wide
kubectl --context kind-kind-dev-misc-local -n kubecrate-status wait \
  --for=condition=Available deployment/kubecrate-status --timeout=180s
```

Port-forward for local inspection:

```sh
kubectl --context kind-kind-dev-misc-local -n kubecrate-status \
  port-forward --address 0.0.0.0 svc/kubecrate-status 18080:80
```

Validate JSON:

```sh
curl -fsS http://127.0.0.1:18080/status.json | python3 -m json.tool
```

## Validation UI hard rule

The validation app UI must be based on the shadcn/ui framework and component language: cards, badges, buttons, muted text, borders, dark theme tokens, accessible focus/ARIA behavior, and responsive layout conventions must follow <https://ui.shadcn.com/>.

Graphs and interactive overview modules must be based on shadcn/ui chart modules from <https://ui.shadcn.com/docs/components/chart> / <https://ui.shadcn.com/charts>. In the current static ConfigMap-hosted implementation, the chart-like overview must mirror those shadcn/ui chart primitives and naming in plain HTML/CSS/JS; once the app moves to a bundled React frontend, use the actual shadcn/ui `ChartContainer`, `ChartTooltip`, `ChartLegend`, and Recharts-backed modules directly.

Do not introduce an unrelated frontend kit for this app. If a future agent wants to use a different chart library, it must first update the architectural docs and get explicit approval.

## Evidence to report

Report:

- branch and revision Flux reconciled,
- Flux ready states,
- kubecrate-status Deployment/Service/Endpoint evidence,
- `/status.json` overall status and enabled check states,
- UI visual inspection evidence,
- the inspection URL, and
- caveats such as temporary SSH-key workarounds or org deploy-key settings.

On Christian's Hermes VM, expose temporary inspection URLs through the VM NetBird address rather than a public address.
