## ADDED Requirements

### Requirement: One documented retained local demo
Kubecrate SHALL provide one README-linked runbook for prerequisites, preflight, up, endpoints, inspection, evidence, restart, recreate, and down.

#### Scenario: A user follows the retained lifecycle
- **WHEN** a user follows the runbook from an exact remotely available checkout
- **THEN** `make local-check`, `make local-up`, `make local-status`, `make local-evidence`, and `make local-down` are available
- **AND** restart and recreate are documented
- **AND** successful up retains the named cluster until explicit down

#### Scenario: Current private source uses deploy-key GitOps access
- **WHEN** current QA validates a private repository candidate
- **THEN** anonymous access SHALL NOT be a current QA acceptance blocker
- **AND** Flux source authentication SHALL use the existing SSH deploy-key contract for `Secret/flux-system-sync`
- **AND** future public upstreams or forks MAY use an explicit anonymous source override

### Requirement: Preflight binds inputs to an exact reconcilable revision
Before cluster creation, the retained workflow SHALL derive a URL and ref with runtime-only overrides, require a clean commit, and verify that the selected remote/ref advertises the exact commit. By default preflight SHALL use current operator Git credentials for this exactness proof and SHALL NOT copy those credentials into the cluster. The retained Flux source SHALL use `flux2-sync` SSH deploy-key generation by default. Setting `KUBECRATE_LOCAL_ANONYMOUS_SOURCE=1` SHALL explicitly opt into a public-source path that probes anonymously and renders Flux without a Git credential Secret.

#### Scenario: Selected source is exact and accessible
- **WHEN** clean checkout HEAD equals the SHA advertised for the selected URL and ref
- **THEN** preflight records the URL, ref, and full commit without requiring `gh`, Doppler, organization settings, or cluster-bound credentials

#### Scenario: Flux source uses generated deploy key by default
- **WHEN** the retained workflow bootstraps Flux for a private source
- **THEN** bootstrap renders the selected repository and ref as an SSH Flux source
- **AND** `flux2-sync` creates `Secret/flux-system-sync` with generated SSH identity material
- **AND** the operator can retrieve the generated public key from `identity.pub` for deploy-key registration
- **AND** no PAT, username/password, or operator Git credential is recorded in state, evidence, or a cluster Secret by the retained workflow

#### Scenario: Anonymous public source is explicit opt-in
- **WHEN** `KUBECRATE_LOCAL_ANONYMOUS_SOURCE=1` is set
- **THEN** preflight verifies the remote/ref with a scrubbed anonymous probe
- **AND** bootstrap renders the Flux source without a Git credential Secret

#### Scenario: Exactness cannot be proven
- **WHEN** the checkout is dirty, HEAD is invalid, the URL/ref is ambiguous, Git access fails, anonymous access fails with the explicit override, or the advertised SHA differs
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
