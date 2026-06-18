.RECIPEPREFIX := >

SHELL := /bin/sh

KIND_CLUSTER_NAME := kind-dev-misc-local
KIND_CONTEXT := kind-$(KIND_CLUSTER_NAME)
KIND_CONFIG := kind/$(KIND_CLUSTER_NAME)/config.yaml
BOOTSTRAP_ROOT := clusters/$(KIND_CLUSTER_NAME)/bootstrap
BOOTSTRAP_ESO_INSTALL := $(BOOTSTRAP_ROOT)/eso-install
BOOTSTRAP_STAGE_TWO := $(BOOTSTRAP_ROOT)/stage-2
ENTRYPOINT_ROOT := clusters/$(KIND_CLUSTER_NAME)/entrypoint
FLUX_INSTALL_ROOT := $(ENTRYPOINT_ROOT)/flux-system/install
BOOTSTRAP_LOADER_ROOT := $(ENTRYPOINT_ROOT)/bootstrap-loader
FLUX_SYNC_ROOT := $(ENTRYPOINT_ROOT)/flux-system/sync
SEED_SECRET_NAMESPACE := eso
MARKER_NAMESPACE := kubecrate-system

.PHONY: kind-dev-misc-local-bootstrap kind-dev-misc-local-check-prereqs kind-dev-misc-local-create kind-dev-misc-local-delete kind-dev-misc-local-evidence kind-dev-misc-local-recreate

kind-dev-misc-local-check-prereqs:
> for cmd in kind kubectl kustomize flux docker make; do command -v "$${cmd}" >/dev/null 2>&1 || { printf 'missing required command: %s\n' "$${cmd}" >&2; exit 1; }; done
> kind version
> kubectl version --client=true
> kustomize version
> flux version --client
> docker version --format '{{.Server.Version}}'

kind-dev-misc-local-create: kind-dev-misc-local-check-prereqs
> kind create cluster --name "$(KIND_CLUSTER_NAME)" --config "$(KIND_CONFIG)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready node --all --timeout=180s

kind-dev-misc-local-delete:
> kind delete cluster --name "$(KIND_CLUSTER_NAME)"

kind-dev-misc-local-recreate:
> $(MAKE) kind-dev-misc-local-delete
> $(MAKE) kind-dev-misc-local-create

kind-dev-misc-local-bootstrap:
> kubectl --context "$(KIND_CONTEXT)" apply --server-side -k "$(BOOTSTRAP_ESO_INSTALL)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/external-secrets -n "$(SEED_SECRET_NAMESPACE)" --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" create secret generic seed-secrets -n "$(SEED_SECRET_NAMESPACE)" --from-env-file=.env --dry-run=client -o yaml | kubectl --context "$(KIND_CONTEXT)" apply -f -
> kubectl --context "$(KIND_CONTEXT)" apply -k "$(BOOTSTRAP_STAGE_TWO)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready clustersecretstores.external-secrets.io/seed-secrets-store --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" apply -k "$(FLUX_INSTALL_ROOT)"
> kubectl --context "$(KIND_CONTEXT)" apply -k "$(BOOTSTRAP_LOADER_ROOT)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready externalsecrets.external-secrets.io/flux-system -n flux-system --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/source-controller -n flux-system --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/kustomize-controller -n flux-system --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" apply -k "$(FLUX_SYNC_ROOT)"
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready gitrepositories.source.toolkit.fluxcd.io/flux-system -n flux-system --timeout=180s
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Ready kustomizations.kustomize.toolkit.fluxcd.io/flux-system -n flux-system --timeout=180s

kind-dev-misc-local-evidence:
> kubectl --context "$(KIND_CONTEXT)" get nodes
> kubectl --context "$(KIND_CONTEXT)" get deployments -n eso
> kubectl --context "$(KIND_CONTEXT)" get secret seed-secrets -n eso
> kubectl --context "$(KIND_CONTEXT)" get clustersecretstore seed-secrets-store
> kubectl --context "$(KIND_CONTEXT)" get externalsecret flux-system -n flux-system
> flux --context "$(KIND_CONTEXT)" get all -A
> kubectl --context "$(KIND_CONTEXT)" get configmap kubecrate-reconciliation-marker -n "$(MARKER_NAMESPACE)" -o jsonpath='{.data.version}' && printf '\n'
