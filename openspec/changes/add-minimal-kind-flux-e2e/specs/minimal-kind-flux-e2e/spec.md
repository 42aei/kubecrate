## ADDED Requirements

### Requirement: One command runs the direct E2E
Kubecrate SHALL provide one operator-facing command that creates a unique disposable kind cluster, bootstraps Flux, validates ESO and CrateCheck, restores controlled failure, and deletes the cluster.

#### Scenario: Successful direct run
- **WHEN** the command runs with required local tools and active `faksibot` repository access
- **THEN** it executes the complete workflow without manual deploy-key registration or intermediate remote-resource setup
- **AND** it exits zero only after restored green evidence and verified cluster deletion

### Requirement: The workflow uses an existing exact PR revision
The runner SHALL use PR #17’s existing remote branch and SHALL verify the PR head, remote branch head, and reconciled Flux artifact revision equal the expected commit. It SHALL NOT create a temporary Git ref or QA branch.

#### Scenario: Revision remains exact
- **WHEN** preflight and Flux reconciliation complete
- **THEN** PR head, remote branch head, expected commit, and observed Flux revision match
- **AND** the revision is recorded in evidence

#### Scenario: Branch revision differs
- **WHEN** any required revision differs from the expected commit
- **THEN** the run fails before product acceptance is reported
- **AND** no temporary remote ref is created

### Requirement: Flux uses runtime-only HTTPS credentials
The runner SHALL obtain credentials from the active `faksibot` GitHub CLI session at runtime and inject them only into the disposable cluster through a standard Flux HTTPS authentication Secret. It SHALL NOT create, enumerate, validate, or delete GitHub deploy keys.

#### Scenario: Credential is available
- **WHEN** the active `faksibot` session can read the repository
- **THEN** Flux authenticates to the HTTPS repository using an in-cluster Secret
- **AND** the credential is not committed, printed, retained in evidence, or exposed in command diagnostics

#### Scenario: Credential is unavailable or invalid
- **WHEN** the credential cannot be obtained or Flux authentication fails
- **THEN** the run exits nonzero with a stable phase diagnostic
- **AND** the disposable cluster is deleted
- **AND** no GitHub resource requires cleanup

### Requirement: Live mutations are confined to the disposable cluster
The runner SHALL generate a unique cluster name, use the matching explicit kubecontext for every live phase, and refuse known shared cluster names or context mismatches.

#### Scenario: Context is correct
- **WHEN** a Kubernetes or Flux mutation executes
- **THEN** its explicit context equals `kind-<unique-cluster-name>`

#### Scenario: Context is wrong
- **WHEN** the active or supplied context does not equal the expected disposable context
- **THEN** the runner stops before that mutation
- **AND** it does not fall back to a shared cluster

### Requirement: Flux bootstrap and reconciliation are proven
The runner SHALL install the pinned Flux components, apply the repository entrypoint with the HTTPS source override, wait for source and Kustomization readiness, and prove the observed source artifact revision equals the expected commit.

#### Scenario: GitOps-managed operation becomes ready
- **WHEN** Flux successfully reconciles the existing PR branch
- **THEN** required controllers, source, root Kustomization, ESO Kustomizations, and CrateCheck workload report Ready or Available
- **AND** the source artifact revision matches the expected commit

### Requirement: ESO consumption is proven directly
The runner SHALL verify ESO controller readiness, SecretStore readiness, ExternalSecret readiness, and strict decoding of the projected target Secret to `kubecrate-eso-smoke-ok`.

#### Scenario: Healthy projection
- **WHEN** ESO reconciliation is healthy
- **THEN** the target Secret exists
- **AND** strict decoding yields exactly `kubecrate-eso-smoke-ok`

#### Scenario: Projection is absent or wrong
- **WHEN** Kubernetes access fails, the field is absent, decoding fails, or the value differs
- **THEN** the run fails without printing encoded or decoded Secret values

### Requirement: CrateCheck proves green, controlled red, and restored green
The runner SHALL validate the exact enabled check identities and states in `/status.json` at baseline, controlled failure, and restoration.

#### Scenario: Baseline green
- **WHEN** projection is healthy
- **THEN** expected ESO checks are green in `/status.json`
- **AND** unrelated enabled checks are green

#### Scenario: Controlled red
- **WHEN** the runner removes the owned ExternalSecret in the disposable cluster
- **THEN** intended ESO checks become red in `/status.json`
- **AND** unrelated enabled checks remain green

#### Scenario: Restored green
- **WHEN** the runner restores the source fixture
- **THEN** the projected value again equals `kubecrate-eso-smoke-ok`
- **AND** `/status.json` returns to the exact green state

### Requirement: Cleanup deletes the disposable cluster
The runner SHALL trap normal exit and interruption, delete only the unique cluster it created, and verify that cluster is absent before reporting success.

#### Scenario: Cleanup succeeds
- **WHEN** the run completes or fails
- **THEN** the exact disposable cluster is deleted
- **AND** known shared clusters remain present and untouched

#### Scenario: Cleanup fails
- **WHEN** the exact disposable cluster remains after deletion
- **THEN** the run exits nonzero and reports that cluster name
- **AND** it does not introduce remote-resource recovery machinery

### Requirement: Implementation remains a bounded direct workflow
The implementation SHALL remain a linear E2E runner with focused tests and minimal support edits. It SHALL NOT implement temporary-ref lifecycle, deploy-key lifecycle, GitHub inventory parsing, remote ownership markers, or a generalized multi-service QA framework.

#### Scenario: Proposed implementation adds generalized machinery
- **WHEN** implementation requires a new remote-resource lifecycle, inventory parser, marker protocol, or generic scenario framework
- **THEN** work stops for explicit scope review before that machinery is added
- **AND** the direct workflow remains the default design

### Requirement: Delivery leaves PR #17 review-ready and unmerged
The card SHALL complete only after the exact reviewed candidate passes the direct live E2E, required repository checks are green, cleanup is verified, and PR #17 points to that candidate. The PR SHALL remain open and unmerged.

#### Scenario: Review-ready result
- **WHEN** all acceptance requirements pass
- **THEN** the delivery result includes PR URL, exact commit, static checks, Flux revision, ESO value assertion, `/status.json` green-red-green evidence, and cluster deletion proof
- **AND** PR #17 remains open and unmerged
