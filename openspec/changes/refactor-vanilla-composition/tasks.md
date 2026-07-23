## 1. Vanilla composition layout

- [x] 1.1 Add `compositions/vanilla/entrypoint/` as the public upstream composition entrypoint.
- [x] 1.2 Move included non-Flux platform-service composition bindings into `compositions/vanilla/platform-services/<service>/`.
- [x] 1.3 Move the CrateCheck composition binding into `compositions/vanilla/application-services/cratecheck/`.
- [x] 1.4 Keep reusable bases under `platform-services/<service>/base/` and `application-services/cratecheck/base/`.
- [x] 1.5 Remove shadow kind-local service bindings for included Vanilla services.

## 2. kind reference consumer

- [x] 2.1 Make `clusters/kind-dev-misc-local/entrypoint/` include `../../../compositions/vanilla/entrypoint`.
- [x] 2.2 Keep kind-local namespace marker, reconciliation marker, and Flux self-management binding in the concrete kind entrypoint.
- [x] 2.3 Preserve `clusters/kind-dev-misc-local/platform-services/flux/` as the current concrete bootstrap/Flux exception.

## 3. Semantic validation

- [x] 3.1 Add `tests/validate-vanilla-composition.py` for Vanilla entrypoint, child path, workload-category, reference consumer, old-path removal, reusable base reference, and QA-token checks.
- [x] 3.2 Add the Vanilla validator to `make validate`.
- [x] 3.3 Update manifest validation roots to cover Vanilla roots plus the kind reference wrapper.
- [x] 3.4 Update existing CrateCheck/Flux/cert-manager/Kyverno/Envoy tests for the new Vanilla paths.

## 4. Documentation and OpenSpec alignment

- [x] 4.1 Add `docs/vanilla-composition.md` with public path, ownership boundary, and migration notes.
- [x] 4.2 Update docs map and runbooks to distinguish Vanilla from the kind reference consumer.
- [x] 4.3 Add this OpenSpec change with proposal, design, spec, and task list for the implemented refactor.

## 5. Validation and review/QA gates

- [ ] 5.1 Run static/render/unit validation for the exact candidate.
- [ ] 5.2 Get independent comprehensive review returning `ready_for_qa` for the exact candidate.
- [ ] 5.3 Run safeguarded disposable kind+Flux QA of the reviewed exact candidate, including CrateCheck JSON green -> controlled red -> restored green.
- [ ] 5.4 Record candidate identity, cleanup, worktree/PR evidence, and final QA result.
