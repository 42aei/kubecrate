## 1. Management-unit contract specification

- [ ] 1.1 Define each platform service as a separately targetable GitOps-managed management unit in the spec.
- [ ] 1.2 Define the management-unit contract requirements: independent installation, environment-specific configuration, avoidance of umbrella bundle lock-in.
- [ ] 1.3 Document the management-unit contract in a new `docs/gitops-component-management.md` reference document.
- [ ] 1.4 Add spec scenario for future wave-like promotion: per-environment rollout as the foundation, wave-like progression as a later capability.

Acceptance checks:
- `docs/gitops-component-management.md` defines a management unit as a separately targetable GitOps-managed platform service.
- The contract specifies that a management unit supports independent installation, environment-specific configuration, and avoids umbrella bundle lock-in.
- The spec includes a scenario for each contract requirement.
- The spec includes an explicit scenario for future wave-like promotion that distinguishes per-environment targeting from wave-like progression across environments.

## 2. Minimal platform services set selection

- [ ] 2.1 Document that the GitOps controller is installed during bootstrap installation and hands off into GitOps-managed operation. The controller is not classified as a GitOps-managed management unit under this change's contract. The bootstrap-installed controller and supporting resources are expected to come under GitOps-managed operation after handoff; only the concrete mechanics of how are deferred.
- [ ] 2.2 Name External-Secrets Operator as the first GitOps-managed platform service.
- [ ] 2.3 Recommend the Fake provider as the local secret-handling baseline for the kind-first local path.
- [ ] 2.4 Explicitly defer additional platform services (ingress, certificate management, observability, policy) to later changes.

Acceptance checks:
- The spec identifies the GitOps controller as bootstrap-installed for handoff, not classified as a management unit, with the expectation that bootstrap resources come under GitOps-managed operation after handoff (mechanics deferred).
- The spec names External-Secrets Operator as the first GitOps-managed platform service.
- The spec recommends the Fake provider for the kind-first local path and notes real providers can be introduced later.
- The spec defers additional platform services without implying they are out of scope permanently.

## 3. Source-structure contract

- [ ] 3.1 Define the conceptual source-structure roles building on the bootstrap installation contract: GitOps entrypoint, platform services (one management unit each), application services, environment binding, ordering and ownership boundaries.
- [ ] 3.2 Define that environment binding must be separable per management unit.
- [ ] 3.3 Keep source-structure roles conceptual and avoid mandating final directory paths or file names.
- [ ] 3.4 Document that the repository boundary question from backlog 0010 (one-stop-shop vs template/example repos) is deferred to the first installable slice or source-layout implementation, with a clear forcing function.

Acceptance checks:
- The spec defines source-structure roles that distinguish platform services as separate management units.
- The spec requires environment binding to be separable per management unit.
- The spec does not mandate final directory paths, environment directory names, or file-level layouts.
- The spec and design state that the final repository boundary is deferred; a reader can tell this change does not decide it and knows what future forcing function will.

## 4. Packaging posture decision

- [ ] 4.1 Document the contract-first packaging posture: concrete packaging can be chosen later provided it satisfies the management-unit contract.
- [ ] 4.2 Identify Helm, Kustomize, and controller wrappers (Flux/Argo) as candidates without selecting one as final.
- [ ] 4.3 State that the first management-unit implementation change is the forcing function for packaging selection.

Acceptance checks:
- The design documents a contract-first packaging posture.
- The design identifies Helm, Kustomize, and controller wrappers as candidates.
- The spec requires any future packaging choice to satisfy the management-unit contract.

## 5. Deferred decisions record

- [ ] 5.1 Explicitly defer the GitOps controller choice with rationale.
- [ ] 5.2 Explicitly defer final packaging format choice with rationale.
- [ ] 5.3 Explicitly defer additional platform services with rationale.
- [ ] 5.4 Explicitly defer environment-specific directory structure with rationale.

Acceptance checks:
- The design records each deferred decision with a rationale that references a specific forcing function or future change.
- No deferred decision is framed as indefinite or unresolvable.

## 6. Backlog hygiene and repository integration

- [x] 6.1 Update `docs/backlog/0007-choose-minimal-component-set.md` frontmatter status from `proposed` to `started` and add a short note pointing to this OpenSpec change.
- [x] 6.2 Update `docs/backlog/0010-define-gitops-source-structure.md` frontmatter status from `proposed` to `started` and add a short note pointing to this OpenSpec change.
- [ ] 6.3 Link `docs/gitops-component-management.md` from `docs/README.md`.

Acceptance checks:
- Both backlog items show status `started` and reference `openspec/changes/define-gitops-component-management/`.
- `docs/README.md` lists the new document.
- The updated artifacts preserve the required project vocabulary and two-axis architecture model.

## 7. Validation

- [ ] 7.1 Run `openspec validate define-gitops-component-management --type change --strict --json --no-interactive` and resolve any errors.
- [ ] 7.2 Run `openspec status --change define-gitops-component-management --json` and confirm all required artifacts are present.
- [ ] 7.3 Verify no Kubernetes manifests, installation scripts, or technical skeleton directories were added.
- [ ] 7.4 Verify required project vocabulary and two-axis model are preserved across all change artifacts.

Acceptance checks:
- `openspec validate` exits successfully with no validation errors.
- `openspec status` reports all `apply.requires` artifacts with status `done`.
- grep/search confirms no runtime manifests, scripts, or skeleton directories were added.
- grep/search confirms required terms are present and competing terminology is absent.
