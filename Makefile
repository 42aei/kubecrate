.RECIPEPREFIX := >

SHELL := /bin/sh

KIND_CLUSTER_NAME := kind-dev-misc-local
KIND_CONTEXT := kind-$(KIND_CLUSTER_NAME)
HELM_CONTEXT_ARGS := --kube-context "$(KIND_CONTEXT)"
KIND_CONFIG := kind/$(KIND_CLUSTER_NAME)/config.yaml
ENTRYPOINT_ROOT := clusters/$(KIND_CLUSTER_NAME)/entrypoint
FLUX_PLATFORM_SERVICE_ROOT := clusters/$(KIND_CLUSTER_NAME)/platform-services/flux
FLUX_HELM_VALUES := $(FLUX_PLATFORM_SERVICE_ROOT)/helm-values.yaml
FLUX_RELEASE_NAME := flux-system
FLUX_SYNC_HELMRELEASE_NAME := flux-system-sync
FLUX_NAMESPACE := flux-system
FLUX_CHART := oci://ghcr.io/fluxcd-community/charts/flux2
FLUX_CHART_VERSION := 2.18.4
MARKER_NAMESPACE := kubecrate-system
MARKER_NAME := kubecrate-reconciliation-marker

.PHONY: kind-dev-misc-local-await-gitops kind-dev-misc-local-bootstrap kind-dev-misc-local-check-prereqs kind-dev-misc-local-create kind-dev-misc-local-delete kind-dev-misc-local-evidence kind-dev-misc-local-recreate

kind-dev-misc-local-check-prereqs:
> for cmd in kind kubectl kustomize helm flux docker make python3; do command -v "$${cmd}" >/dev/null 2>&1 || { printf 'missing required command: %s\n' "$${cmd}" >&2; exit 1; }; done
> kind version
> kubectl version --client=true
> kustomize version
> helm version --short
> flux version --client
> docker version --format '{{.Server.Version}}'
> python3 --version

kind-dev-misc-local-create: kind-dev-misc-local-check-prereqs
> kind create cluster --name "$(KIND_CLUSTER_NAME)" --config "$(KIND_CONFIG)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready node --all --timeout=180s

kind-dev-misc-local-delete:
> kind delete cluster --name "$(KIND_CLUSTER_NAME)"

kind-dev-misc-local-recreate:
> $(MAKE) kind-dev-misc-local-delete
> $(MAKE) kind-dev-misc-local-create

kind-dev-misc-local-bootstrap:
> helm upgrade --install "$(FLUX_RELEASE_NAME)" "$(FLUX_CHART)" $(HELM_CONTEXT_ARGS) --version "$(FLUX_CHART_VERSION)" --namespace "$(FLUX_NAMESPACE)" --create-namespace -f "$(FLUX_HELM_VALUES)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/source-controller -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/kustomize-controller -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/helm-controller -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" apply -k "$(ENTRYPOINT_ROOT)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready helmreleases.helm.toolkit.fluxcd.io/"$(FLUX_SYNC_HELMRELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> printf 'Register this deploy key with the Git provider before waiting for GitOps-managed operation readiness:\n'
> kubectl --context "$(KIND_CONTEXT)" get secret "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" -o jsonpath='{.data.identity\.pub}' | base64 -d && printf '\n'
> printf 'After deploy-key registration, run: make kind-dev-misc-local-await-gitops\n'

kind-dev-misc-local-await-gitops:
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/source-controller -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/kustomize-controller -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/helm-controller -n "$(FLUX_NAMESPACE)" --timeout=180s
> flux --context "$(KIND_CONTEXT)" reconcile source git "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> flux --context "$(KIND_CONTEXT)" reconcile kustomization "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready gitrepositories.source.toolkit.fluxcd.io/"$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready kustomizations.kustomize.toolkit.fluxcd.io/"$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" get configmap "$(MARKER_NAME)" -n "$(MARKER_NAMESPACE)" -o jsonpath='{.data.version}' && printf '\n'

kind-dev-misc-local-evidence:
> kubectl --context "$(KIND_CONTEXT)" get nodes
> kubectl --context "$(KIND_CONTEXT)" get deployments -n "$(FLUX_NAMESPACE)"
> kubectl --context "$(KIND_CONTEXT)" get secret "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" -o go-template='{{range $k, $_ := .data}}{{printf "%s\n" $k}}{{end}}'
> flux --context "$(KIND_CONTEXT)" get sources git -n "$(FLUX_NAMESPACE)"
> flux --context "$(KIND_CONTEXT)" get kustomizations -n "$(FLUX_NAMESPACE)"
> kubectl --context "$(KIND_CONTEXT)" get configmap "$(MARKER_NAME)" -n "$(MARKER_NAMESPACE)" -o jsonpath='{.data.version}' && printf '\n'
