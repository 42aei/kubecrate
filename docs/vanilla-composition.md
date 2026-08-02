# Vanilla composition

The Vanilla composition is Kubecrate's reusable public consumption path for GitOps-managed operation.

## Contract

The public entrypoint is:

- `compositions/vanilla/entrypoint/`

That entrypoint contains Flux `Kustomization` objects for the currently included platform services:

- External-Secrets Operator
- Envoy Gateway
- cert-manager
- Kyverno

## Reusable definitions and composition bindings

Reusable service definitions remain under the workload-category roots:

- `platform-services/<service>/base/`
- `application-services/<service>/base/`

The Vanilla composition binds those reusable definitions under:

- `compositions/vanilla/platform-services/<service>/`
- `compositions/vanilla/application-services/<service>/`

The composition is intentionally cluster-independent. It does not carry concrete cluster identity, release mechanics, or private consumer application services.

Use `compositions/vanilla/entrypoint/` as the stable upstream path.

## Validation

Run the repository validation suite before review:

```sh
make validate
```

Final delivery requires independent review and validation of the exact candidate.
