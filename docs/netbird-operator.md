# NetBird operator

The NetBird operator is an optional platform service. It is not part of the Vanilla composition: `compositions/vanilla/entrypoint/` does not reconcile it, and a consumer that does not opt in gets no NetBird operator, CRDs, or GatewayClasses.

The reusable base is `platform-services/netbird-operator/base/`. It installs chart `netbird-operator` version `0.9.0` from `oci://ghcr.io/netbirdio/helm-charts` into the `core-netbird-operator` namespace. The `HelmRelease` uses `install.crds: CreateReplace` and `upgrade.crds: CreateReplace`, and `install.remediation.retries: 3`.

## Consumer contract

A consumer opts in by adding a Flux `Kustomization` that reconciles `./platform-services/netbird-operator/base` from `GitRepository/flux-system-sync`, the same source and exact release tag it uses for Vanilla.

The consumer must supply:

- Secret `netbird-mgmt-api-key` with key `NB_API_KEY` in namespace `core-netbird-operator`, holding a NetBird API key. Kubecrate never carries the value; the consumer delivers it, for example through an `ExternalSecret`.
- An override of `cluster.name` through the `HelmRelease`'s `spec.values`. The base sets the placeholder `override-me`; every consumer must replace it with a name unique to its cluster, because NetBird uses it to name networks and network resources.

Example consumer patch (Flux `Kustomization` `patches`):

```yaml
patches:
  - target:
      kind: HelmRelease
      name: netbird-operator
    patch: |
      - op: add
        path: /spec/values
        value:
          cluster:
            name: my-cluster
```

Flux merges `spec.values` over the values from the generated `netbird-operator-values` `ConfigMap`.

The consumer owns everything above the operator: `NetworkRouter`, `NetworkResource`, Gateway and route objects, and the secret delivery. None of it is in this base.

## Dependencies

The base relies on two things Vanilla provides, and a consumer that reconciles it without Vanilla must provide them itself:

- cert-manager, because `webhook.enableCertManager: true` renders a self-signed `Issuer` and `Certificate` for the webhook;
- the Gateway API CRDs, because `gatewayAPI.enabled: true` renders the `GatewayClass` objects `netbird-private` and `netbird-public`.

## Secret arrival order

The operator pod needs Secret `netbird-mgmt-api-key` before it becomes Ready. On a fresh cluster the Secret may arrive after the install starts. The `HelmRelease` retries a failed install up to 3 times (`install.remediation.retries: 3`), about 20 minutes with the 5-minute `timeout`. Once the retries are used up, Flux keeps the release failed. A Secret that arrives later than that needs a reset of the failure count:

```sh
flux reconcile helmrelease netbird-operator -n core-netbird-operator --reset
```

Deliver the Secret early, so the first install attempt does not have to wait for it.

## Webhook scope

The chart's only webhook is a mutating pod webhook (sidecar injection) on pod `CREATE`. Its chart default is `failurePolicy: Fail` on all namespaces, which would block every pod creation in the cluster while the operator is down. The base sets `failurePolicy: Ignore` and narrows the namespace selector to `kubernetes.io/metadata.name In [core-netbird-operator]`. Sidecar injection is therefore not available outside that namespace.

## Limits

These are accepted costs of using the chart as it is:

- The chart grants the operator cluster-wide Secret get/list/watch/create/update/patch/delete when `netbirdAPI.keyFromSecret` is set; `clusterSecretsPermissions.allowAllSecrets: false` does not narrow it.
- Each `NetworkRouter` runs three privileged routing-peer pods (`NET_ADMIN`, `SYS_RESOURCE`, `SYS_ADMIN`), and each pod is a NetBird machine.
- The API key belongs to an admin-role NetBird service user.
- A routing-pod restart leaves a stale peer in NetBird.
- There is no login per app.
- Private access is plain HTTP.
- NetBird Reverse Proxy is beta.
- The chart installs 12 `netbird.io` CRDs.

## Validation

`make validate` renders this base with `kustomize build`. Static rendering does not prove the service works: the end-to-end proof is the tenant-01 rollout (https://github.com/42aei/bedrock/issues/101), because it needs a NetBird account and API key that this repository has none of.
