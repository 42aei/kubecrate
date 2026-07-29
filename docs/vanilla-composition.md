# Vanilla composition

The Vanilla composition is Kubecrate's reusable public consumption path for GitOps-managed operation.

It separates the stable upstream Kubecrate contract from the concrete `kind-dev-misc-local` reference consumer. External/private consumers should consume the same Vanilla entrypoint path rather than copying the kind-first local path. New private consumer repositories should normally start from `42aei/kubecrate-consumer-template` and pin Kubecrate to an exact SemVer release tag.

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

## Validation

Run the static validation suite before review:

```sh
python3 tests/validate-vanilla-composition.py
python3 scripts/validate-kubernetes-manifests.py
python3 tests/validate-cratecheck.py --render
python3 tests/validate-flux-sync-values.py --helm-render
```

Final delivery still requires an independent review and safeguarded disposable kind+Flux QA of the exact candidate. Static rendering does not replace the CrateCheck JSON green -> controlled red -> restored green proof.
