## Why

Backlog 0008 is the forcing planning pivot that keeps Kubecrate focused on the smallest installable tracer bullet. The first slice still needs to prove bootstrap installation through GitOps-managed operation on a kind-first local path, but it should do so with fewer moving parts: Flux controller installation, Flux self-management handoff, generated SSH deploy-key credentials for `flux2-sync`, and a `kubecrate-reconciliation-marker` reconciliation proof. This keeps the first vertical slice aligned with the project goal to point at a cluster and install before broadening platform services or application services scope.

## What Changes

- **Keep Flux as the first concrete GitOps controller**: Flux remains the first concrete GitOps controller for this change.
- **Pivot bootstrap direction to Flux Helm charts**: the first installable slice now targets bootstrap installation of Flux from Helm charts, with the resulting desired state prepared for GitOps-managed operation and Flux self-management handoff.
- **Record the Flux namespace exception explicitly**: the general platform service dedicated namespace rule remains `core-<service-name>`, but this slice keeps Flux in `flux-system` as an approved exception because Flux chart defaults and `flux2-sync` bootstrap conventions use `flux-system` for controllers and first sync objects.
- **Change the first Git auth path**: the first slice uses `flux2-sync` SSH deploy-key generation for the Flux `GitRepository` path. The generated public key is displayed or retrieved for operator registration with the Git provider, while the generated private key remains in-cluster as a Secret.
- **Remove ESO from the first tracer bullet**: External-Secrets Operator is not part of the first tracer bullet for this branch. ESO is deferred platform services work for a later branch or change, not removed from long-term options.
- **Keep the two-axis model explicit**: this change still preserves the two-axis model: lifecycle phase vs workload category. Bootstrap installation remains a lifecycle phase, not a service category. Future platform services and application services stay separate from the first reconciliation proof.
- **Retain the concrete cluster path and marker proof**: `clusters/<cluster>/entrypoint` remains the first GitOps reconciliation root, and `kubecrate-reconciliation-marker` remains the validation material used to prove reconciliation from version X to version Y.
- **Keep kind validation plumbing in scope**: repository-owned kind validation plumbing remains part of the slice because the first proof must still run on a prepared kind cluster.
- **Record the manual operator registration step**: bootstrap installation can create or expose the generated public key, but the operator must register that public key as a deploy key with the Git provider before Flux can reconcile successfully.

## Capabilities

### New Capabilities

- `first-installable-slice`: the first end-to-end bootstrap-to-GitOps vertical slice on a kind-first local path. Covers Flux controller installation, `flux2-sync` SSH deploy-key generation, Flux self-management handoff, a Flux-managed reconciliation marker proof, kind validation plumbing, and tracer bullet validation evidence.

### Modified Capabilities

None. No existing global OpenSpec specs exist to modify. This change revises the implementation direction inside `create-first-installable-slice` to keep the first tracer bullet thinner and more directly aligned with point at a cluster and install.

## Impact

- Re-centers the first installable slice on Flux Helm chart bootstrap installation plus `flux2-sync` SSH deploy-key generation.
- Removes ESO projection work from the first tracer bullet and classifies it as deferred platform services work for a later branch or change.
- Preserves Flux self-management handoff and the `kubecrate-reconciliation-marker` X→Y reconciliation proof as the first operator-visible outcome.
- Preserves the kind-first local path and concrete cluster-root direction under `clusters/<cluster>/entrypoint` while keeping runtime layout decisions minimal.
- Avoids any design direction that would require committed credential material in Helm values or other Git-managed files.
