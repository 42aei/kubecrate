## Context

Earlier installable slices grew the kind-first local path by placing each concrete platform-service and application-service binding directly under `clusters/kind-dev-misc-local/`. That was acceptable while `kind-dev-misc-local` was the only consumer, but it makes the concrete reference cluster look like the public product contract.

The approved consumer architecture makes Kubecrate the versioned upstream distribution and each private repository an independent Flux root. That requires a reusable upstream path that can be referenced by more than one consumer while keeping consumer-owned cluster identity and private application services out of Kubecrate.

## Decisions

### Vanilla is the stable upstream composition

`compositions/vanilla/entrypoint/` is the public Kubecrate composition path for the included platform services and Kubecrate-owned generic validation application service.

The Vanilla entrypoint owns Flux `Kustomization` resources that point at composition-local bindings. Those bindings compose the reusable bases:

- `platform-services/<service>/base/`
- `application-services/cratecheck/base/`

This keeps base resources reusable while giving Kubecrate one coherent upstream composition that can be validated and later released.

### kind-dev-misc-local is a reference consumer, not the product contract

The concrete kind-first local path lives in `42aei/kubecrate-kind-example`. It owns local bootstrap/handoff concerns such as the namespace marker and Flux self-management binding, then references this repository's `compositions/vanilla/entrypoint/` from an exact Kubecrate release tag.

This preserves existing local validation while proving the same Vanilla path future external consumers will use.

### Flux remains the current concrete bootstrap exception

Flux self-management remains consumer-local because it is tied to bootstrap installation and the concrete repository source binding for the reference path. The refactor does not make Flux release mechanics generic beyond the kind example yet.

### CrateCheck remains application services scope

CrateCheck is Kubecrate-owned, but it validates platform capabilities by consuming them. Ownership does not change workload category. It remains under `application-services/cratecheck/base/` and is included in Vanilla as an application service.

### Old kind-local service paths are not public API

The old Kubecrate-owned paths under `clusters/kind-dev-misc-local/platform-services/<service>/` and `clusters/kind-dev-misc-local/application-services/cratecheck/` are removed for the services included in Vanilla. Keeping them would create a shadow composition and allow the reference path to drift from the public contract.

## Risks and mitigations

- Risk: moving files can break Kustomize relative paths. Mitigation: add `tests/validate-vanilla-composition.py` plus render/schema validation for every Vanilla root and the kind reference wrapper.
- Risk: docs/OpenSpec still describe the old kind-local placement. Mitigation: update current source-of-truth docs and add migration notes; historical OpenSpec files remain point-in-time records unless changed by this active refactor.
- Risk: temporary QA refs could leak into the public composition. Mitigation: semantic validator rejects QA-only tokens in composition YAML and keeps the committed Flux sync default on durable `main` for post-merge operation.
