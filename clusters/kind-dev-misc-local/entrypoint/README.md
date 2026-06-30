# kind-dev-misc-local entrypoint

This directory is the first GitOps reconciliation root for the kind-first local path.

- It is cluster-owned validation material for `kind-dev-misc-local`.
- `kubecrate-reconciliation-marker` is a validation marker/config proof.
- The marker is **not** a platform service or an application service.
- Bootstrap installation applies this same path before Flux hands off to GitOps-managed operation.
