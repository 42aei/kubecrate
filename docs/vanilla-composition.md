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

Each nested Flux `Kustomization` uses `sourceRef.kind: GitRepository` and `sourceRef.name: flux-system-sync`. Consumers should use a single `GitRepository/flux-system-sync`, pinned to an exact Kubecrate release tag, for the top-level Vanilla reconciliation and for these nested reconciliations.

## Reusable definitions and composition bindings

Reusable service definitions remain under the workload-category roots:

- `platform-services/<service>/base/`
- `application-services/<service>/base/`

The Vanilla entrypoint reconciles the selected platform-service bases directly:

- `platform-services/external-secrets-operator/base/`
- `platform-services/envoy-gateway/base/`
- `platform-services/cert-manager/base/`
- `platform-services/kyverno/base/`

The composition is intentionally cluster-independent. It does not carry concrete cluster identity, release mechanics, or private consumer application services.

## Compatibility note

`compositions/vanilla/entrypoint/` remains the stable consumer path. Direct references to the former per-service composition binding paths under `compositions/vanilla/platform-services/<service>/` must move to the corresponding service base under `platform-services/<service>/base/`. Consumers that only reconcile `compositions/vanilla/entrypoint/` do not need to change their Kubecrate path.

Use `compositions/vanilla/entrypoint/` as the stable upstream path.

## Validation

Run the repository validation suite before review:

```sh
make validate
```

Final delivery requires independent review and validation of the exact candidate.
