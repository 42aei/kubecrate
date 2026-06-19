.RECIPEPREFIX := >

SHELL := /bin/sh

KIND_CLUSTER_NAME := kind-dev-misc-local
KIND_CONTEXT := kind-$(KIND_CLUSTER_NAME)
KIND_CONFIG := kind/$(KIND_CLUSTER_NAME)/config.yaml
BOOTSTRAP_ROOT := clusters/$(KIND_CLUSTER_NAME)/bootstrap
PLATFORM_SERVICES_ROOT := clusters/$(KIND_CLUSTER_NAME)/platform-services
BOOTSTRAP_EXTERNAL_SECRETS_OPERATOR := $(PLATFORM_SERVICES_ROOT)/external-secrets-operator
EXTERNAL_SECRETS_OPERATOR_CHART_CACHE := platform-services/external-secrets-operator/base/charts
BOOTSTRAP_STAGE_TWO := $(BOOTSTRAP_ROOT)/stage-2
ENTRYPOINT_ROOT := clusters/$(KIND_CLUSTER_NAME)/entrypoint
FLUX_INSTALL_ROOT := $(ENTRYPOINT_ROOT)/flux-system/install
BOOTSTRAP_LOADER_ROOT := $(ENTRYPOINT_ROOT)/bootstrap-loader
FLUX_SYNC_ROOT := $(ENTRYPOINT_ROOT)/flux-system/sync
SEED_SECRET_NAMESPACE := core-external-secrets-operator
MARKER_NAMESPACE := kubecrate-system

.PHONY: kind-dev-misc-local-bootstrap kind-dev-misc-local-check-prereqs kind-dev-misc-local-create kind-dev-misc-local-delete kind-dev-misc-local-evidence kind-dev-misc-local-recreate

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
> rm -rf "$(EXTERNAL_SECRETS_OPERATOR_CHART_CACHE)"
> kubectl kustomize --enable-helm "$(BOOTSTRAP_EXTERNAL_SECRETS_OPERATOR)" | kubectl --context "$(KIND_CONTEXT)" apply --server-side -f -
> kubectl --context "$(KIND_CONTEXT)" wait --for=condition=Available deployment/external-secrets -n "$(SEED_SECRET_NAMESPACE)" --timeout=180s
> python3 -c 'exec("import base64, sys\nrequired = (\"SEED_FLUX_GIT_USERNAME\", \"SEED_FLUX_GIT_PAT\")\ndata = {}\nfor raw in sys.stdin:\n    line = raw.strip()\n    if not line or line.startswith(\"#\") or \"=\" not in line:\n        continue\n    key, value = line.split(\"=\", 1)\n    key = key.strip()\n    if key in required:\n        data[key] = value.strip()\nmissing = [key for key in required if not data.get(key)]\nif missing:\n    sys.stderr.write(\"missing required seed key(s): \" + \", \".join(missing) + \"\\n\")\n    sys.exit(1)\nsys.stdout.write(\"apiVersion: v1\\nkind: Secret\\nmetadata:\\n  name: seed-secrets\\n  namespace: $(SEED_SECRET_NAMESPACE)\\ntype: Opaque\\ndata:\\n\")\nfor key in required:\n    encoded = base64.b64encode(data[key].encode()).decode()\n    sys.stdout.write(\"  \" + key + \": \" + encoded + \"\\n\")\n")' < .env | kubectl --context "$(KIND_CONTEXT)" apply --server-side -f -
> kubectl --context "$(KIND_CONTEXT)" patch secret/seed-secrets -n "$(SEED_SECRET_NAMESPACE)" --type=merge -p '{"metadata":{"annotations":{"kubectl.kubernetes.io/last-applied-configuration":null}}}'
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
> kubectl --context "$(KIND_CONTEXT)" get deployments -n "$(SEED_SECRET_NAMESPACE)"
> kubectl --context "$(KIND_CONTEXT)" get secret seed-secrets -n "$(SEED_SECRET_NAMESPACE)"
> kubectl --context "$(KIND_CONTEXT)" get clustersecretstore seed-secrets-store
> kubectl --context "$(KIND_CONTEXT)" get externalsecret flux-system -n flux-system
> flux --context "$(KIND_CONTEXT)" get all -A
> kubectl --context "$(KIND_CONTEXT)" get configmap kubecrate-reconciliation-marker -n "$(MARKER_NAMESPACE)" -o jsonpath='{.data.version}' && printf '\n'
