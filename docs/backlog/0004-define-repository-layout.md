---
task_id: "0004"
title: "Define repository layout"
status: "proposed"
depends_on: ["0001"]
---

## Goal

Define a repository layout that supports small vertical slices and keeps docs, bootstrap installation concerns, and GitOps-managed operation concerns clear.

## Notes

Reflect the two-axis model without creating too many top-level categories too early.

Favor a structure that stays navigable for contributors who are still learning the platform domain.

Future repository layout work should treat environments such as prod, staging, test, and local as an explicit design axis. That should be evaluated alongside lifecycle phase and workload category, without changing the current two-axis architecture model too early.

Evaluate layout patterns later rather than locking them now. That includes monorepo and split-repository approaches such as repo-per-environment, repo-per-team, or repo-per-app.
