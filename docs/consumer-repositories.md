# Consumer repositories

Kubecrate is the versioned upstream distribution for reusable platform services, generic validation application services, stable public composition paths, compatibility notes, and releases.

A consumer repository is a separate private Flux root owned by a cluster owner. It contains concrete cluster identity, Git credentials wiring, domains, secret declarations, private application services, and the decision about which exact Kubecrate release to run.

The minimal public template for new consumer repositories is `42aei/kubecrate-consumer-template`.

## Producer contract

Kubecrate maintainers own:

- the stable Vanilla composition entrypoint: `compositions/vanilla/entrypoint/`
- reusable platform-service definitions under `platform-services/<service>/base/`
- reusable Kubecrate-owned application-service definitions under `application-services/<service>/base/`
- compatibility and deprecation notes for each release
- SemVer tags and release notes after an explicitly approved release action
- validation evidence for Kubecrate's own reference path

Kubecrate does not own consumer domains, cluster names, private Git roots, credentials, or business application services.

## Consumer contract

A consumer repository owns:

- `clusters/<cluster>/entrypoint/` as its Flux bootstrap path
- a `GitRepository` source pointing at `https://github.com/42aei/kubecrate.git`
- an exact immutable SemVer `ref.tag`, for example `v0.3.0`
- a `Kustomization` that reconciles `./compositions/vanilla/entrypoint` from the Kubecrate source
- a separate private-services path that depends on the Vanilla Kustomization
- any cluster-specific secret-manager declarations, domains, and application workloads

Consumer repositories must not copy Kubecrate implementation into long-lived forks. They should reference a release tag and keep local changes in consumer-owned paths.

## Version and compatibility policy

Consumers must pin exact SemVer tags. Do not default a consumer repository to `main`, `master`, a moving branch, `latest`, or a floating major/minor tag. A merge to Kubecrate `main` must not silently update existing clusters.

The expected release/update flow is:

1. Kubecrate maintainers prepare and validate a release candidate.
2. Christian explicitly authorizes the exact tag/release action.
3. Kubecrate publishes release notes and the immutable SemVer tag.
4. Each consumer repository receives an explicit version-only PR or equivalent reviewed diff.
5. The cluster owner merges that PR when ready.
6. Rollback restores the previous exact tag in the consumer repository.

Pre-1.0 releases may still contain breaking changes. Release notes must call out any required consumer-owned edits.

## Template relationship

`42aei/kubecrate-consumer-template` is a tiny starting point. Creating a private repository from it copies the files once. It is not a managed update channel, and template changes do not automatically modify repositories already created from it.

Keep template-owned plumbing deliberately small:

- one example cluster root
- one Kubecrate upstream source
- one Vanilla reconciliation
- one private-services reconciliation path
- a thin wrapper around official Flux bootstrap instructions
- static validation fixtures and docs

Do not add a bespoke Kubecrate CLI for consumer bootstrap.

## Responsibility matrix

| Area | Kubecrate maintainers | Template maintainers | Cluster owners | Application owners |
| --- | --- | --- | --- | --- |
| Vanilla composition | Own stable paths, release notes, compatibility, validation | Link to stable paths only | Consume one exact tag | Rely on the platform contract |
| Consumer private repository | Do not own private cluster details | Provide minimal copied starting point | Own visibility, branch policy, cluster identity, bootstrap, and Git credentials | Own app manifests and runtime configuration |
| Credentials and secrets | Do not receive consumer credentials | Do not include credential examples with real values | Own deploy keys, tokens, kubeconfigs, and secret-manager setup | Own application secrets and rotation |
| Upgrades | Publish approved exact releases | Keep examples current for new repos | Adopt through reviewed private PRs and rollback by tag | Test app compatibility |
| Decommissioning | Document upstream assumptions | Document safe order | Own cluster/repo retirement | Own data export and application shutdown |

## Bootstrap-generated versus hand-maintained files

Flux bootstrap-generated files belong to the cluster owner and the official Flux bootstrap flow. Review them when they are created or updated, but do not use them for ordinary application changes.

Hand-maintained consumer files include the Kubecrate tag declaration, the Vanilla Kustomization, private-services Kustomization, and private application manifests. These should be reviewed like normal repository code.

Generated private keys and Secret values must remain in the cluster or canonical secret systems. They must not be committed to Kubecrate, the template repository, or consumer repositories.
