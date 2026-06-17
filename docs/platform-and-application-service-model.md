# Platform and application service model

This document defines the working model for platform services and application services. It is a practical owner's guide, not a taxonomy exercise.

## Two-axis model

Kubecrate separates concerns along two axes. Keep them distinct:

- **lifecycle phase**: bootstrap installation or GitOps-managed operation
- **workload category**: platform services or application services

Bootstrap installation is a lifecycle phase, not a third workload category. This document focuses on the workload category axis and assumes the lifecycle distinction is already understood.

## Platform services

A platform service is a shared capability maintained as part of the platform. It helps ensure applications are hosted and served reliably and can be deployed and managed easily by developers without deep knowledge of the platform.

Platform services may require deeper insight into Kubernetes and platform internals than application services. Common examples include ingress controllers, certificate management, secret-handling components, observability building blocks, and GitOps controllers.

Platform services are operator-owned. The operator or platform team selects, installs, and maintains them based on the needs of the applications they host. Application developers should not need to configure, troubleshoot, or reason about platform service internals beyond their documented interfaces.

## Application services

Application services are the user or company workloads that consume the platform. They are the workloads people want to run once the shared platform capabilities exist.

Application services are developer-owned. Application developers are expected to understand what is within application service scope — their own application code, configuration, and deployment concerns — not deep platform internals.

## Ownership and scope boundaries

| Concern | Platform scope | Application scope |
| --- | --- |
| Ingress routing rules | Defines the ingress controller and its operational configuration | Defines per-application routing rules (hosts, paths) |
| Certificate provisioning | Provides certificate management infrastructure | Requests certificates for application domains |
| Observability | Provides collection, storage, and dashboards | Emits metrics, logs, and traces in the expected format |
| Secret handling | Provides secret-sync and trust-material infrastructure | Declares which secrets their application needs |
| GitOps reconciliation | Provides the GitOps controller and its binding to the Git source | Defines application manifests that the controller reconciles |
| Cluster access | Owns cluster-level RBAC and policies | Owns application-level service accounts and access within their namespace |

## Practical boundary rules

- **Classification follows ownership and operational purpose, not technology type alone.** A database operated by the platform team for shared use is a platform service. A database bundled and operated by an application team for its own application is an application service.
- **If application developers need to understand it to ship their own code safely, it belongs in application scope.** If only the platform team needs to understand it to keep the cluster healthy, it belongs in platform scope.
- **Platform services serve applications or support other platform services.** A service that serves neither is not a platform service.
- **The handoff from bootstrap installation to GitOps-managed operation determines nothing about service classification.** After handoff, both platform services and application services are managed through GitOps unless a later decision documents a bootstrap-managed exception.
- **When in doubt, keep platform scope minimal.** Start with the smallest set of platform services needed to host applications reliably, and grow platform scope only when there is a clear operational reason.

## Examples with nuance

### Ingress controller (platform service)

An ingress controller is a platform service. The platform team selects, installs, and maintains the controller and its operational configuration. Application teams define routing rules for their own applications through the controller's documented interface.

### Application database (application service)

A database deployed and operated by an application team for its own workload is an application service. The application team owns the database version, configuration, and maintenance. The platform provides the cluster and ingress that make it reachable.

### Shared database (platform service)

The same database technology becomes a platform service when the platform team operates it as a shared capability for multiple application teams. Classification follows ownership and operational purpose, not the database engine.

### External-Secrets Operator (platform service)

External-Secrets Operator is a platform service. It provides secret-sync infrastructure that application services consume. The operator supplies the trust material for the backing secret store. Application teams declare which secrets their workloads need through the operator's documented interface.

### Application deployment manifests (application service definitions)

Application deployment manifests are definitions for application services, not services themselves. They describe the application workloads that run on the platform. Application developers own these definitions and the application code they reference. The GitOps controller reconciles them, but the controller is a platform concern.

## Kind-first local path

The kind-first local path is the first reference path for developing and validating this model as part of the point at a cluster and install experience. It is not the only future path. The model is designed to apply across cluster providers, but kind is the practical starting point.

## Relationship to other documents

- `architecture.md` defines the two-axis model and design posture.
- `bootstrap-installation-contract.md` defines the lifecycle handoff from bootstrap installation to GitOps-managed operation.
- `kind-local-workflow.md` defines the local reference workflow.
- `roadmap.md` shows the near-term order of work.

This document is a reference for later proposals that need a shared understanding of what platform services and application services mean in practice.
