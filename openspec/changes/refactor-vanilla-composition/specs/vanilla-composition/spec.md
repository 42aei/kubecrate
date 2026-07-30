## ADDED Requirements

### Requirement: Vanilla composition provides the public upstream entrypoint
Kubecrate SHALL provide a reusable, cluster-independent Vanilla composition as the stable upstream consumption path for included platform services and Kubecrate-owned generic application services.

#### Scenario: Vanilla entrypoint exists
- **WHEN** the repository is inspected
- **THEN** the public Vanilla composition entrypoint lives at `compositions/vanilla/entrypoint/`
- **AND** it contains Flux `Kustomization` resources for the included platform services and CrateCheck application service
- **AND** no temporary QA-only Git refs are committed in the Vanilla composition

#### Scenario: Vanilla child paths are composition-owned
- **WHEN** the Vanilla Flux `Kustomization` resources are inspected
- **THEN** their `spec.path` values point under `./compositions/vanilla/`
- **AND** their `sourceRef` uses `GitRepository/flux-system-sync`
- **AND** workload-category labels preserve `platform-services` for platform service units and `application-services` for CrateCheck

### Requirement: kind-first local path consumes Vanilla from a reference consumer repository
The `kind-dev-misc-local` cluster SHALL consume the same Vanilla entrypoint that external consumers will use, while retaining kind-local bootstrap, Flux self-management resources, and consumer-owned extensions in the concrete consumer repository.

#### Scenario: kind entrypoint lives outside upstream Kubecrate
- **WHEN** the upstream Kubecrate repository is inspected
- **THEN** it does not contain an active `clusters/kind-dev-misc-local/` runtime tree
- **AND** the reference consumer lives in `42aei/kubecrate-kind-example`
- **AND** the reference consumer references `compositions/vanilla/entrypoint/` from an exact Kubecrate release tag

#### Scenario: old kind-local service bindings are removed
- **WHEN** the runtime tree is inspected
- **THEN** included Vanilla services do not keep active bindings under `clusters/kind-dev-misc-local/platform-services/<service>/`
- **AND** CrateCheck does not keep an active binding under `clusters/kind-dev-misc-local/application-services/cratecheck/`
- **AND** Flux self-management may remain in the reference consumer repository as the current concrete bootstrap exception

### Requirement: Reusable bases and workload taxonomy are preserved
Kubecrate SHALL keep reusable service bases in the existing workload-category roots and SHALL preserve the two-axis model across the refactor.

#### Scenario: reusable base roots remain stable
- **WHEN** Vanilla composition bindings are inspected
- **THEN** platform service bindings reference reusable bases under `platform-services/<service>/base/`
- **AND** the CrateCheck application service binding references `application-services/cratecheck/base/`

#### Scenario: CrateCheck remains application services scope
- **WHEN** the Vanilla composition is inspected
- **THEN** CrateCheck is labeled and documented as `application-services`
- **AND** it is not moved into `platform-services`

### Requirement: Semantic validation protects the public composition contract
Kubecrate SHALL validate the public composition, source paths, ownership boundaries, and absence of temporary QA refs with repository-owned checks.

#### Scenario: Vanilla validator proves source and ownership boundaries
- **WHEN** `python3 tests/validate-vanilla-composition.py` runs
- **THEN** it verifies the Vanilla entrypoint child set, child source paths, workload-category labels, kind wrapper consumption, removed old kind-local bindings, reusable base references, and absence of temporary QA tokens in composition YAML

#### Scenario: Static render validation includes Vanilla and reference consumer roots
- **WHEN** `python3 scripts/validate-kubernetes-manifests.py` runs
- **THEN** it renders and schema-validates the Vanilla composition roots

### Requirement: Documentation explains migration from the old kind-local entrypoint
Kubecrate SHALL document the Vanilla composition and explain how it replaces the old kind-local service-binding entrypoint as the stable public consumption path.

#### Scenario: docs describe consumer path
- **WHEN** docs are inspected
- **THEN** `docs/vanilla-composition.md` identifies `compositions/vanilla/entrypoint/` as the public consumption path
- **AND** it explains that `kind-dev-misc-local` is a reference consumer of Vanilla in a separate consumer repository
- **AND** it lists the old kind-local service paths as replaced implementation details, not public API
