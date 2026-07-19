---
task_id: "0017"
title: "Introduce cert-manager certificate management"
status: "done"
depends_on: ["0011", "0014", "0016"]
openspec_change: "introduce-cert-manager-certificate-management"
---

## Goal

Introduce cert-manager as the certificate management platform service for the kind-first local path, with an end-to-end proof that the validation application service is reachable over TLS using an issued certificate.

## Notes

- Do not implement this from the backlog item alone. Expand it into OpenSpec before adding runtime files.
- This task should build on the ingress path from 0016 unless the proposal explicitly decides to validate certificate management independently first.
- cert-manager is a platform service under the two-axis model and should be a GitOps-managed management unit unless a proposal explicitly justifies another lifecycle handling.
- The first kind-first certificate path should stay local and minimal. The proposal should decide whether to use a self-signed issuer, CA issuer, or another local issuer pattern that proves certificate issuance without requiring external DNS or public ACME.
- The validation app from 0014 should be reachable through the ingress path over TLS and report a green certificate/TLS check in both the status UI and status JSON.
- The certificate check should explain what is being validated and help distinguish likely failure areas: cert-manager controller health, Issuer or ClusterIssuer readiness, Certificate readiness, Secret creation, Gateway or route TLS binding, trust chain expectations for local validation, and client-side verification behavior.
- Keep the first certificate management slice focused on proving issuance and use for the validation app. Public ACME, DNS-01, production issuer policy, and multi-environment certificate strategy can remain later work unless this proposal makes them necessary.
- If cert-manager needs a dedicated namespace, use the `core-<service-name>` pattern with a clear service name chosen in the OpenSpec proposal.
