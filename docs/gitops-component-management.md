# GitOps Component Management

Kubecrate manages platform services as separately targetable units under GitOps-managed operation. Each service is installed, configured, and updated independently per concrete cluster. This document defines:

- The **management-unit contract**: what it means for a platform service to be separately targetable.
- The **minimal initial platform services set**: which services come first.
- The **source-structure contract**: the conceptual roles a GitOps source layout must express.
- The **packaging posture**: contract-first; concrete packaging is chosen later.

This document is a durable reference, not a runnable implementation. It builds on the [architecture](architecture.md) (two-axis model) and the [bootstrap installation contract](bootstrap-installation-contract.md) (handoff into GitOps-managed operation). Where this document records first-slice implementation direction, that material is labeled explicitly so the broader contract stays clear.

## Management-unit contract

A **management unit**, or **service unit**, is one separately targetable GitOps-managed platform service.

### Contract requirements

A management unit MUST satisfy all of the following:

#### Independent installation

A management unit can be installed in a target cluster without requiring all other platform services in that cluster. Installing or updating External-Secrets Operator in one staging cluster does not require cert-manager, ingress, or any other platform service to be present or reconciled first.

Independent targeting does not mean a management unit has no dependencies. Dependencies between services are expected — an application depends on ingress, which depends on certificate management. Ordering and dependencies are expressed through simple source-structure conventions (layer or name ordering, similar in spirit to systemd-style naming) and are enforced by the selected GitOps controller when implementation happens. The first implementation that needs ordering must show how the chosen controller makes dependency order clear and enforceable. Kubecrate does not introduce custom dependency metadata files, unit descriptors, generated graphs, or bespoke dependency models.

#### Environment-specific configuration

A management unit accepts cluster-specific configuration (values, overlays, or equivalent binding data) without changing the shared definition of the service. The same service definition can target multiple conforming clusters with different binding data.

Shared defaults live with the service definition. Cluster binding records only real cluster-specific overrides or references, avoiding noisy defaults repeated in every cluster.

#### No umbrella bundle lock-in

No management unit is locked inside a single indivisible umbrella bundle that blocks per-service or per-environment operations. A monochart or monolithic overlay that forces all platform services to deploy or update together violates this contract.

Dependency orchestration (coordinating related services that genuinely depend on each other) is allowed. The prohibition is against forcing unrelated platform services into one indivisible bundle.

#### Future wave-like promotion

The contract preserves wave-like promotion as a firm capability. A management unit can be promoted across concrete clusters in a wave-like pattern, and those concrete clusters may represent different environments. Per-cluster targeting and per-cluster configuration are the foundation that enables wave-like promotion. The specific promotion mechanism, environment sequencing, and gating are deferred to a later change, but the capability is a preserved design requirement, not an open question.

### Why contract-first

The contract is packaging-agnostic. It can be satisfied by a Helm release, a Kustomize overlay, a Flux HelmRelease or Kustomization, an Argo CD Application, or another GitOps controller wrapper, provided the controller support exists. The contract constrains the *behavior* of a management unit, not the packaging format used to express it.

Controller-specific objects (Argo CD Applications, Flux Kustomizations, etc.) are replaceable adapters for the selected GitOps controller. They are not the portable contract. The durable expression of a management unit must remain separable from any particular controller so that replacing the controller later does not require redefining every service. Bootstrap installation must not depend on a GitOps provider to install the controller itself.

## Minimal initial platform services set

The two-axis model separates lifecycle phase (bootstrap installation or GitOps-managed operation) from workload category (platform services or application services). The initial platform services set follows this model.

### GitOps controller (bootstrap-installed, not a management unit)

The GitOps controller is installed during bootstrap installation because it is required for handoff into GitOps-managed operation. The management-unit contract applies to platform services under GitOps-managed operation. Because the controller is bootstrap-installed and not yet under GitOps-managed operation at handoff time, it is not classified as a management unit under this change's contract. This is not an exception to the contract — the contract governs a different lifecycle phase.

After handoff into GitOps-managed operation, the bootstrap-installed controller and supporting bootstrap resources are expected to come under GitOps-managed operation. Only the concrete mechanics of how those bootstrap resources are brought under GitOps-managed operation are deferred.

The durable contract in this document does not require a controller choice. The first installable slice does make a first concrete controller choice, and that direction is recorded below without changing the broader controller-agnostic contract.

#### First-slice controller and handoff direction

