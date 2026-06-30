# AI repository guide

This guide helps AI agents and contributors find the right source of truth before changing Kubecrate. It is a map, not a replacement for the linked documents.

## Source-of-truth map

| Decision area | Source of truth | Use it before changing |
| --- | --- | --- |
| Agent guardrails, required project language, current phase boundaries | `AGENTS.md` | Any repository change, especially docs, backlog, OpenSpec, or runtime layout work. |
| Project model and two-axis framing | `docs/architecture.md` | Language about lifecycle phase, workload category, platform services, application services, bootstrap installation, or GitOps-managed operation. |
| Platform service and application service classification | `docs/platform-and-application-service-model.md` | Deciding whether a workload is platform services scope or application services scope. |
| `point at a cluster and install`, bootstrap installation boundaries, handoff evidence | `docs/bootstrap-installation-contract.md` | Changes that describe or affect bootstrap installation or the handoff into GitOps-managed operation. |
| GitOps-managed platform service management units and source-structure contract | `docs/gitops-component-management.md` | Changes to platform service structure, management-unit boundaries, or GitOps-managed operation. |
| kind-first local path workflow | `docs/kind-local-workflow.md` | Changes that describe local setup, kind validation, or the local reference path. |
| Lightweight backlog capture and readiness rules | `docs/backlog/README.md` and `docs/backlog/*.md` | Creating, updating, starting, completing, or evaluating backlog items. |
| Proposed, active, or completed scoped changes | `openspec/changes/<change-name>/` | Expanding ready backlog work into a scoped proposal, design, task list, or spec delta. |
| Current concrete runtime layout | Existing runtime files under `clusters/` and `platform-services/` | Any runtime-adjacent documentation or implementation work. Inspect the actual files before assuming paths. |

Existing concrete runtime paths include:

- `clusters/kind-dev-misc-local/entrypoint/` — the first GitOps reconciliation root for the kind-first local path.
- `clusters/kind-dev-misc-local/platform-services/flux/` — the concrete cluster binding for Flux on `kind-dev-misc-local`.
- `platform-services/flux/base/` — the reusable Flux platform service base.

Do not infer new runtime directories from these examples. New runtime manifests, scripts, config, or directories require an approved OpenSpec change that explicitly authorizes them.

## Backlog-to-OpenSpec readiness

Backlog items are lightweight raw captures. A backlog item with `status: "proposed"` is only a candidate for evaluation, not permission to create an OpenSpec change.

Before creating or expanding an OpenSpec change from backlog work, return one readiness verdict:

- `ready for OpenSpec` — the item is large and concrete enough for a scoped change, with a clear operator-visible or user-visible outcome and acceptance criteria.
- `not ready` — the item is too small, stale, superseded, or better handled as discussion or routine documentation cleanup.
- `unclear` — the item may be useful, but scope, acceptance criteria, or the outcome are missing. Default to `unclear` when in doubt and identify the next decision or outcome to clarify.

Keep backlog entries lightweight. Do not add a heavy required template just to make an idea look ready.

### Examples

A backlog note should stay as discussion when it says only: "Consider another platform service later." That does not yet name the platform service, the operator-visible need, whether it belongs in bootstrap installation or GitOps-managed operation, or how it affects the kind-first local path.

A backlog note may be ready for OpenSpec when it says: "Introduce one concrete platform service under GitOps-managed operation for the kind-first local path, with a reusable base under `platform-services/<service>/base/`, a concrete binding under `clusters/kind-dev-misc-local/platform-services/<service>/`, and acceptance checks that prove static rendering plus the required operational evidence." That has a concrete slice, preserves the two-axis model, and can produce reviewable tasks.

## Validation checklist

Validation depends on the kind of change.

### Docs, backlog, and OpenSpec planning changes

- Validate relevant OpenSpec changes, for example:
  - `openspec validate ai-enable-repository-structure --type change --strict --json --no-interactive`
- If a change has OpenSpec tasks or status to confirm, inspect it with:
  - `openspec status --change ai-enable-repository-structure --json`
- Check changed docs for required project language: platform services, application services, bootstrap installation, GitOps-managed operation, kind-first local path, and point at a cluster and install.

### Static manifest rendering

For changes touching existing Kubernetes manifests, Helm values, Kustomize overlays, or runtime-adjacent docs, run the relevant static rendering command. For the current kind-first local path entrypoint:

- `kustomize build clusters/kind-dev-misc-local/entrypoint`

Static rendering, schema checks, and build validation are necessary but not sufficient whenever bootstrap installation or GitOps-managed operation applies or reconciles Kubernetes resources.

### Operational Kubernetes validation

Before claiming success for a change that applies or reconciles Kubernetes resources through bootstrap installation or GitOps-managed operation, collect operational evidence for:

- intended cluster context,
- expected resources,
- controller and workload health,
- readiness or sync conditions,
- recent events or logs for blocking errors, and
- the operator-visible outcome.

If those checks are failing or inconclusive, do not claim success. Keep deeper diagnosis symptom-driven and tied to the failing layer.
