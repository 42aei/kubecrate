# AI repository guide

This guide helps AI agents and contributors find the right source of truth before changing Kubecrate. It is a map, not a replacement for the linked documents.

## Source-of-truth map

| Decision area | Source of truth | Use it before changing |
| --- | --- | --- |
| Agent guardrails, required project language, current phase boundaries | `AGENTS.md` | Any repository change, especially docs or runtime layout work. |
| Project model and two-axis framing | `docs/architecture.md` | Language about lifecycle phase, workload category, platform services, application services, bootstrap installation, or GitOps-managed operation. |
| Platform service and application service classification | `docs/platform-and-application-service-model.md` | Deciding whether a workload is platform services scope or application services scope. |
| `point at a cluster and install`, bootstrap installation boundaries, handoff evidence | `docs/bootstrap-installation-contract.md` | Changes that describe or affect bootstrap installation or the handoff into GitOps-managed operation. |
| GitOps-managed platform service management units and source-structure contract | `docs/gitops-component-management.md` | Changes to platform service structure, management-unit boundaries, or GitOps-managed operation. |
| Current concrete runtime layout | Existing runtime files under `platform-services/` and `application-services/` | Any runtime-adjacent documentation or implementation work. Inspect the actual files before assuming paths. |

Existing reusable runtime paths include the service bases under `platform-services/` and `application-services/`.

Do not infer new runtime directories from these examples. New runtime manifests, scripts, config, or directories require an explicit scoped change.

## Validation checklist

Validation depends on the type of change.

### Documentation changes

- Check changed docs for required project language: platform services, application services, bootstrap installation, GitOps-managed operation, and point at a cluster and install.

### Static manifest rendering

For changes touching existing Kubernetes manifests, Helm values, Kustomize overlays, or runtime-adjacent docs, run the repository manifest validation target.

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

For platform service changes, operational validation should include an end-to-end consumption proof where practical. A small application service fixture can prove the capability: loading a projected Secret, serving through ingress, using an issued certificate, emitting observable signals, or triggering expected policy behavior.
