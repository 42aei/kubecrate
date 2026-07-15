# Flux deploy-key operator guide

This document covers durable operator knowledge for the Flux `flux2-sync` SSH deploy-key flow used in Kubecrate bootstrap installation and disposable-cluster QA. It complements the design docs in `openspec/changes/create-first-installable-slice/` with field-level diagnosis and GitHub-side troubleshooting.

## Deploy-key contract (summary)

- The `flux2-sync` chart release `flux-system-sync` creates `Secret/flux-system-sync` with an SSH key pair and reconciles `GitRepository/flux-system-sync` and `Kustomization/flux-system-sync`.
- Kubecrate explicitly configures chart version `1.14.6` to generate an Ed25519 key; do not rely on the chart's ECDSA default.
- The operator retrieves the generated public key from `identity.pub` and registers it with the Git provider as a **read-only** deploy key.
- The generated private key stays in-cluster and must not be committed, printed, or copied.

For the full contract, see `docs/bootstrap-installation-contract.md`.

## GitHub org-level prerequisite

The GitHub organization that owns the repository must allow deploy keys under **Member privileges**.

### Settings location

`https://github.com/organizations/<org>/settings/member_privileges`

For the 42aei organization (the Kubecrate reference org):

`https://github.com/organizations/42aei/settings/member_privileges`

Under that page, the section **Repository deploy keys** must allow members to create deploy keys. If the organization setting disallows deploy keys, every `POST /repos/:owner/:repo/keys` call returns HTTP 422, regardless of the caller's admin permissions.

### Verifying the setting outside the browser

There is no public REST endpoint that exposes the org-level deploy-key policy directly. The GraphQL API exposes `organization.repositoryDeployKeyCreationSetting` but may require org-level scopes. The practical verification is:

1. Navigate to the Member privileges settings page.
2. Confirm that the **Deploy keys** option is enabled (not disabled/unchecked).

Alternatively, run the preflight at `scripts/preflight-flux-deploy-key.py`. It generates a valid temporary Ed25519 key, creates it read-only, reads it back and validates its identity and boolean metadata, deletes only the captured ID, and verifies absence. Every unknown status, malformed body, schema mismatch, or cleanup failure blocks cluster creation. Private key material is confined to an automatically removed temporary directory.

## Disabled existing keys

### How keys become disabled

When an organization changes its deploy-key policy from *allow* to *disallow*, GitHub does not delete existing deploy keys — it sets `enabled: false` on each key. Flux will then fail to connect because the private key in `Secret/flux-system-sync` no longer matches an *enabled* public key registered on the repository.

### Symptom in Flux

```
GitRepository/flux-system-sync: failed to checkout and determine revision:
unable to clone 'ssh://git@github.com/...': ...
```

The `flux get source git flux-system-sync` command will show the GitRepository as not ready with an authentication or clone error.

### Diagnosis checklist

1. List deploy keys on the repository:
   ```sh
   gh api repos/<org>/<repo>/keys --jq '.[] | {id, title, enabled, read_only}'
   ```

2. Look for keys where `enabled` is `false`.

3. If every key shows `enabled: false`, the org-level deploy-key policy is the root cause. Enable deploy keys in org Member privileges, then re-enable the needed deploy key.

4. If only a specific key is disabled, re-enable it:
   - Navigate to `https://github.com/<org>/<repo>/settings/keys`
   - Find the key and toggle it back on via the UI
   - Alternatively, delete the disabled key and re-register it: the public key
     is still available in the cluster (`kubectl -n flux-system get secret flux-system-sync
     -o jsonpath='{.data.identity\.pub}' | base64 -d`)

### Re-enabling after org policy change

After the org policy is restored (deploy keys allowed):

1. Re-enable existing keys via the repository settings page (navigate to
   `https://github.com/<org>/<repo>/settings/keys` and toggle each key back on),
   or delete and re-register them using the public key still available in the
   cluster.
2. Force a Flux reconciliation:
   ```sh
   flux reconcile source git flux-system-sync -n flux-system
   ```

New keys registered after the policy is enabled will have `enabled: true` by default.

## HTTP 422 diagnosis

When `flux bootstrap` or any API call attempts to register a deploy key on a repository in an org that disallows deploy keys, GitHub returns:

```
HTTP 422 Unprocessable Entity
```

The response body typically includes a message like:

> Deploy keys are not supported for this organization. To enable deploy keys, an organization owner must enable them in the organization's member privileges.

Root cause: the org-level deploy-key policy is set to disallow members from creating deploy keys.

