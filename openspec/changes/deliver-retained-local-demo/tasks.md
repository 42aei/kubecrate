## 1. Contract and documentation

- [x] 1.1 Define the retained-demo proposal, design, specification, and tasks.
- [x] 1.2 Add a README-linked runbook for the lifecycle and recovery commands.

## 2. Retained workflow

- [x] 2.1 Add check, up, status, evidence, restart, recreate, and down subcommands.
- [x] 2.2 Verify exact source identity before mutation, with runtime-only overrides.
- [x] 2.3 Bootstrap and validate the current stack with bounded waits and exact-green CrateCheck proof.
- [x] 2.4 Retain state and bounded sanitized evidence for failures.
- [x] 2.5 Scope restart, recreate, and down to the recorded demo cluster.
- [x] 2.6 Add thin Make wrappers.

## 3. Validation

- [x] 3.1 Test source derivation, exactness, and pre-mutation failures through the shipped entrypoint.
- [x] 3.2 Test readiness/schema failures, redaction, evidence, idempotence, and scoped cleanup.
- [x] 3.3 Run OpenSpec, Bash, pytest, project validation, link, and diff checks.
- [x] 3.4 Keep live mutation, commit, push, PR, and release outside this pass.
- [x] 3.5 Cover review fixes for state preservation, cluster identity, Git isolation, bounded failures, evidence schema, and sanitization.
