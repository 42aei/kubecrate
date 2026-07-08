---
task_id: "0014"
title: "Create application service validation status app"
status: "started"
depends_on: ["0011"]
---

## Goal

Create the reusable application service validation fixture that future platform service slices use to prove real end-to-end consumption. This should be the first concrete follow-up split from 0011 because later platform service tasks need a common, AI-runnable way to report what is green and where failures likely are.

## Implementation direction

The validation app consumes the external CrateCheck image (`ghcr.io/42aei/cratecheck:main`) rather than embedding application runtime code in ConfigMaps. CrateCheck is a small Go binary that reads declarative YAML check definitions (CEL expressions evaluated against live Kubernetes resources) and exposes `/status.json` (JSON) and `/status` (HTML UI).

Key decisions:
- **Image consumption, not in-repo app**: Kubecrate declares the CrateCheck Deployment referencing the external image with no imagePullSecrets (anonymous/public pull).
- **ConfigMap holds only YAML StatusConfig**: No Python, JS, Go, or runtime code in ConfigMaps. The ConfigMap `cratecheck-status-config` carries a `status.yaml` with `apiVersion: status.cratecheck.io/v1alpha1` check definitions.
- **Read-only RBAC**: A ClusterRole (`cratecheck-readonly`) grants get access on resources the initial StatusConfig checks plus discovery API access. RBAC is kept minimal; each future platform service check may require expanding the ClusterRole.
- **Application service placement**: `application-services/cratecheck/base/` for reusable manifests; `clusters/kind-dev-misc-local/application-services/cratecheck/` for cluster binding.
- **GitOps-managed operation**: Wired through `clusters/kind-dev-misc-local/entrypoint/`, not bootstrap installation.

## Notes

- The validation app is an application service because it consumes platform services. It is not a platform service.
- CrateCheck exposes both a human-readable status UI and a machine-readable `/status.json` endpoint.
- Each CEL-based check reports status (`green`, `yellow`, `red`, `unknown`), the resource it evaluates, and diagnostic messages.
- Initial baseline checks: CrateCheck deployment readiness, namespace existence, ConfigMap presence.
- Future platform service slices add checks to the StatusConfig ConfigMap and expand RBAC as needed for secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior.
- AI-runnable validation fetches `/status.json` and asserts expected checks are green.

## OpenSpec

Active OpenSpec change: `openspec/changes/create-validation-status-app/`.

Implementation is in progress under the `wt/cratecheck-image-consumption` worktree. The OpenSpec proposal and design have been updated to reflect CrateCheck image consumption rather than in-repo app development.
