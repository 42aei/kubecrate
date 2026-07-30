# Vanilla composition

The Vanilla composition is Kubecrate's reusable public consumption path for GitOps-managed operation.

It separates the stable upstream Kubecrate contract from concrete consumer repositories. External/private consumers should reference the same Vanilla entrypoint path from their own Flux roots.

## Contract

The public entrypoint is:

- `compositions/vanilla/entrypoint/`

That entrypoint contains Flux `Kustomization` objects for the currently included platform services and application services:

- External-Secrets Operator platform service and its smoke consumer resources
- Envoy Gateway platform service and its smoke Gateway API resources
- cert-manager platform service and its local issuer smoke resources
- Kyverno platform service and its smoke policy/resources
- CrateCheck application service

CrateCheck remains an application service because it consumes platform services to validate operator-visible outcomes. It is not moved into `platform-services` just because Kubecrate owns it.

## Reusable definitions and composition bindings

Reusable service definitions remain under the workload-category roots:

- `platform-services/<service>/base/`
- `application-services/<service>/base/`

The Vanilla composition binds those reusable definitions under:

- `compositions/vanilla/platform-services/<service>/`
- `compositions/vanilla/application-services/<service>/`

The composition is intentionally cluster-independent. It does not carry concrete cluster identity, local kind setup, bootstrap installation wrappers, release mechanics, or private consumer application services.

## Consumer repository boundary

The kind-first local reference consumer lives outside this upstream repository:

- `42aei/kubecrate-kind-example`

That repository owns its concrete `clusters/kind-dev-misc-local/` Flux root, kind setup, Flux self-management binding, and consumer-owned platform services and application services. It references this repository as an upstream Flux source and reconciles `compositions/vanilla/entrypoint/` from an exact Kubecrate release tag. The kind smoke fixtures are maintained in `42aei/kubecrate-kind-smoke` and are imported by the consumer repository.

This keeps Kubecrate as the versioned upstream distribution and makes the kind-first local path exercise the same public contract private consumers use.

## Migration from the old entrypoint

Before this refactor, the kind-first local path carried concrete bindings directly under:

- `clusters/kind-dev-misc-local/platform-services/<service>/`
- `clusters/kind-dev-misc-local/application-services/cratecheck/`
- `clusters/kind-dev-misc-local/entrypoint/`

Those paths are replaced by the Vanilla composition for reusable upstream content. Kind-local bootstrap installation wrappers, cluster identity, and Flux self-management move to the consumer repository.

Consumers should not treat the old kind-local service paths as a public API. Use `compositions/vanilla/entrypoint/` as the stable upstream path.

## Validation

Run the static validation suite before review:

```sh
python3 tests/validate-vanilla-composition.py
python3 scripts/validate-kubernetes-manifests.py
python3 tests/validate-cratecheck.py --render
```

Final delivery still requires independent review and consumer-repository validation of the exact Kubecrate tag consumed by the kind-first local path. Static rendering does not replace the CrateCheck JSON green -> controlled red -> restored green proof for a release candidate.
