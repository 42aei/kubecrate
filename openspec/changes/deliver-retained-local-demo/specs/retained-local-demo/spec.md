## ADDED Requirements

### Requirement: Public users can run one documented retained local demo
Kubecrate SHALL provide one prominent README-linked runbook for the kind-first local path covering supported prerequisites, public clone or fork, preflight, up and bounded readiness, endpoints, inspection, diagnostics, restart, recreate, and explicit down.

#### Scenario: Fresh public checkout follows the retained lifecycle
- **WHEN** a user anonymously clones a public upstream repository or public fork and follows the runbook
- **THEN** stable `make local-check`, `make local-up`, `make local-status`, `make local-evidence`, and `make local-down` interfaces are available
- **AND** explicit restart and recreate interfaces are documented
- **AND** successful up leaves the named cluster running until explicit down

### Requirement: Preflight binds local inputs to an anonymously reconcilable exact revision
The workflow SHALL derive a public URL and ref from the checkout with runtime-only overrides and SHALL fail before cluster creation when the candidate is dirty, the selected source is not anonymously accessible, the selected commit is unavailable at the selected remote/ref, or Flux cannot reconcile the exact selected commit.

#### Scenario: Public upstream or fork is exact and accessible
- **WHEN** the clean checkout HEAD equals the anonymously advertised SHA for the selected public URL and ref
- **THEN** preflight records the URL, ref, and full commit without requiring `gh`, tokens, keys, Doppler, private credentials, or organization settings

#### Scenario: Exactness cannot be proven
- **WHEN** the worktree is dirty, HEAD is not a commit, the URL/ref is ambiguous, anonymous access fails, or the advertised SHA differs
- **THEN** preflight exits non-zero with a phase and recovery message
- **AND** no kind cluster creation command is executed
- **AND** any existing recorded state and evidence remain byte-for-byte unchanged
- **AND** anonymous probing ignores repository, user, system, injected Git configuration and credential mechanisms while retaining public TLS verification

### Requirement: Up reconciles the complete current stack with bounded readiness
Up SHALL create or reuse only its named persistent kind cluster, bootstrap Flux, reconcile the exact source revision, and validate Flux, External Secrets Operator, Envoy Gateway, cert-manager, Kyverno, CrateCheck, and their smoke consumers with bounded waits.

#### Scenario: Up reaches retained green
- **WHEN** preflight succeeds and no incompatible state exists
- **THEN** the named cluster becomes Ready on its explicit context
- **AND** Flux source and root and child Kustomizations become Ready at the exact selected commit
- **AND** controller, workload, and service-native readiness checks succeed
- **AND** the full CrateCheck JSON matches the exact green schema
- **AND** HTTP on port 10080 and locally trusted HTTPS on port 10443 are reported
- **AND** the cluster remains running

#### Scenario: Up fails after mutation
- **WHEN** any bounded mutation or readiness phase fails
- **THEN** state records the failed phase and recovery commands
- **AND** bounded sanitized evidence is retained for inspection, or any partial resource is proven cleaned

### Requirement: Status and evidence are deterministic and inspectable
The workflow SHALL provide concise human status and stable machine-readable evidence with deterministic noninteractive exits.

#### Scenario: Read-only status inspects the retained demo
- **WHEN** status runs for coherent retained state
- **THEN** it explicitly reports context, nodes, exact Flux revision, GitRepository and Kustomizations, controllers, workloads, ESO projection evidence, Envoy resources, cert-manager resources, Kyverno resources, full CrateCheck JSON, HTTP, and trusted HTTPS
- **AND** it performs no cluster mutation
- **AND** any failed check causes a non-zero exit

#### Scenario: Evidence is retained safely
- **WHEN** evidence is requested or up fails
- **THEN** bounded sanitized evidence is written under `.tmp/kubecrate-local/evidence/latest/`
- **AND** source credentials, tokens, keys, and Secret values are not recorded
- **AND** `summary.json` uses `kubecrate.retained-demo.evidence/v1` with structured context, nodes, exact revision, Flux children, controllers, workloads, native consumers, CrateCheck, and endpoints
- **AND** unavailable prerequisites produce explicit unavailable sections rather than preventing the bundle

### Requirement: Lifecycle operations are state-aware and scoped
The retained workflow SHALL be idempotent for matching state, expose explicit restart and recreate behavior, and scope down to the exact recorded cluster.

#### Scenario: Matching up is repeated
- **WHEN** up finds its recorded cluster at the same source URL, ref, and commit
- **THEN** it validates and converges that cluster instead of creating a second cluster

#### Scenario: Down proves exact absence
- **WHEN** down receives coherent workflow-owned state
- **THEN** it refuses protected, mismatched, or ambiguous cluster identity
- **AND** accepts only `kubecrate-local` or a `kubecrate-local-` lowercase alphanumeric segmented name before any state write, inventory, or mutation
- **AND** deletes only the recorded cluster
- **AND** proves that cluster is absent before clearing active state

### Requirement: Behavioral tests exercise the shipped entrypoint
Kubecrate SHALL include red-capable tests that invoke the shipped local workflow with fake external commands rather than only checking helper internals.

#### Scenario: Entry-point behavior regresses
- **WHEN** source derivation/access/exactness, pre-mutation ordering, readiness, schema, retention, redaction, or scoped cleanup behavior is broken
- **THEN** focused automated tests fail without creating a real cluster or requiring credentials

#### Scenario: Destructive QA remains separate
- **WHEN** the retained workflow is implemented
- **THEN** it does not repurpose the destructive direct E2E runner or execute controlled-red mutations