Resolution path:
1. An organization owner enables deploy keys under Member privileges.
2. After the policy change, re-register any deploy keys that were rejected.

## Read-only key registration

Kubecrate always registers Flux deploy keys as **read-only**. This is the correct posture because:

- Flux only needs to pull the Git source; it never pushes.
- A read-only key limits blast radius if the private key is ever exposed.
- The GitHub UI and API both default to read-only for deploy keys.

### Registration command examples

After retrieving the public key from `Secret/flux-system-sync`:

```sh
# Retrieve the public key (safe to display)
PUBKEY=$(kubectl -n flux-system get secret flux-system-sync -o jsonpath='{.data.identity\.pub}' | base64 -d)

# Register via gh CLI (read-only is the default)
gh api repos/42aei/kubecrate/keys \
  -f title="kubecrate-qa-$(date +%s)" \
  -f key="$PUBKEY" \
  -f read_only=true
```

The title convention `kubecrate-qa-<timestamp>` identifies disposable QA cluster keys and makes cleanup tractable.

### Lifecycle for disposable QA clusters

For each disposable kind cluster created by a QA or validation run:

1. **Before cluster creation**: run the preflight to confirm deploy keys are allowed and no existing keys are disabled.
2. **Cluster creation**: bootstrap Flux; retrieve the generated public key.
3. **Registration**: register the public key as a read-only deploy key with a `kubecrate-qa-*` title.
4. **Validation**: run the GitOps-managed operation validation.
5. **Cleanup**: after validation, remove and verify absence of the exact captured deploy key, QA branch, disposable cluster, and active deploy-key ownership/uncertainty markers. The helper atomically renames authenticated deploy-key markers to unpredictable `.retired-deploy-key-*` names and retains them as non-active, non-secret audit evidence (repository, title, fingerprint, state, and key ID only). Retired entries remain mode `0600` under the mode `0700` evidence directory and are not pathname-unlinked. Open marker and directory descriptors remain held through deploy-key cleanup, and the active plus retired evidence is fully re-authenticated immediately before each GitHub request (including every list page). These are fail-closed, point-in-time boundary checks, not continuous tamper protection; the private mode `0700` evidence directory remains part of the safety contract.

For final QA, use the executable safeguarded workflow in [Exact-tree final QA](final-qa-exact-tree.md). It publishes and verifies the immutable candidate tree, selects the unique branch through a runtime-only manifest artifact, performs browser plus `/status.json` green → controlled ESO red → restored green evidence, and guarantees verified trap cleanup.

## Cleanup

Deploy keys linger after their associated clusters are deleted. Accumulated stale keys cause confusion and may exhaust the per-repository deploy key limit for smaller plans.

### Listing QA keys

```sh
gh api repos/42aei/kubecrate/keys --jq '.[] | select(.title | startswith("kubecrate-qa-")) | {id, title, created_at}'
```

### Removing a key

```sh
gh api repos/42aei/kubecrate/keys/<KEY_ID> -X DELETE
```

### Full cleanup of stale QA keys

A safe cleanup that only removes keys whose associated kind cluster no longer exists:

```sh
# List QA-titled deploy keys
gh api repos/42aei/kubecrate/keys --jq '.[] | select(.title | startswith("kubecrate-qa-")) | {id, title}' \
  | while read -r line; do
      # Manual review step: confirm the cluster is gone, then delete
      # gh api repos/42aei/kubecrate/keys/<id> -X DELETE
    done
```

Automated cleanup is deferred. Manual cleanup after each disposable QA run is the current expectation.

## FAQ

### Q: Why does `git clone` work but Flux does not?

`git clone` may use a personal SSH key or HTTPS credential that is not affected by the deploy-key policy. Flux uses the specific deploy key registered on the repository, which is subject to the org policy.

### Q: My key was working yesterday but stopped today. What changed?

The most common causes:
1. The org deploy-key policy was changed to disallow keys (all existing keys become `enabled: false`).
2. A specific key was manually disabled in the repository settings.
3. The key's read-only scope changed (unlikely, but correlated with policy changes).

Check `enabled` status on all deploy keys first.

### Q: Can I skip the deploy-key flow for local kind clusters?

The Kubecrate design intentionally validates the real GitOps-managed operation contract, including SSH deploy-key registration, even for local kind clusters. This keeps the local validation path honest about what production clusters will require.

### Q: What is the per-repository deploy key limit?

GitHub allows up to 20 deploy keys per repository. Accumulated stale QA keys should be cleaned up periodically.
