# Tailscale access ownership

The `operator/tailscale-access` Terragrunt unit owns the complete tailnet policy
and three GitHub federated identities through `tailscale/tailscale` 0.29.2.
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

Review the saved plan before apply. Expect one adopted policy update and three
new federated identities, with no unrelated resource deletion. Policy validation
runs its embedded positive and negative access tests. Both policy and identities
have `prevent_destroy`; the policy cannot reset to a default on destruction.

The output `github_identity_client_ids` contains non-secret identity selectors:

| Output key | GitHub variable | Scope |
| --- | --- | --- |
| `plan` | `TAILSCALE_CLIENT_ID` | `homelab-plan` environment |
| `apply` | `TAILSCALE_CLIENT_ID` | `homelab-production` environment |
| `cordium` | `TAILSCALE_CORDIUM_CLIENT_ID` | Repository |

Publish those fixed bindings through the repository-owned operator helper after
applying the saved provider plan. The default previews; `--execute` requires a
clean checkout at signed, verified current `main`, checks the existing GitHub
owner-review/environment protection rules, and verifies all three written values.
It accepts neither client IDs nor GitHub targets as arguments and creates no
OAuth secret. Re-running reconciles the same three variables.

```sh
nix develop --command python3 -I scripts/tailscale-ci-configure.py
nix develop --command python3 -I scripts/tailscale-ci-configure.py --execute
```

Plan/apply identity subjects require their protected GitHub environments.
Production additionally requires a workflow from `refs/heads/main`. Cordium
keeps branch subjects and its existing wrong-ref/wrong-workflow Octelium denial
tests; that identity has no Kubernetes RBAC binding. Each identity can mint
only an ephemeral node auth key for its own tag. No long-lived CI OAuth secret
or Kubernetes bearer token is copied to GitHub.

The Tailscale operator's auth-mode API proxy impersonates node tags as Kubernetes
groups. The plan group can read cluster resources, including Helm release
Secrets. Kubernetes manifest planning also requires Application create/patch
permission for server-side dry runs: a fail-closed ValidatingAdmissionPolicy
rejects every non-dry-run write by that group. The protected apply group retains
cluster administration for the existing Argo CD bootstrap and cluster RBAC.

Deploy and verify the API proxy, admission policy, and RBAC before switching CI.
After identity publication, require an authenticated protected plan and apply
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
