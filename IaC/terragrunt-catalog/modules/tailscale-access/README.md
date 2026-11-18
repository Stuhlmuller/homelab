# Tailscale access ownership

The `operator/tailscale-access` Terragrunt unit owns the complete tailnet policy,
DNS configuration, tailnet settings, contact addresses, and three scoped CI auth
keys through `tailscale/tailscale` 0.29.2.
Ordinary CI never applies this unit or receives policy administration scopes.
State and saved plans use the existing encrypted homelab S3 backend.

The provider reads a separate administrator OAuth client from private
`~/.config/homelab/tailscale/terragrunt-oauth-client-{id,secret}` files. Keep the
directory `0700` and both files `0600`; never commit or print either value.
The Kubernetes operator's SSM-backed OAuth client remains separate. The
Terragrunt client needs read access plus write scopes for each managed surface:
`dns`, `feature_settings`, `account_settings`, `policy_file`, `auth_keys`, and
`federated_keys` when those resources need updating. Do not broaden the
Kubernetes operator credential to administer the tailnet.

The imported DNS configuration preserves MagicDNS, two global resolvers with
local-DNS override off, and the `stinkyboi.com` split DNS resolver. The split
resolver stays active when a client selects an exit node; otherwise the exit
node's resolver cannot find private app names. The fixed split DNS IP must match
the `homelab-dns` Tailscale Service before any update.
The imported tailnet settings preserve existing approval, key-duration, HTTPS,
auto-update, logging, posture, and routing flags. Provider 0.29.2 does not
expose the live `routeSelection` setting; keep that gap visible when reviewing
tailnet-wide drift. Configuration and network log streaming are unavailable on
the current Tailscale billing plan.
The six Kubernetes proxy devices are owned by the Tailscale operator's reviewed
Helm values, Connector, Service, Ingress, and policy declarations. Their current
hostnames, tags, authorization, key-expiry behavior, and exit-node routes were
checked against those sources. Do not pin controller-generated device IDs in this
module. Personal and non-Kubernetes devices remain outside repository ownership.

The complete policy in `scripts/config/tailscale-policy.json` preserves the
reviewed October 10, 2026 baseline. The former wildcard grant now names existing
human members and legacy tags explicitly, so newly introduced CI tags receive
only their declared grants. Legacy route/exit-node approvals, SSH checks, and
the standalone Funnel IP are retained. The broad `tag:k8s` Funnel permission is
replaced by `tag:homelab-funnel`.

The provider replaces the entire policy. Re-read and compare live policy before
initial adoption, preserving any intervening unrelated changes. Its embedded
positive and negative tests check the CI boundaries. An unknown-policy bootstrap
marker is rejected by the module.

Generate the root stack, initialize the operator unit, and import existing
singletons only when their addresses are absent from state:

```sh
umask 077
review_dir="$(mktemp -d /private/tmp/homelab-tailscale-review.XXXXXX)"
cd IaC
terragrunt stack generate
cd homelab/us-west-2/operator/tailscale-access
terragrunt init
terragrunt state list >"$review_dir/state-list.txt"
for entry in \
  'tailscale_acl.homelab acl' \
  'tailscale_dns_configuration.homelab dns_configuration' \
  'tailscale_tailnet_settings.homelab tailnet_settings' \
  'tailscale_contacts.homelab contacts'; do
  address=${entry% *}
  if ! grep -Fxq "$address" "$review_dir/state-list.txt"; then
    terragrunt import "$address" "${entry#* }"
  fi
done
terragrunt plan -out="$review_dir/access.tfplan"
terragrunt show -no-color "$review_dir/access.tfplan" >"$review_dir/access.txt"
# Require no unreviewed ACL, DNS, settings, contact, or CI key change.
terragrunt apply "$review_dir/access.tfplan"
```

The state key is
`IaC/homelab/operator/tailscale-access/terraform.tfstate` in the existing
`rstuhlmuller-aws-s3-use1-datalake` bucket. Both S3 and OpenTofu state/plan
encryption use `alias/homelab-opentofu` in `us-east-1`. Authenticate through the
normal local AWS SSO profile before initialization; do not disable encryption or
use a local state fallback when that credential expires. Import only adopts the
existing policy into this state; it does not write the live policy.

