.RECIPEPREFIX := >

SHELL := /bin/sh

KIND_CLUSTER_NAME ?= kind-dev-misc-local
KIND_CONTEXT = kind-$(KIND_CLUSTER_NAME)
HELM_CONTEXT_ARGS := --kube-context "$(KIND_CONTEXT)"
KIND_CONFIG := kind/config.yaml
KIND_UNIQUE_PREFIX ?= kubecrate-qa
KIND_UNIQUE_CLUSTER_NAME := $(KIND_UNIQUE_PREFIX)-$(shell date +%s)-$(shell LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 6)
KIND_UNIQUE_STATE_FILE ?= .tmp/kind-unique-cluster-name
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
FLUX_SYNC_VALUES := $(FLUX_PLATFORM_SERVICE_ROOT)/helm-values-sync.yaml

.PHONY: kind-dev-misc-local-await-gitops kind-dev-misc-local-bootstrap kind-dev-misc-local-check-prereqs kind-dev-misc-local-create kind-dev-misc-local-delete kind-dev-misc-local-evidence kind-dev-misc-local-recreate kind-unique-create kind-unique-current kind-unique-delete kind-unique-preflight kind-unique-smoke

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

kind-unique-preflight:
> python3 scripts/preflight-flux-deploy-key.py

kind-unique-create: kind-unique-preflight
kind-unique-create: KIND_CLUSTER_NAME := $(KIND_UNIQUE_CLUSTER_NAME)
kind-unique-create: kind-dev-misc-local-create
> mkdir -p "$$(dirname "$(KIND_UNIQUE_STATE_FILE)")"
> printf '%s\n' "$(KIND_CLUSTER_NAME)" >"$(KIND_UNIQUE_STATE_FILE)"
> printf 'cluster=%s\ncontext=kind-%s\n' "$(KIND_CLUSTER_NAME)" "$(KIND_CLUSTER_NAME)"

kind-unique-current:
> test -s "$(KIND_UNIQUE_STATE_FILE)" || { printf 'no kind unique cluster state found at %s\n' "$(KIND_UNIQUE_STATE_FILE)" >&2; exit 1; }
> sed -n '1p' "$(KIND_UNIQUE_STATE_FILE)"

kind-unique-delete:
> cluster=""; \
> if [ "$(origin KIND_CLUSTER_NAME)" = "command line" ] || [ "$(origin KIND_CLUSTER_NAME)" = "environment" ] || [ "$(origin KIND_CLUSTER_NAME)" = "environment override" ]; then cluster="$(KIND_CLUSTER_NAME)"; \
> elif [ -s "$(KIND_UNIQUE_STATE_FILE)" ]; then cluster="$$(sed -n '1p' "$(KIND_UNIQUE_STATE_FILE)")"; fi; \
> test -n "$${cluster}" || { printf 'KIND_CLUSTER_NAME is required or %s must contain a cluster name\n' "$(KIND_UNIQUE_STATE_FILE)" >&2; exit 1; }; \
> kind delete cluster --name "$${cluster}"; \
> if [ -s "$(KIND_UNIQUE_STATE_FILE)" ] && [ "$$(sed -n '1p' "$(KIND_UNIQUE_STATE_FILE)")" = "$${cluster}" ]; then rm -f "$(KIND_UNIQUE_STATE_FILE)"; fi

kind-unique-smoke: kind-dev-misc-local-check-prereqs
> cluster="$(KIND_UNIQUE_CLUSTER_NAME)"; \
> cleanup() { kind delete cluster --name "$${cluster}" >/dev/null 2>&1 || true; }; \
> trap cleanup EXIT INT TERM; \
> $(MAKE) kind-dev-misc-local-create KIND_CLUSTER_NAME="$${cluster}"; \
> kubectl --context "kind-$${cluster}" get nodes; \
> kubectl --context "kind-$${cluster}" wait --for=condition=Ready node --all --timeout=180s; \
> cleanup; \
> trap - EXIT INT TERM; \
> if kind get clusters | grep -Fx "$${cluster}" >/dev/null; then printf 'cluster cleanup failed: %s\n' "$${cluster}" >&2; exit 1; fi; \
> printf 'created and deleted disposable kind cluster: %s\n' "$${cluster}"

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
> expected_url="$$(python3 -c 'import re,sys; text=open(sys.argv[1]).read(); print(re.search(r"(?m)^    url: (\S+)", text).group(1))' "$(FLUX_SYNC_VALUES)")"; expected_branch="$$(python3 -c 'import re,sys; text=open(sys.argv[1]).read(); print(re.search(r"(?m)^      branch: (\S+)", text).group(1))' "$(FLUX_SYNC_VALUES)")"; live_url="$$(kubectl --context "$(KIND_CONTEXT)" get gitrepository "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" -o jsonpath='{.spec.url}' 2>/dev/null || true)"; live_branch="$$(kubectl --context "$(KIND_CONTEXT)" get gitrepository "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" -o jsonpath='{.spec.ref.branch}' 2>/dev/null || true)"; if [ "$${live_url}" != "$${expected_url}" ] || [ "$${live_branch}" != "$${expected_branch}" ]; then printf 'GitRepository/flux-system is not reconciling the reviewed implementation source.\nexpected url: %s\nlive url: %s\nexpected branch: %s\nlive branch: %s\n' "$${expected_url}" "$${live_url}" "$${expected_branch}" "$${live_branch}" >&2; exit 1; fi
> flux --context "$(KIND_CONTEXT)" reconcile source git "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> flux --context "$(KIND_CONTEXT)" reconcile kustomization "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready gitrepositories.source.toolkit.fluxcd.io/"$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready kustomizations.kustomize.toolkit.fluxcd.io/"$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" --timeout=180s
> for kustomization in external-secrets-operator external-secrets-operator-smoke cratecheck; do kubectl --context "$(KIND_CONTEXT)" get kustomizations.kustomize.toolkit.fluxcd.io/"$${kustomization}" -n "$(FLUX_NAMESPACE)" >/dev/null || { printf 'missing expected child Flux Kustomization: %s\n' "$${kustomization}" >&2; exit 1; }; done
> kubectl --context "$(KIND_CONTEXT)" get configmap "$(MARKER_NAME)" -n "$(MARKER_NAMESPACE)" -o jsonpath='{.data.version}' && printf '\n'

kind-dev-misc-local-evidence:
> kubectl --context "$(KIND_CONTEXT)" get nodes
> kubectl --context "$(KIND_CONTEXT)" get deployments -n "$(FLUX_NAMESPACE)"
> kubectl --context "$(KIND_CONTEXT)" get secret "$(FLUX_RELEASE_NAME)" -n "$(FLUX_NAMESPACE)" -o go-template='{{range $$k, $$_ := .data}}{{printf "%s\n" $$k}}{{end}}'
> flux --context "$(KIND_CONTEXT)" get sources git -n "$(FLUX_NAMESPACE)"
> flux --context "$(KIND_CONTEXT)" get kustomizations -n "$(FLUX_NAMESPACE)"
> kubectl --context "$(KIND_CONTEXT)" get configmap "$(MARKER_NAME)" -n "$(MARKER_NAMESPACE)" -o jsonpath='{.data.version}' && printf '\n'
