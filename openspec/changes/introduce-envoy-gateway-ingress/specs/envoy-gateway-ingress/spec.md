## ADDED Requirements

### Requirement: Envoy Gateway installed as a GitOps-managed platform service
Kubecrate SHALL install Envoy Gateway as a platform service on the kind-first local path using a Flux HelmRelease. Envoy Gateway SHALL use the `core-envoy-gateway` namespace following the `core-<service-name>` pattern. The HelmRelease SHALL reference chart `gateway-helm` version `v1.4.2` from the Envoy Proxy OCI Helm repository.

#### Scenario: Envoy Gateway HelmRelease reconciles successfully
- **WHEN** Flux reconciles the `envoy-gateway` Kustomization in the cluster entrypoint
- **THEN** the Envoy Gateway HelmRelease is installed in namespace `core-envoy-gateway`
- **AND** the HelmRelease reports Ready condition

#### Scenario: Envoy Gateway follows the platform service layout
- **WHEN** Envoy Gateway runtime manifests are inspected
- **THEN** reusable base manifests live under `platform-services/envoy-gateway/base/`
- **AND** cluster binding lives under `clusters/kind-dev-misc-local/platform-services/envoy-gateway/`

### Requirement: Envoy proxy exposed as NodePort for kind ingress
Kubecrate SHALL configure the managed Envoy proxy Service as NodePort via an `EnvoyProxy` resource so HTTP ingress traffic reaches the kind cluster through the port mapping defined in `kind/config.yaml` (host 10080 → container 30080).

#### Scenario: EnvoyProxy resource configures NodePort service type
- **WHEN** the EnvoyProxy resource is created in namespace `core-envoy-gateway`
- **THEN** `spec.provider.kubernetes.envoyService.type` is `NodePort`
- **AND** the GatewayClass references the EnvoyProxy via `parametersRef`

#### Scenario: Gateway listener port is exposed via NodePort
- **WHEN** the smoke Gateway has an HTTP listener on port 80
- **THEN** the Envoy proxy Service maps that listener to a Kubernetes NodePort
- **AND** the operator can verify the NodePort assignment and reconcile it with the kind config port mapping

### Requirement: Smoke Gateway API resources route traffic to CrateCheck
Kubecrate SHALL define Gateway API resources that route HTTP traffic to the CrateCheck application service. The smoke resources SHALL be reconciled by a dedicated Flux Kustomization that depends on the Envoy Gateway platform service Kustomization.

#### Scenario: GatewayClass references the Envoy Gateway controller
- **WHEN** the GatewayClass `kubecrate-envoy-gateway` is created
- **THEN** it specifies `controllerName: gateway.envoyproxy.io/gatewayclass-controller`
- **AND** it references the EnvoyProxy via `parametersRef`

#### Scenario: Gateway accepts HTTP routes
- **WHEN** the Gateway `kubecrate-envoy-smoke` is created in namespace `core-envoy-gateway`
- **THEN** it has an HTTP listener on port 80
- **AND** it accepts routes from all namespaces

#### Scenario: HTTPRoute forwards traffic to CrateCheck
- **WHEN** the HTTPRoute `envoy-smoke-cratecheck` is created in namespace `cratecheck`
- **THEN** it has a parentRef to Gateway `kubecrate-envoy-smoke` in namespace `core-envoy-gateway`
- **AND** backendRefs point to Service `cratecheck` on port 8080

### Requirement: CrateCheck validates the Envoy Gateway ingress pipeline
Kubecrate SHALL add CrateCheck status checks that validate the Envoy Gateway ingress pipeline end-to-end. The checks SHALL cover HelmRelease readiness, GatewayClass acceptance, Gateway programming, and HTTPRoute acceptance with backend reference resolution.

#### Scenario: Envoy Gateway HelmRelease is monitored
- **WHEN** CrateCheck evaluates `envoy-helmrelease-ready`
- **THEN** it checks the Envoy Gateway HelmRelease Ready condition in namespace `core-envoy-gateway`
- **AND** reports green when the HelmRelease is Ready

#### Scenario: GatewayClass acceptance is monitored
- **WHEN** CrateCheck evaluates `envoy-gatewayclass-accepted`
- **THEN** it checks the GatewayClass `kubecrate-envoy-gateway` Accepted condition
- **AND** reports green when Accepted is True

#### Scenario: Gateway programming is monitored
- **WHEN** CrateCheck evaluates `envoy-gateway-ready`
- **THEN** it checks the Gateway `kubecrate-envoy-smoke` Programmed condition in namespace `core-envoy-gateway`
- **AND** reports green when Programmed is True

#### Scenario: HTTPRoute acceptance and backend resolution are both required
- **WHEN** CrateCheck evaluates `envoy-httproute-ready`
- **THEN** it checks the HTTPRoute `envoy-smoke-cratecheck` parent status in namespace `cratecheck`
- **AND** it requires both `Accepted=True` and `ResolvedRefs=True` on the matching parent
- **AND** reports green only when both conditions are True

#### Scenario: Controlled red test is detectable
- **WHEN** the HTTPRoute backend port is changed to a non-existent port (9999)
- **THEN** the `envoy-httproute-ready` check SHALL report non-green because `ResolvedRefs` is no longer True
- **AND** restoring the correct backend port SHALL return the check to green

### Requirement: Validation runbook provides end-to-end ingress validation
Kubecrate SHALL provide a validation runbook at `docs/kind-envoy-gateway-ingress-runbook.md` that documents end-to-end ingress validation for the kind-first local path. The runbook SHALL include host-side HTTP requests through the ingress path, direct CrateCheck status inspection, and a controlled red test with restore instructions.

#### Scenario: Runbook documents host-side ingress request
- **WHEN** the operator follows the runbook
- **THEN** curl through `127.0.0.1:10080` reaches CrateCheck `/status.json` through the Envoy Gateway ingress path
- **AND** the runbook documents the exact curl command and expected output

#### Scenario: Runbook documents controlled red test
- **WHEN** the operator follows the controlled red test steps
- **THEN** the runbook provides commands for green → controlled red → restore green
- **AND** the expected CrateCheck check behavior is documented for each phase

### Requirement: QA branch override for disposable Flux clusters
Kubecrate SHALL document a mechanism for overriding the Flux sync branch when using a disposable QA cluster, without hardcoding a PR branch into committed configuration.

#### Scenario: Operator can override the Flux sync branch
- **WHEN** the operator needs to test a PR branch with a disposable Flux cluster
- **THEN** the operator can override the sync branch at bootstrap time
- **AND** the committed `helm-values-sync.yaml` remains unchanged as the canonical branch reference

### Requirement: No dependency on obsolete kubecrate-status
Kubecrate SHALL use CrateCheck as the validation application service for this slice. No artifact in this slice SHALL depend on or reference the obsolete `kubecrate-status` application.

#### Scenario: All validation references use CrateCheck
- **WHEN** any artifact in this slice references the validation application service
- **THEN** it uses CrateCheck, not kubecrate-status
- **AND** CrateCheck status JSON and CrateCheck check names are used in validation commands and documentation
