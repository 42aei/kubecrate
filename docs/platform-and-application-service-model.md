# Platform and application service model

This document defines the working model for platform services and application services. It is a practical owner's guide, not a taxonomy exercise.

## Workload category focus

This document defines only the workload-category boundary between platform services and application services. For the broader architecture model, see `architecture.md`.

## Overview

The two workload categories define a provider-consumer relationship. Platform services provide shared capabilities that make the cluster usable. Application services consume those capabilities to run user and company workloads. The sections below define each category and the boundary between them.

## Platform services

A platform service is a shared capability maintained as part of the platform. It helps ensure applications are hosted and served reliably and can be deployed and managed easily by developers without deep knowledge of the platform.

Platform services may require deeper insight into Kubernetes and platform internals than application services. Common examples include ingress controllers, certificate management, secret-handling components, observability building blocks, and reconciliation controllers.

Platform services are operator-owned. The operator or platform team selects, installs, and maintains them based on the needs of the applications they host. Application developers should not need to configure, troubleshoot, or reason about platform service internals beyond their documented interfaces.

## Application services

Application services are the user or company workloads that consume the platform. They are the workloads people want to run once the shared platform capabilities exist.

Application services are developer-owned. Application developers are expected to understand what is within application service scope — their own application code, configuration, and deployment concerns — not deep platform internals.

## Ownership and scope boundaries

The table below maps common concerns to platform and application scope.

| Concern | Platform scope | Application scope |
| --- | --- | --- |
| Ingress routing rules | Defines the ingress controller and its operational configuration | Defines per-application routing rules (hosts, paths) |
| Certificate provisioning | Provides certificate management infrastructure | Requests certificates for application domains |
| Observability | Provides collection, storage, and dashboards | Emits metrics, logs, and traces in the expected format |
| Secret handling | Provides secret-sync and trust-material infrastructure | Declares which secrets their application needs |
| Deployment reconciliation | Provides the reconciliation controller and its binding to the source of truth | Defines application manifests that the controller reconciles |
| Cluster access | Owns cluster-level RBAC and policies | Owns application-level service accounts and access within their namespace |

## Practical boundary rules

- **Classification follows ownership and operational purpose, not technology type alone.** A database operator deployed by the platform team for shared provisioning is a platform service. A database instance created and operated by an application team for its own application is an application service.
- **If application developers need to understand it to ship their own code safely, it belongs in application scope.** If only the platform team needs to understand it to keep the cluster healthy, it belongs in platform scope.
- **Platform services serve applications or support other platform services.** A service that serves neither is not a platform service.
- **Service classification is independent of lifecycle phase.** A service remains platform or application scope whether it is introduced during bootstrap installation or later reconciled through GitOps-managed operation.
- **When in doubt, keep platform scope minimal.** Start with the smallest set of platform services needed to host applications reliably, and grow platform scope only when there is a clear operational reason.

## Examples with nuance

### Ingress controller (platform service)

An ingress controller is a platform service. The platform team selects, installs, and maintains the controller and its operational configuration. Application teams define routing rules for their own applications through the controller's documented interface.

### Database operator (platform service)

A database operator or provisioner (e.g., CloudNativePG) that the platform team deploys and maintains is a platform service. The platform owns the operator and its operational configuration. Application teams provision database instances through the operator's documented interface without needing to understand operator internals.

### Database instance (application service)

A database instance declared by an application team through the platform's database provisioning capability is an application service. The application team owns the instance claim or custom resource, the requested settings (such as resource sizes, connection details, and version preferences), and the database configuration within the constraints enforced by the platform. The platform team owns the operator, the provisioning mechanics, and the guardrails that the operator enforces.

### External-Secrets Operator (platform service)

External-Secrets Operator is a platform service. It provides secret-sync infrastructure that application services consume. The operator supplies the trust material for the backing secret store. Application teams declare which secrets their workloads need through the operator's documented interface.

## Relationship to other documents

- `architecture.md` defines the two-axis model and design posture.
- `kind-local-workflow.md` defines the local reference workflow.
- `roadmap.md` shows the near-term order of work.

This document is a reference for later proposals that need a shared understanding of what platform services and application services mean in practice.
