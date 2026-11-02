# Production-only Harbor Tailnet access

The public mirror workflow joins the existing tailnet and uses Harbor's private
HTTPS hostname directly. `harbor-publish.sh <mirror-scope> --tailscale` neither
installs a kubeconfig nor calls Kubernetes, changes `/etc/hosts`, or starts a
port-forward. TLS verification, the registry 401 challenge, separate existing
publisher/pull robots, digest verification and complete pulls remain required.
Other publication workflows retain their existing transport. This change does
not migrate the other homelab access workflows or change routes, ACLs or RBAC.

The workflow is dispatch-only, restricted to exact reviewed `main` and the
`homelab-production` environment. Publishing this source does not enroll a node.
The credential-check step fails when the production key is absent; Tailnet
Lock rejects unsigned enrollment. Pipeline results determine readiness without
additional document-derived signing, installation, or dispatch approvals.

## Credential preview and installation

The production-only helper reuses an existing provider `apply` key and cached
Tailnet Lock wrapper. It has no signing, key creation, provider apply, node
registration, variable deletion, or authority removal operation. It never
publishes to plan or Cordium. Existing provider outputs and the private cache
bundle all three identities; only the production record is selected or used.
No private values are printed. Do not run the three-identity publisher for this
bounded recovery.

The production helper canonicalizes public authority names in memory: Tailscale
JSON uses `nlpub:<hex>`, while its CLI uses `tlpub:<hex>` for the same key bytes
([pinned implementation](https://github.com/tailscale/tailscale/blob/v1.102.3/types/key/nl.go)).
Duplicate aliases and malformed keys fail closed. This never changes cache files
or relaxes the provider fingerprint, wrapped key, generation or authority metadata
checks. Equal generation alone does not make a stale signed cache usable.

The helper reads the existing private production key/cache from clean signed
current `main`:

```sh
nix develop --command python3 -I scripts/harbor-tailscale-production.py
```

Preview reports only identity/tag, generation, existing public authority,
expiration and fixed secret destination. Missing/mismatched cache or trust
metadata stops; it never signs a replacement. The preview supplies the exact generation, authority and
expiration consumed by the installation helper.

The installation command binds those values:

```sh
nix develop --command python3 -I scripts/harbor-tailscale-production.py \
  --execute --generation <reviewed-generation> \
  --authority <reviewed-tlpub> --expires-at <reviewed-expiration>
```

Execution requires a clean checkout at GitHub's signed current `main`, the
`rstuhlmuller` account, protected main, the production branch/protection contract,
and an absent destination secret. The only write is
`Stuhlmuller/homelab` environment `homelab-production` secret
`TAILSCALE_AUTH_KEY`, passed over stdin. Metadata readback confirms presence;
it cannot prove the stored value or enrollment works. An uncertain write stops
without retrying. GitHub has no conditional secret-create operation: keep other
secret publishers stopped during this action. This helper refuses to replace
an existing secret.

## Identity, lifetime and authority

The existing identity is `apply`, tag `tag:homelab-ci-apply`. Current source grants
it TCP 443 to `tag:homelab-ingress` and `tag:k8s-operator`. Its Kubernetes binding
is cluster-admin; publishing this key therefore enables more authority than
Harbor alone, even though this mirror path never calls Kubernetes. No ACL or
RBAC expansion is proposed.

The provider key is reusable, ephemeral and preauthorized, with a 90-day maximum
lifetime. Preview requires 7-90 days remaining; it does not extend expiration.
Each job uses its own Tailnet Key Authority state directory, accepts tailnet
DNS, and declines subnet routes. The pinned Tailscale
Action logs out on cleanup; ephemeral nodes are removed. Existing AWS role and
Harbor robot credentials are retained.

Tailnet Lock remains enabled. The cached wrapper includes a delegated private
signing key. This proposal creates no new delegation and never exports the
Mac's voting key, but putting that wrapper in CI is persistent credential access.
Auth-key expiry or secret deletion does not remove the existing signing authority
or necessarily revoke already enrolled nodes. Key, node and authority revocation
are distinct operations; neither helper
removes shared authorities or re-signs other nodes.

[Tailscale's Action](https://github.com/tailscale/github-action#tailnet-lock)
requires a pre-signed key for unattended locked-tailnet enrollment. Signing each
runner node directly avoids a pre-auth-key delegation, but needs a secure per-run
request/signing path. No such service is implemented here, and none is installed
by this patch. Reusing the existing wrapper is the bounded supported path.

## Acceptance and rollback

The protected mirror runs at exact current `main`. Its steps check actual
Tailnet enrollment/cleanup, strict TLS, complete destination pulls and
platform/digest equality. Executable release checks own runtime readiness;
this runbook does not hold individual PRs or add manual acceptance gates.

Revert this source through protected PRs to stop future use; that does not revoke
a published key or enrolled nodes. Deleting the production secret prevents
future jobs from using it.
Preserve encrypted provider state and the private cache for recovery. Key or
signing-authority retirement remains a distinct operation. Do not restore
Octelium or broaden network access as an automatic fallback.

## Existing verification/access limits

The saved image-updater packet records a Kubernetes read to
`10.1.0.199:6443` rejected with network-sandbox operation-not-permitted. The saved
record does not establish an immutable firewall policy or preserve an approval
review rejection; do not reinterpret it as either. No retry through another
endpoint, proxy, SSH or Talos route is authorized by this source change.

No QNAP backup share was mounted on the operator Mac at inspection. Saved
October 25 initial-backup and isolated-restore receipts are historical;
October 26-27 nightly backups failed. Current source offers no independent
Mastodon backup-receipt workflow. Fresh verification comes from executable
backup/restore checks and their Job status, rather than a document-derived
operator attestation. Do not mount a new share or route the
denied Kubernetes read through another service to manufacture acceptance.
