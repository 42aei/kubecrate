# Vanilla composition

The Vanilla composition is Kubecrate's reusable public consumption path for GitOps-managed operation.

It separates the stable upstream Kubecrate contract from the concrete `kind-dev-misc-local` reference consumer. External/private consumers should consume the same Vanilla entrypoint path rather than copying the kind-first local path.

## Contract

The public entrypoint is:

- `compositions/vanilla/entrypoint/`

That entrypoint contains Flux `Kustomization` objects for the included platform services:

- External-Secrets Operator platform service
- Envoy Gateway platform service
- cert-manager platform service
- Kyverno platform service

The Vanilla composition is platform services only. The kind-local smoke fixtures and the
CrateCheck status application moved out of this repository into the consumer-side smoke suite at
[42aei/kubecrate-kind-smoke](https://github.com/42aei/kubecrate-kind-smoke). That repository
reconciles its own Flux `Kustomization` objects on top of a pinned kubecrate Vanilla entrypoint
and keeps the green -> controlled red -> restored green `/status.json` proof.

Consumers validate kubecrate substrate updates by running the smoke suite against a pinned
kubecrate commit, locally or through its invokable kind CI workflow. See the smoke repository
README for the consumption contract.

## Reusable definitions and composition bindings

Reusable service definitions remain under the workload-category roots:

- `platform-services/<service>/base/`

The Vanilla composition binds those reusable definitions under:

- `compositions/vanilla/platform-services/<service>/`

The composition is intentionally cluster-independent. It does not carry concrete cluster identity, local kind setup, release mechanics, or private consumer application services.

## kind reference consumer

The kind-first local path remains the first concrete reference consumer:

- `clusters/kind-dev-misc-local/entrypoint/`

That entrypoint owns only kind-local bootstrap/handoff resources and the Flux self-management binding, then includes `../../../compositions/vanilla/entrypoint`.

This makes `kind-dev-misc-local` prove the same public contract that an external consumer will use. It must not keep a shadow copy of platform-service/application-service bindings under `clusters/kind-dev-misc-local/` for services that are part of Vanilla.

## Migration from the old entrypoint

Before this refactor, the kind-first local path carried concrete bindings directly under:

- `clusters/kind-dev-misc-local/platform-services/<service>/`
- `clusters/kind-dev-misc-local/application-services/cratecheck/`
- `clusters/kind-dev-misc-local/entrypoint/*-kustomization.yaml`

Those paths are replaced by the Vanilla composition for reusable upstream content. The only retained kind-local binding is Flux bootstrap/self-management under `clusters/kind-dev-misc-local/platform-services/flux/`.

Consumers should not treat the old kind-local service paths as a public API. Use `compositions/vanilla/entrypoint/` as the stable upstream path.

The smoke consumer resources, the cert-manager local issuer chain, and the CrateCheck
application service later moved to `42aei/kubecrate-kind-smoke` for the same reason: they are
consumer-side validation fixtures, not part of the upstream distribution.

## Validation

Run the static validation suite before review:

```sh
python3 tests/validate-vanilla-composition.py
python3 scripts/validate-kubernetes-manifests.py
python3 tests/validate-flux-sync-values.py --helm-render
```

Final delivery still requires an independent review and safeguarded disposable kind+Flux QA of
the exact candidate. The runtime consumption proof for a kubecrate substrate update is owned by
the smoke suite in `42aei/kubecrate-kind-smoke` (CrateCheck JSON green -> controlled red ->
restored green against a pinned kubecrate commit).
