## ADDED Requirements

### Requirement: One documented retained local demo
Kubecrate SHALL provide one README-linked runbook for prerequisites, preflight, up, endpoints, inspection, evidence, restart, recreate, and down.

#### Scenario: A user follows the retained lifecycle
- **WHEN** a user follows the runbook from an exact remotely available checkout
- **THEN** `make local-check`, `make local-up`, `make local-status`, `make local-evidence`, and `make local-down` are available
- **AND** restart and recreate are documented
- **AND** successful up retains the named cluster until explicit down

#### Scenario: Current QA uses authenticated exact-PR access
- **WHEN** current QA validates a private repository candidate
- **THEN** it MAY use the authenticated direct runner against the exact PR revision
- **AND** anonymous access SHALL NOT be a current QA acceptance blocker
- **AND** future public upstreams or forks remain expected to support the retained demo through anonymously readable sources or runtime source overrides

### Requirement: Preflight binds inputs to an exact reconcilable revision
Before cluster creation, the retained workflow SHALL derive a URL and ref with runtime-only overrides, require a clean commit, and verify that the selected remote/ref advertises the exact commit. By default the retained Flux source has no credential Secret and its selected source SHALL be anonymously readable. Setting `KUBECRATE_LOCAL_GIT_BASIC_AUTH=1` SHALL opt into a credentialed path that sources basic-auth credentials, creates a Flux credential Secret, renders the source with a `secretRef`, and verifies the remote/ref with those credentials instead of anonymously.

#### Scenario: Selected source is exact and accessible
- **WHEN** clean checkout HEAD equals the SHA advertised for the selected URL and ref
- **THEN** preflight records the URL, ref, and full commit without requiring `gh`, tokens, keys, Doppler, or organization settings

#### Scenario: Private source via explicit basic-auth override
- **WHEN** `KUBECRATE_LOCAL_GIT_BASIC_AUTH=1` is set and basic-auth credentials are available from `KUBECRATE_LOCAL_GIT_USERNAME`/`KUBECRATE_LOCAL_GIT_PASSWORD` or `git credential fill`
- **THEN** preflight verifies the remote/ref advertises the exact commit using those credentials
- **AND** bootstrap creates a `flux-system-sync` basic-auth Secret and renders the Flux source with a matching `secretRef`
- **AND** credentials are not recorded in state or evidence

#### Scenario: Exactness cannot be proven
- **WHEN** the checkout is dirty, HEAD is invalid, the URL/ref is ambiguous, anonymous access fails without the override, credentialed access fails with the override, or the advertised SHA differs
- **THEN** preflight exits non-zero with its phase and recovery command
- **AND** kind cluster creation does not run
- **AND** existing state and evidence remain byte-for-byte unchanged
- **AND** the probe ignores repository, user, system, and injected Git configuration and credential mechanisms while retaining TLS verification

### Requirement: Up reconciles the current stack with bounded readiness
Up SHALL create or reuse only its named retained kind cluster, bootstrap Flux, reconcile the exact source revision, and validate Flux, External Secrets Operator, Envoy Gateway, cert-manager, Kyverno, CrateCheck, and their smoke consumers with bounded waits.

#### Scenario: Up reaches retained green
- **WHEN** preflight succeeds and no incompatible state exists
- **THEN** the named cluster becomes Ready on its explicit context
- **AND** the Flux source, root, and child Kustomizations become Ready at the exact commit
- **AND** controller, workload, and native service checks pass
- **AND** CrateCheck matches the exact-green JSON schema
- **AND** HTTP on port `10080` and locally trusted HTTPS on port `10443` pass
- **AND** the cluster remains running

#### Scenario: Up fails after mutation
- **WHEN** a bounded mutation or readiness phase fails
- **THEN** state records the failed phase and recovery commands
- **AND** bounded sanitized evidence is retained, or any partial resource is proven cleaned

### Requirement: Status and evidence are deterministic
The workflow SHALL provide concise status and stable machine-readable evidence with deterministic noninteractive exits.

#### Scenario: Status inspects the retained demo
- **WHEN** status runs for coherent retained state
- **THEN** it reports context, nodes, exact Flux revision, GitRepository and Kustomizations, controllers, workloads, native service evidence, full CrateCheck JSON, HTTP, and trusted HTTPS
- **AND** it performs no cluster mutation
- **AND** any failed check returns non-zero

#### Scenario: Evidence is retained safely
- **WHEN** evidence is requested or up fails
- **THEN** bounded sanitized evidence is written under `.tmp/kubecrate-local/evidence/latest/`
- **AND** credentials, tokens, keys, and Secret values are not recorded
- **AND** `summary.json` uses `kubecrate.retained-demo.evidence/v1` with context, nodes, exact revision, Flux children, controllers, workloads, native consumers, CrateCheck, and endpoints
- **AND** missing prerequisites produce explicit unavailable sections instead of preventing the bundle

### Requirement: Lifecycle operations are state-aware and scoped
The workflow SHALL reuse matching state, expose restart and recreate, and scope down to the exact recorded cluster.

#### Scenario: Matching up is repeated
- **WHEN** up finds its recorded cluster at the same source URL, ref, and commit
- **THEN** it converges and validates that cluster instead of creating another

#### Scenario: Down proves exact absence
- **WHEN** down receives coherent workflow-owned state
- **THEN** it refuses protected, mismatched, or ambiguous cluster identity
- **AND** it accepts only `kubecrate-local` or a `kubecrate-local-` lowercase alphanumeric segmented name before state access, inventory, or mutation
- **AND** it deletes only the recorded cluster
- **AND** it proves absence before clearing active state

### Requirement: Behavioral tests exercise the shipped entrypoint
Kubecrate SHALL test the shipped local workflow with fake external commands.

#### Scenario: Entrypoint behavior regresses
- **WHEN** source exactness, pre-mutation ordering, readiness, schema, retention, redaction, or scoped cleanup breaks
- **THEN** focused tests fail without creating a real cluster or requiring credentials

#### Scenario: Destructive QA remains separate
- **WHEN** the retained workflow is used
- **THEN** it does not repurpose the direct E2E runner or execute controlled-red mutations
