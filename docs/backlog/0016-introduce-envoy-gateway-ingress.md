---
task_id: "0016"
title: "Introduce Envoy Gateway ingress"
status: "started"
depends_on: ["0011", "0014"]
openspec: "openspec/changes/introduce-envoy-gateway-ingress/"
---

## Goal

Introduce ingress as a platform service using Envoy Gateway on the kind-first local path, with an end-to-end proof that the validation application service is reachable through the ingress path.

## Notes

- Do not implement this from the backlog item alone. Expand it into OpenSpec before adding runtime files.
- Use Envoy Gateway as the ingress implementation unless the OpenSpec proposal discovers a blocking operational reason and records the decision explicitly.
- This task must include the kind plumbing needed to expose ingress locally. The current kind config is minimal, so the proposal should evaluate and define the required kind port mappings, listener ports, local hostnames, or other local access mechanics.
- Envoy Gateway is a platform service under the two-axis model and should be a GitOps-managed management unit unless a proposal explicitly justifies another lifecycle handling.
- The validation app from 0014 should be reachable through Envoy Gateway and report a green ingress check in both the status UI and status JSON.
- The ingress check should explain what is being validated and help distinguish likely failure areas: kind host-to-cluster port mapping, GatewayClass readiness, Gateway listener readiness, HTTPRoute attachment, service endpoints, DNS or local hostname assumptions, and application health.
- Keep the first ingress slice minimal: prove HTTP reachability for the validation app before adding TLS, multi-host routing, advanced policies, or production-grade exposure concerns.
- If Envoy Gateway needs a dedicated namespace, use the `core-<service-name>` pattern with a clear service name chosen in the OpenSpec proposal.
