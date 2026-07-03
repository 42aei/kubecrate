---
task_id: "0014"
title: "Create application service validation status app"
status: "started"
depends_on: ["0011"]
---

## Goal

Create the reusable application service validation fixture that future platform service slices use to prove real end-to-end consumption. This should be the first concrete follow-up split from 0011 because later platform service tasks need a common, AI-runnable way to report what is green and where failures likely are.

## Notes

- Do not implement this from the backlog item alone. Expand it into OpenSpec before adding runtime files.
- The validation app is an application service because it consumes platform services. It is not a platform service and should not be treated as operator-owned infrastructure beyond its role as a test fixture.
- The app should be deliberately small but polished: vibe-code it into a proper status panel page rather than a blank nginx page or one-off curl target.
- It should expose both:
  - a human-readable status UI;
  - a machine-readable status JSON endpoint.
- Each check should report status, what capability it is validating, what Kubernetes or platform area it exercises, and a troubleshooting explanation that helps pinpoint the likely failing layer when the check is not green.
- Initial check categories should be designed to grow with platform services: base app health, secret loading, ingress reachability, certificate/TLS status, observability signal path, and policy behavior.
- Keep the fixture minimal and kind-first. A small Go or Node app is acceptable; nginx is acceptable only if it can still provide the required status UI and JSON behavior without becoming awkward.
- The fixture should be reusable by later service-specific tasks instead of each task creating its own bespoke demo app.
- Acceptance should require AI-runnable validation commands that fetch the UI or JSON endpoint and assert the expected checks are green for the capabilities enabled in that slice.

## OpenSpec

Active OpenSpec change: `openspec/changes/create-validation-status-app/`.

Discovery is still required before implementation. The OpenSpec change is a draft scaffold until the validation app's user experience, status JSON contract, implementation approach, runtime placement details, and first-slice validation flow are confirmed.
