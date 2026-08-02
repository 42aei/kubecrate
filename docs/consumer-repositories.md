# Consumer repositories

Kubecrate is the versioned upstream distribution for reusable platform services and the Vanilla composition. A consumer repository supplies the cluster-specific Flux root, Kubecrate version, and application services for a concrete cluster.

The minimal public starting point for a new consumer repository is [`42aei/kubecrate-consumer-template`](https://github.com/42aei/kubecrate-consumer-template).

## Kubecrate contract

Kubecrate maintains:

- the stable Vanilla composition entrypoint at `compositions/vanilla/entrypoint/`;
- reusable platform-service definitions under `platform-services/<service>/base/`;
- reusable Kubecrate-owned application-service definitions under `application-services/<service>/base/`;
- compatibility notes and release notes for published versions; and
- validation of the reusable Vanilla composition.

Kubecrate does not own a consumer's cluster identity, private Git root, credentials, domains, or private application services.

## Consumer contract

A consumer repository owns:

- `clusters/<cluster>/entrypoint/` as the Flux reconciliation root;
- a Git source for `https://github.com/42aei/kubecrate.git`;
- an exact immutable Kubecrate release tag;
- a Kustomization that reconciles `./compositions/vanilla/entrypoint` from that source; and
- consumer-owned platform or application services that depend on the Vanilla reconciliation.

Consumer repositories should reference Kubecrate rather than copy its implementation into a long-lived fork. Cluster-specific configuration and secrets remain in the consumer repository or the canonical secret system that owns them.

## Bootstrap and GitOps handoff

A cluster provider or cluster-factory workflow may create the cluster and provide the initial Kubernetes access required for bootstrap installation. Kubecrate begins at the reachable Kubernetes API; it does not create the provider infrastructure or cluster.

The bootstrap flow establishes Flux and binds it to the consumer repository. The same consumer entrypoint then becomes the source for GitOps-managed operation:

```text
cluster provisioning
  -> Kubernetes API and initial access
  -> Flux bootstrap
  -> consumer repository
  -> exact Kubecrate release and Vanilla composition
  -> consumer-owned services
```

For a public consumer repository, bootstrap may use a no-secret public HTTPS Git source. For a private consumer repository, the cluster owner supplies the Git authentication required by the selected Flux bootstrap path. Generated private keys and Secret values must never be committed to Kubecrate, the template, or a consumer repository.

## Version policy

Consumers pin an exact immutable SemVer release tag. They must not use `main`, `master`, `latest`, or a floating major/minor tag as the default source revision.

An upgrade is an explicit consumer change:

1. Kubecrate publishes an approved release and release notes.
2. The consumer updates its exact Kubecrate tag in a reviewed change.
3. The consumer validates the resulting composition before merge.
4. Rollback restores the previous exact tag.

Pre-1.0 releases may contain breaking changes; release notes must identify required consumer-owned changes.

## Template relationship

`42aei/kubecrate-consumer-template` is a small starting point, not a managed update channel. Creating a consumer repository copies its files once; later template changes do not automatically update existing consumers.

Template-owned plumbing should remain small:

- one example cluster root;
- one Kubecrate source;
- one Vanilla reconciliation;
- one consumer-services reconciliation path; and
- validation and instructions for adapting the example.

Do not add a bespoke Kubecrate CLI to replace the official Flux bootstrap flow.

## Ownership matrix

| Area | Kubecrate maintainers | Consumer repository owner | Application owner |
| --- | --- | --- | --- |
| Vanilla composition | Stable paths, releases, compatibility, validation | Consume an exact release | Rely on the platform contract |
| Cluster and bootstrap | Document the consumer contract | Own cluster identity, bootstrap, and Git credentials | Provide application requirements |
| Private services | Provide reusable bases where applicable | Own cluster-specific services and configuration | Own application manifests and runtime configuration |
| Secrets | Do not receive consumer credentials | Own kubeconfigs, deploy keys, and secret-manager integration | Own application secrets and rotation |
| Upgrades | Publish approved releases and notes | Adopt releases through reviewed changes and retain rollback by tag | Test application compatibility |

## Validation

Validate the consumer's rendered Flux and Kubernetes resources, then verify controller reconciliation and the intended operator-visible outcome on the target cluster. Static rendering alone does not prove that bootstrap installation or GitOps-managed operation succeeded.

Kubecrate's reusable composition can be validated locally with:

```sh
make validate
```

The consumer repository owns its additional validation and cluster-specific evidence.

See also [`bootstrap-installation-contract.md`](bootstrap-installation-contract.md) and [`vanilla-composition.md`](vanilla-composition.md).