The first concrete GitOps controller for the first installable slice is **Flux**.

Flux uses a self-managing handoff model for the first slice. Bootstrap installation should apply or reference the same Flux desired-state path that Flux later reconciles. There must not be duplicate independent Flux definitions under bootstrap installation and platform services. Bootstrap installation is a loader or reference, not a second source of truth.

#### Bootstrap trust: operator-provided inputs

Bootstrap installation is responsible for receiving, collecting, or generating the trust inputs needed to start bootstrap-critical services. In the first slice, Flux Git access is established through the `flux2-sync` SSH deploy-key generation path: the `flux-system-sync` chart release creates `Secret/flux-system-sync`, `GitRepository/flux-system-sync`, and `Kustomization/flux-system-sync`, and the operator registers the generated public key as a read-only deploy key with the Git provider.

Bootstrap-critical services may be installed during bootstrap installation and then handed off to GitOps-managed operation. Whether a service is bootstrap-installed or first installed under GitOps-managed operation depends on its operational needs. This document states the input rule without prematurely classifying every service. When a later change introduces a concrete service, that change resolves whether the service follows the bootstrap-install-handoff path or the direct GitOps-managed path.

### External-Secrets Operator (deferred platform service)

**External-Secrets Operator (ESO)** is deferred outside the first installable slice. The first slice proves Flux bootstrap installation and GitOps-managed operation without requiring ESO projection first.

ESO remains a platform service candidate. A later change can introduce it with its own bootstrap or GitOps-managed acceptance criteria when the secret-management need is concrete.

Kubecrate does not require Seed Secrets for the first Flux tracer bullet. The broader first-secret problem remains open for later secret-management work.

When ESO is introduced later, services and controllers should consume narrow projected Secrets in the namespaces they actually use rather than broad bootstrap input Secrets.

The deferred ESO path should standardize how operator-supplied trust material enters the cluster and how that material is narrowed before services consume it.

#### Local ESO provider direction

When ESO is introduced, it needs a provider that can read operator-supplied or bootstrap-created trust material and project narrower Secrets from it.

The **Fake provider** can be used as a simple ESO contract test, but it does not validate a real trust-material flow by itself.

The implementation should therefore use the **ESO Kubernetes provider**, or an equivalent provider with the same capability, when that deferred secret-management path is implemented.

Real providers (AWS Secrets Manager, GCP Secret Manager, Vault, or others) can be introduced later as provider-specific needs arise, without changing the management-unit contract or the source structure.

### Deferred platform services

The following platform services are deferred to later changes. The project posture of minimal over comprehensive applies: start with the smallest set needed to demonstrate a working GitOps-managed lifecycle, and grow only when there is a clear operational reason.

- **Ingress** — deferred. Required before application services can receive external traffic, but not needed for the first tracer bullet.
- **Certificate management** — deferred. Required before TLS-terminated ingress is available, but not needed for the first installable slice.
- **Observability** — deferred. Required for operational visibility, but not needed to validate the management-unit contract.
- **Policy** — deferred. Required for governance and compliance, but not needed for the first management-unit implementation.
- **External-Secrets Operator** — deferred. Required when Kubecrate needs a real secret projection platform service, but not needed for the first Flux SSH deploy-key tracer bullet.

These services are deferred, not excluded. Each can be introduced in a later change when its operational need is clear.

## Source-structure contract