Review the saved plan before apply. The October 24, 2026 adoption plan was a
no-op after reconciling the existing CI key generation 2 and both global DNS
resolvers. An earlier preview would have replaced all three working generation
2 keys with generation 1; never apply that stale plan. The full policy and
retained identities keep `prevent_destroy`. Do not remove resources from state
to bypass that guard. The aggregate DNS resource is alpha in provider 0.29.2;
pin its version and check the exact plan before updating it.
The keys are reusable, ephemeral, preauthorized, scoped to separate CI tags, and
expire after 90 days.

The sensitive `github_auth_keys` output contains the three CI credentials. Keep
outputs and saved plans private; never run an unredirected `terragrunt output -json`
or paste its output. Raw keys remain in encrypted state.

| Output key | GitHub secret | Scope | Node tag |
| --- | --- | --- | --- |
| `plan` | `TAILSCALE_AUTH_KEY` | `homelab-plan` environment | `tag:homelab-ci-plan` |
| `apply` | `TAILSCALE_AUTH_KEY` | `homelab-production` environment | `tag:homelab-ci-apply` |
| `cordium` | `TAILSCALE_CORDIUM_AUTH_KEY` | Repository | `tag:homelab-ci-cordium` |

CI uses the scoped auth key from the corresponding protected GitHub secret.
The [Harbor mirror](../../../../docs/harbor-tailscale-production.md) enrolls
with its checksum-pinned native client and removes its ephemeral node on cleanup.
Cordium's separate repository secret has no Kubernetes RBAC binding. Exact-main
and trusted-PR workflow checks remain necessary: auth keys do not encode GitHub
OIDC subject or workflow claims.

## Auth key rotation

Rotate every 60 days from provider creation, before the 90-day expiry. Increment
the committed `ci_key_generation` in
[`terragrunt.hcl`](../../units/operator/tailscale-access/terragrunt.hcl),
review and merge it, then use the encrypted saved-plan path above. Expect three
key replacements with no policy or identity changes. `create_before_destroy`
creates replacements first; the same apply revokes old auth keys. Coordinate
credential publication with CI dispatches. Auth-key deletion does not revoke
already enrolled nodes. Invalid keys are not silently recreated under the same
generation (`recreate_if_invalid = "never"`); prepare a reviewed generation
change when replacement is needed. Keep credentials out of arguments, logs and
git, and verify actual protected plan, apply and Cordium enrollment after rotation.

[Provider auth-key resource](https://registry.terraform.io/providers/tailscale/tailscale/0.29.2/docs/resources/tailnet_key).

## API proxy acceptance

The Tailscale operator's auth-mode API proxy impersonates node tags as Kubernetes
groups. The plan group can read cluster resources, including Helm release
Secrets. Kubernetes manifest planning also requires Application create/patch
permission for server-side dry runs: a fail-closed ValidatingAdmissionPolicy
rejects every non-dry-run write by that group. The protected apply group retains
cluster administration for the existing Argo CD bootstrap and cluster RBAC.

Deploy and verify the API proxy, admission policy, and RBAC before switching CI.
With the scoped credentials available, require an authenticated protected plan and apply
through `homelab-tailscale-operator.tail67beb.ts.net`, a rejected real write by
the plan group, and the existing Cordium denial/cleanup checks. The CI cutover
wires `scripts/ci/tailscale-access-check.py plan` into the plan workflow. It
verifies the proxy's actual
impersonated tag, accepts a server-side dry-run empty JSON Patch of the existing
Tailscale Application, then requires the identical real request to fail with the
specific admission-policy denial. The empty patch cannot change the Application
even if that guard is missing. The same cutover wires `apply` mode into the
existing diagnostics workflow to verify the apply tag and its cluster permission
without real writes. Only then retire
the old clientless Kubernetes endpoint. Roll back through reviewed source while
preserving the old transport until these checks pass.

Offline checks:

```sh
tofu -chdir=IaC/terragrunt-catalog/modules/tailscale-access init -backend=false
tofu -chdir=IaC/terragrunt-catalog/modules/tailscale-access validate
tofu -chdir=IaC/terragrunt-catalog/modules/tailscale-access test
nix develop --command python3 -I scripts/ci/install-kubeconfig-test.py
python3 -I scripts/ci/tailscale-access-check-test.py
```
