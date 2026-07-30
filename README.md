<p align="center">
  <img src="docs/logos/kubecrate-logo.svg" alt="KubeCrate logo" width="600">
</p>

# Kubecrate

Kubecrate is a minimal cloud-native platform distribution for Kubernetes clusters. It packages an opinionated baseline of platform services and a small validation application so a cluster owner can install a known GitOps-managed starting point instead of assembling the same foundation from scratch.

Kubecrate is:

- **minimal**: it includes only the baseline needed for the supported composition;
- **opinionated**: the repository chooses concrete components and paths rather than exposing broad early configurability;
- **GitOps-managed**: Flux reconciles the cluster state from Git;
- **kind-first**: the local reference workflow uses kind, while the repository model keeps the cluster-provider boundary separate;
- **production-inspired, not production-ready**: the manifests and workflows are designed for clear validation and review, not as a turnkey production platform.

## Structure

Kubecrate separates lifecycle phase from workload category.

Lifecycle phases:

1. **bootstrap installation**: establish Flux and the first GitOps handoff on a reachable cluster;
2. **GitOps-managed operation**: Flux reconciles Kubecrate and consumer-owned resources from Git.

Workload categories:

1. **platform services**: shared platform capabilities such as External Secrets Operator, Envoy Gateway, cert-manager, and Kyverno;
2. **application services**: workloads that run on the platform. Kubecrate includes CrateCheck as an application service that validates platform behavior through `/status.json`.

The main repository paths are:

```text
platform-services/                         reusable platform-service bases
application-services/                      reusable application-service bases
compositions/vanilla/                      reusable Kubecrate Vanilla composition
clusters/kind-dev-misc-local/              kind-first local reference consumer
kind/                                      kind cluster configuration
docs/                                      architecture, workflows, and runbooks
scripts/                                   validation and local-demo helpers
tests/                                     contract and validation tests
openspec/                                  design/change specifications
```

## Vanilla composition

`compositions/vanilla/entrypoint/` is the reusable upstream composition path. It wires the included platform services, smoke resources, and CrateCheck application service into one Flux entrypoint.

The Vanilla composition includes:

- External Secrets Operator and a projected-Secret smoke consumer;
- Envoy Gateway and Gateway API smoke resources;
- cert-manager and local TLS issuer smoke resources;
- Kyverno and policy-behavior smoke resources;
- CrateCheck, using `ghcr.io/42aei/cratecheck:v1`.

Consumer repositories should reconcile this path from an exact immutable Kubecrate release tag. Cluster consumers should not track `main`, `latest`, or a floating major tag.

See [`docs/vanilla-composition.md`](docs/vanilla-composition.md).

## Local retained demo

The retained local demo runs the kind-first local reference stack and leaves the cluster running for inspection.

Prerequisites are listed in [`docs/retained-local-demo.md`](docs/retained-local-demo.md). From a clean checkout whose `HEAD` is available from the selected remote:

```sh
make local-check
make local-up
```

Inspect the running demo:

```sh
make local-status
make local-evidence
```

Stop and remove the demo-owned cluster:

```sh
make local-down
```

The demo exposes CrateCheck over local HTTP and trusted local HTTPS. `local-status` verifies cluster state, Flux revision, platform-service readiness, CrateCheck JSON health, and endpoint reachability.

## Consumer repositories

Kubecrate is consumed as a versioned upstream distribution. A consumer repository is an independent Flux root owned by the cluster operator. It carries cluster identity, domains, credentials, private application services, and the selected Kubecrate release tag.

A consumer Flux root should:

1. define a `GitRepository` for the Kubecrate upstream repository;
2. pin `ref.tag` to an exact immutable Kubecrate release;
3. reconcile `./compositions/vanilla/entrypoint` from that source;
4. reconcile consumer-owned private services separately after Vanilla is ready.

If Kubecrate is publicly readable, Flux can fetch the upstream over anonymous HTTPS. If Kubecrate is private, the consumer repository must configure a Flux `secretRef` or another Git credential path for the upstream source.

## Development validation

Install the development dependencies from `requirements-dev.txt` in a virtual environment, then run the repository validators:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
make validate
python3 scripts/validate-kubernetes-manifests.py
python3 -m pytest -q
```

Useful focused validators:

```sh
python3 tests/validate-vanilla-composition.py
python3 tests/validate-cratecheck.py --render
```

Static rendering and tests do not replace live validation for delivery work that changes bootstrap installation, GitOps-managed operation, or platform-service behavior.

## Documentation

Start with:

- [`docs/architecture.md`](docs/architecture.md) for the project model;
- [`docs/bootstrap-installation-contract.md`](docs/bootstrap-installation-contract.md) for the bootstrap and GitOps handoff contract;
- [`docs/vanilla-composition.md`](docs/vanilla-composition.md) for the reusable upstream composition;
- [`docs/kind-local-workflow.md`](docs/kind-local-workflow.md) for the kind-first local path;
- [`docs/retained-local-demo.md`](docs/retained-local-demo.md) for the retained demo commands;
- [`docs/README.md`](docs/README.md) for the full documentation map.

## Repository visibility

This repository is safe to make public only after maintainers verify the selected release tag, tracked files, README, and public-facing docs for the intended release. Repository visibility is controlled through GitHub settings; changing visibility is a separate maintainer action from merging documentation or license updates.

## License

Kubecrate is licensed under the MIT License. See [`LICENSE`](LICENSE).
