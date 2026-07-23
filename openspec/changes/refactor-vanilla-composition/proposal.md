## Why

Kubecrate now needs a stable public upstream composition that independent private GitOps repositories can consume without treating `kind-dev-misc-local` as the product contract.

The kind-first local path remains the reference validation path, but it should prove the same reusable Vanilla composition external consumers will use. This keeps Kubecrate cluster-provider agnostic while preserving the existing platform services/application services taxonomy and the established CrateCheck validation surface.

## What changes

- Add `compositions/vanilla/entrypoint/` as the reusable public Vanilla composition entrypoint.
- Move current non-Flux platform-service and CrateCheck composition bindings from the concrete kind cluster tree into `compositions/vanilla/`.
- Keep reusable bases under `platform-services/<service>/base/` and `application-services/cratecheck/base/`.
- Make `clusters/kind-dev-misc-local/entrypoint/` a reference consumer wrapper that keeps kind-local bootstrap/Flux self-management resources and includes the Vanilla entrypoint.
- Add semantic validation for the Vanilla public contract, source paths, workload-category labels, kind reference-consumer wrapper, and absence of temporary QA refs in the composition.
- Update docs and runbooks with migration guidance from the old kind-local service binding paths.

## Non-goals

- Creating a private consumer repository or template repository.
- Publishing a release or tag.
- Moving CrateCheck into platform services.
- Creating a custom Kubecrate CLI.
- Mutating shared clusters or merging main without explicit authorization.

## Validation

- `python3 tests/validate-vanilla-composition.py`
- `python3 scripts/validate-kubernetes-manifests.py`
- `python3 tests/validate-cratecheck.py --render`
- `python3 tests/validate-flux-sync-values.py --helm-render`
- `python3 -m pytest -q`
- Independent review and safeguarded disposable kind+Flux QA of the exact candidate.