The GitOps source structure must express the conceptual roles needed to support the management-unit contract and targeted rollout, building on the roles already defined in the [bootstrap installation contract](bootstrap-installation-contract.md#gitops-source-structure-roles).

### Conceptual roles

| Role | What it expresses |
| --- | --- |
| **GitOps entrypoint** | The reconciled entrypoint that defines what the controller starts from. |
| **platform services** | One management unit per platform service. Each unit can be reused across multiple concrete cluster bindings. |
| **application services** | One or more units for application workloads (not implemented in this change). |
| **cluster binding** | Configuration that binds management units to a concrete cluster. This includes values, overlays, destination settings, versions, or controller-specific binding data. |
| **ordering and ownership boundaries** | A way to keep reconciliation order and responsibility understandable, especially between platform services and cluster binding. |

These roles are conceptual, but the first installable slice is concrete enough to state the required initial runtime layout for real services.

### First-slice layout direction

A real platform service uses `platform-services/<service>/base/` for its reusable service definition.

Concrete cluster directories explicitly enable and configure those services under `clusters/<cluster>/platform-services/<service>/`.

`clusters/<cluster>/entrypoint` is the intended first GitOps reconciliation root or table of contents for that concrete cluster.

Temporary cluster-local platform service implementations are forbidden unless a scoped change explicitly allows them with a removal plan.

This follows the general shape of Flux's recommended monorepo pattern where each cluster state is defined in a dedicated cluster directory that references shared infrastructure or app definitions. In Kubecrate terms, those reusable definitions are `platform services` and `application services`, not generic infrastructure or apps, unless the Flux pattern itself is being cited.

The intended first model is concrete cluster directories, not reusable shared layers or profiles. Environment remains a preserved capability in this model because the concrete cluster identity can encode environment and later promotion policy can build on that. If duplication later becomes an operational problem, Kubecrate can revisit layered variants explicitly.

Only the tracer bullet runtime files that are actually needed should be introduced in the first installable slice. Empty skeleton directories are still out of scope.

### Concrete cluster identity

The first concrete cluster directory convention is `<provider>-<environment>-<workload>-<location>`.

Examples include `gcp-prod-web-eu1`, `gcp-prod-web-us1`, `gcp-prod-storage-eu1`, `gcp-staging-web-eu1`, `gcp-staging-storage-eu1`, and `aws-prod-web-eu1`.

This is a pragmatic convention for concrete cluster directories, not an immutable taxonomy.

### Cluster binding separation

Cluster binding MUST be separable per management unit. A single platform service can be updated in one cluster without affecting other clusters. This separation is what enables targeted rollout and the future ability of wave-like promotion.

Version selection and configuration selection happen at the cluster binding layer, not only in the reusable service base. In practice, one cluster can stay on one version of a platform service while another cluster moves ahead first. That makes targeted rollout possible without introducing extra shared profile layers up front.

### First-slice repository boundary direction

The first concrete runtime files for the tracer bullet should live in this repository. Template or example repository indirection is not part of the first slice.

This is a first-slice direction, not a permanent rule that closes every future repository boundary decision. A later change can revisit broader repository boundaries if there is a clear operational reason.

## Packaging posture

Kubecrate adopts a **contract-first** packaging posture. Concrete packaging can be chosen later provided the choice satisfies the management-unit contract.

### Candidate formats

The following packaging formats are identified as candidates that can satisfy the management-unit contract. No single format is selected as final.

| Format | How it satisfies the contract |
| --- | --- |
| **Helm** | A Helm release can be a management unit. Cluster-specific values files or `--set` overrides provide binding. |
| **Kustomize** | A Kustomize overlay can be a management unit. Patches and overlays provide cluster-specific binding. |
| **Controller wrappers** | Flux HelmRelease or Kustomization objects, or Argo CD Application objects, can wrap either format and provide additional reconciliation features. |

The first bootstrap path installs Flux controllers with Helm, then hands off to GitOps-managed HelmRelease resources for Flux self-management and `flux2-sync`. Helm remains an acceptable packaging format inside GitOps-managed operation, including HelmRelease for Helm-native platform services.

### Forcing function

The first change that implements a management unit is the forcing function for packaging selection. That change MUST validate that the chosen packaging satisfies the management-unit contract defined here.

## Deferred decisions

The following decisions are explicitly deferred. Each includes the rationale and the forcing function that will resolve it.

| Decision | Rationale | Forcing function |
| --- | --- | --- |
| **Additional platform services** (ingress, certificate management, observability, policy, secret projection) | The project posture is minimal over comprehensive. The first installable slice proves Flux bootstrap installation and GitOps-managed operation before adding more platform services. Additional services stay deferred unless a concrete operational need is clear. | A later change that introduces a specific platform service when its operational need is clear. |
| **Shared profile layers or reusable environment overlays** | The first installable slice uses concrete cluster directories first. Shared layers can be reconsidered later if duplication becomes a clear operational problem. | A later change that has enough duplication evidence to justify a more layered source structure. |

No deferred decision is indefinite or unresolvable. Each has a clear forcing function tied to a concrete future change.

## Non-runnable boundary

This document defines intent and contracts. It does not introduce:

- Kubernetes manifests (Deployments, Services, ConfigMaps, or any other Kubernetes resources)
- Helm charts or Kustomize overlays
- Installation scripts or CLI implementations
- Technical skeleton directories
- Runtime platform component implementations

The first installable slice that implements a management unit will introduce runnable artifacts. This document provides the contract those artifacts must satisfy.
