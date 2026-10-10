# Tailscale access ownership

The `operator/tailscale-access` Terragrunt unit owns the complete tailnet policy
and three scoped CI auth keys through `tailscale/tailscale` 0.29.2.
The tailnet keeps Tailnet Lock enabled; OAuth/OIDC enrollment alone cannot sign
a new node. Existing unused federated identities remain protected in state until
the final migration retirement removes them through a reviewed provider apply
after signed-key CI acceptance.
Ordinary CI never applies this unit or receives policy administration scopes.
State and saved plans use the existing encrypted homelab S3 backend.

The provider reads the administrator API key from
`~/.config/homelab/tailscale/api-key`; keep the directory `0700` and file `0600`.
This is a private credential, never a desired-state input or repository file.

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

Generate the root stack, initialize the operator unit, and import the existing
policy only if `tailscale_acl.homelab` is absent from its state:

```sh
umask 077
review_dir="$(mktemp -d /private/tmp/homelab-tailscale-review.XXXXXX)"
cd IaC
terragrunt stack generate
cd operator/tailscale-access
terragrunt init
terragrunt state list >"$review_dir/state-list.txt"
if ! grep -Fxq tailscale_acl.homelab "$review_dir/state-list.txt"; then
  terragrunt import tailscale_acl.homelab acl
fi
terragrunt plan -out="$review_dir/access.tfplan"
terragrunt show -no-color "$review_dir/access.tfplan" >"$review_dir/access.txt"
# Review access.txt privately, then apply exactly the saved encrypted plan.
terragrunt apply "$review_dir/access.tfplan"
```

The state key is
`IaC/homelab/operator/tailscale-access/terraform.tfstate` in the existing
`rstuhlmuller-aws-s3-use1-datalake` bucket. Both S3 and OpenTofu state/plan
encryption use `alias/homelab-opentofu` in `us-east-1`. Authenticate through the
normal local AWS SSO profile before initialization; do not disable encryption or
use a local state fallback when that credential expires. Import only adopts the
existing policy into this state; it does not write the live policy.

Review the saved plan before apply. For the Tailnet Lock addition, expect exactly
three new `tailscale_tailnet_key.github` resources, with no ACL change or deletion
of the existing federated identities. The full policy and retained identities
keep `prevent_destroy`. Do not remove resources from state to bypass that guard.
The keys are reusable, ephemeral, preauthorized, scoped to separate CI tags, and
expire after 90 days. `preauthorized` is not a Tailnet Lock signature.

The sensitive `github_auth_keys` output is consumed only by the fixed operator
publisher. Never run an unredirected `terragrunt output -json` or paste its output.
The raw keys remain in encrypted state; signing and publication capture private
subprocess output without displaying it or passing keys in process arguments.

| Output key | GitHub secret | Scope | Node tag |
| --- | --- | --- | --- |
| `plan` | `TAILSCALE_AUTH_KEY` | `homelab-plan` environment | `tag:homelab-ci-plan` |
| `apply` | `TAILSCALE_AUTH_KEY` | `homelab-production` environment | `tag:homelab-ci-apply` |
| `cordium` | `TAILSCALE_CORDIUM_AUTH_KEY` | Repository | `tag:homelab-ci-cordium` |

Run the publisher on this homelab's trusted Mac signing node after the provider
apply. It uses `/Applications/Tailscale.app/Contents/MacOS/Tailscale`, verifies
Tailnet Lock is enabled and this node is a trusted signer, and checks the fixed
GitHub environment owner-review and branch protections. The default is read-only.
`--execute` also requires a clean checkout at signed, verified current `main`.

```sh
nix develop --command python3 -I scripts/tailscale-ci-configure.py
nix develop --command python3 -I scripts/tailscale-ci-configure.py --execute
```

Signing uses `tailscale lock sign file:<private temporary file>`. Wrapped keys
are saved at `~/.config/homelab/tailscale/ci-signed-keys.json` with mode `0600`
in an owned `0700` directory before GitHub publication. Keep an encrypted private
backup of that cache: retries reuse the same signatures instead of adding new
trusted authorities. An uncached existing signature fails closed; restore the
private cache before retrying. Never put it in git or an ordinary support bundle.
An advisory file lock prevents concurrent publishers on this Mac.

The helper sends each wrapped key to `gh secret set` over stdin. GitHub can expose
only secret metadata, so the helper checks presence and leaves actual key
acceptance to protected CI runs. Only after all three publications and metadata
checks succeed does it delete the two environment `TAILSCALE_CLIENT_ID` variables
and repository `TAILSCALE_CORDIUM_CLIENT_ID`. It changes no other secret or
variable. Partial publication keeps all old variables; rerunning is safe.
Retained provider identity outputs must not be republished.

Each CI consumer must use the pinned Tailscale action's `authkey` input and a
per-job `statedir` for Tailnet Key Authority state. The action logs out on cleanup;
ephemeral nodes are removed. Plan/apply secrets stay behind their existing
protected environments; Cordium's separate repository secret supports trusted
branch denial tests and has no Kubernetes RBAC binding. The workflow's exact-main
and trusted-PR checks remain necessary: signed keys do not carry GitHub OIDC
subject/workflow claims.

## Rotation and retirement

Generation 1 was prepared on October 10, 2026 UTC. Rotate every 60 days from
the provider creation timestamp, before the 90-day expiry. No timestamp or local environment
variable silently changes desired state. Increment the committed
`ci_key_generation` in
[`IaC/.catalog/units/operator/tailscale-access/terragrunt.hcl`](../../.catalog/units/operator/tailscale-access/terragrunt.hcl),
review/merge it, then use the private saved-plan path above. Expect three key
replacements and no policy or identity changes. `create_before_destroy` creates
the replacements first; the same apply then revokes old auth keys. Pause new CI
dispatches during apply/publication; existing enrolled nodes are not revoked by
auth-key deletion. An expired/revoked key is not automatically recreated under
the same generation (`recreate_if_invalid = "never"`). Increment the generation
through a reviewed recovery change if an early replacement is needed.

Publish the new generation with the same preview/execute commands. Verify one
protected plan including real-write denial, one apply diagnostics run, and the
Cordium happy/denial checks before retiring old signing authority:

```sh
nix develop --command python3 -I scripts/tailscale-ci-configure.py --retire-previous
nix develop --command python3 -I scripts/tailscale-ci-configure.py --retire-previous --execute
```

The retirement mode removes only older-generation authorities recorded by this
publisher and matched to their original auth-key metadata. It requires valid,
cached current signatures first. `tailscale lock remove` re-signs existing nodes
by default; the helper never disables Tailnet Lock or removes unrelated signers.
It deletes old wrapped cache entries only after authority removal is confirmed.
Do not roll back a generation or restore revoked keys; prepare a fresh generation.

A pre-signed key embeds a private Tailnet Lock signing key. Its cryptographic
signing authority is broader than its normal auth-key tag permissions, and that
authority remains trusted after auth-key expiry/revocation. The explicit retirement
step is therefore required, not optional cleanup. Treat any leak as a signing-key
incident using Tailscale's recovery procedure, not merely an auth-key rotation.
This deployment intentionally accepts that tradeoff to retain Tailnet Lock while
using ephemeral GitHub-hosted runners.

Primary references: [pinned GitHub Action Tailnet Lock setup](https://github.com/tailscale/github-action/blob/d1b6cd204f8dceda5b3eaad7f1f767be390056cd/README.md#tailnet-lock),
[CLI signing and authority removal](https://tailscale.com/docs/reference/tailscale-cli/lock),
[provider auth-key resource](https://registry.terraform.io/providers/tailscale/tailscale/0.29.2/docs/resources/tailnet_key).

## API proxy acceptance

The Tailscale operator's auth-mode API proxy impersonates node tags as Kubernetes
groups. The plan group can read cluster resources, including Helm release
Secrets. Kubernetes manifest planning also requires Application create/patch
permission for server-side dry runs: a fail-closed ValidatingAdmissionPolicy
rejects every non-dry-run write by that group. The protected apply group retains
cluster administration for the existing Argo CD bootstrap and cluster RBAC.

Deploy and verify the API proxy, admission policy, and RBAC before switching CI.
After signed-key publication, require an authenticated protected plan and apply
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
tofu -chdir=IaC/modules/tailscale-access init -backend=false
tofu -chdir=IaC/modules/tailscale-access validate
tofu -chdir=IaC/modules/tailscale-access test
nix develop --command python3 -I scripts/ci/install-kubeconfig-test.py
python3 -I scripts/ci/tailscale-ci-configure-test.py
python3 -I scripts/ci/tailscale-access-check-test.py
```
