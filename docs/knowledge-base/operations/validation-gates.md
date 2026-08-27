# Validation Gates

Tags: #operations #validation

## Default Gate

Run the smallest validation that proves the change and record unavailable
checks in the PR or final response.

For most repo changes, start with:

```sh
terragrunt hcl fmt --check
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
git diff --check
```

Operator-owned AWS bootstrap units require a focused backend-free validation
and an administrator-authenticated plan before apply:

```sh
cd IaC/operator/github-actions-role-policy
terragrunt --log-disable init -backend=false -lockfile=readonly -no-color
terragrunt --log-disable validate -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable init -reconfigure -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable state list
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_role.github_actions' Github-TF-State
AWS_PROFILE=<administrator-profile> terragrunt --log-disable import \
  'aws_iam_user.external_secrets' external-secrets_aws-ssm-auth
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan -out=plan.out -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color plan.out
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color plan.out
```

Run each import only on the first rollout, or during state recovery, when
`state list` does not contain its address: `aws_iam_role.github_actions` or
`aws_iam_user.external_secrets`. Backend-free validation deliberately leaves
the working directory detached from shared state, so the authenticated
`init -reconfigure` must precede every import, production plan, or apply from
that directory.

The GitHub workflow role must not plan or apply `IaC/operator`; those units own
the permissions that protect the workflow from self-administration.

## GitHub Workflow Checks

Workflow changes are covered by `scripts/ci/conftest-policies.sh` and
`policy/workflows.rego`. External `uses:` references must be pinned to a full
40-character commit SHA; keep an optional trailing version comment when it helps
reviewers map the immutable pin back to the upstream release tag.

The CodeQL workflow in `.github/workflows/codeql.yml` runs on pushes
and pull requests targeting `main` and on its weekly schedule. It has one
buildless `actions` analysis job because this repository has no compiled
application source. Treat it as CI/CD security automation: workflow edits
should pass the static policy gate locally before relying on GitHub's code
scanning result.

For docs-only or knowledge-base-only changes, focused Markdown and whitespace
checks are acceptable when the infrastructure graph is untouched:

```sh
git diff --check -- AGENTS.md ONBOARDING.md docs/knowledge-base .agents/skills
rg -n "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" docs/knowledge-base .agents/skills
```

## Kubernetes Source Checks

Use the renderer that matches the changed source:

```sh
kubectl kustomize clusters/homelab/apps/<app>
kubectl kustomize clusters/homelab/platform/<service>
helm template <release> <chart> -f clusters/homelab/apps/<app>/values.yaml
kubectl diff --server-side -k clusters/homelab/apps/<app>
```

For image automation changes, render the retirement source, validate Renovate,
and confirm no image bypasses digest policy:

```sh
kubectl kustomize clusters/homelab/apps/argocd-image-updater
npx --yes --package renovate renovate-config-validator renovate.json
nix develop --command bash scripts/ci/static-checks.sh
```

For `platform-dns` changes, render the overlay and compare upstream answers
before rollout. After Argo CD syncs, verify CoreDNS contains the intended
resolvers and a workload pod receives a public answer rather than a sinkhole:

```sh
kubectl kustomize clusters/homelab/platform/dns
dig +short A iptorrents.com @1.1.1.1
kubectl -n kube-system get configmap coredns -o yaml
kubectl -n media exec deployment/prowlarr -c app -- getent ahostsv4 iptorrents.com
```

## Octelium Cutover Checks

Before running `octops init`, validate the self-hosted Cluster prerequisites:

```sh
kubectl kustomize clusters/homelab/platform/multus
kubectl kustomize clusters/homelab/apps/octelium-storage
kubectl kustomize clusters/homelab/apps/octelium-cluster
kubectl kustomize clusters/homelab/apps/octelium-public
bash -n scripts/octelium-gateway-dns.sh scripts/octelium-public-dns.sh scripts/octelium-cloudflare-origin-port.sh scripts/octelium-entra-oidc.sh
scripts/octelium-cluster-bootstrap.sh --help
```

After a Multus rollout or burst of Octelium service pod replacements, verify
all Multus pods remain ready and below their 512Mi memory limit. A daemon at its
limit plus `multus-shim` timeouts means the Octelium ingress can lose every
endpoint while Argo CD still reports `platform-multus` healthy.

```sh
kubectl -n kube-system rollout status daemonset/kube-multus-ds
kubectl -n kube-system top pod -l app=multus --containers
kubectl -n octelium get events --field-selector reason=FailedCreatePodSandBox
```

After the prerequisite apps are applied, `scripts/octelium-cluster-bootstrap.sh`
checks the Multus CRD, Multus DaemonSet rollout, Octelium node labels, and
PostgreSQL/Redis readiness before it calls `octops init` in front-proxy mode.
The `octelium-cluster` app must render only the Istio front-door route and its
HTTP/2 upstream `DestinationRule` in `istio-system`; it must not create the
`octelium` namespace because Octelium genesis owns that namespace during
bootstrap. The bootstrap wrapper applies the required privileged Pod Security
labels to the namespace after `octops` creates it.

Before declaring Octelium-backed app UI access healthy, the replacement path
must pass:

```sh
scripts/octelium-e2e-check.sh
```

Pass `--octelium-context` and `--homelab-context` when the Octelium control
plane and homelab connector live in different Kubernetes clusters.

CI/CD Octelium changes should also pass shell syntax checks for
`scripts/ci/install-kubeconfig.sh`, `scripts/octelium-ci-credential.sh`, and
`scripts/octelium-ci-kubeconfig-secret.sh`. Validate that
`docs/examples/octelium/homelab-services.yaml` parses and contains Service
`kubernetes-api-ci` plus core `ClusterConfig` `default` with human
`maxPerUser: 32`, and that User `homelab-ci` keeps matching 30-day clientless
Session and access-token lifetimes before applying it with `octeliumctl`.
Apply the `ClusterConfig` with `--include ClusterConfig` before the normal
catalog apply because the include flag replaces the default resource-kind list.
The static gate requires manual Homelab Diagnostics and Terragrunt Apply
dispatches to carry an exact expected `main` SHA and fail before work when the
resolved workflow commit differs. Terragrunt Apply acquires its production
concurrency lock only in the live job downstream of that guard and retains the
full pending queue.

The gate checks the Octelium control plane, IdentityProvider `entra`, synced
workload credential, ready connector replica, Cluster/API/portal TLS responses,
the complete homelab WEB Service catalog, public DNS for each existing
`*.stinkyboi.com` app hostname, and HTTPS access to each app hostname through
Octelium public WEB access. It also requires AFFiNE and NOFX anonymous Service
mode, validates AFFiNE's native-client CORS preflight plus public `serverConfig`
GraphQL query, confirms AFFiNE rejects an unauthenticated workspace query, and
ensures every other public app Service remains non-anonymous. App hostnames
must not resolve to private
Octelium service IPs or the old Tailscale wildcard. The same script probes the
Cordium nested workspace wildcard for valid edge TLS and probes the reviewed
callback hostnames for public DNS and path-limited reachability; the
n8n expected-negative webhook probe must see an n8n webhook response body, not
only a generic HTTP 404 from Cloudflare or the Istio gateway, while the Policy
Bot webhook probe must use the POST shape GitHub sends and require the app-level
HTTP 400 webhook validation response, not just any non-404 response.

Rendered Kubernetes policy also enforces the access contract:
`policy/kubernetes.rego` rejects Tailscale Funnel, requires public
`VirtualService`, `Gateway`, and non-discovery `Ingress` resources to declare
`homelab.rst.io/access-plane: octelium`, and requires reviewed
`homelab.rst.io/public-callback-*` annotations for unauthenticated callback
hosts such as `n8n-webhook.stinkyboi.com` and
`policy-bot-hook.stinkyboi.com`. Run `scripts/ci/conftest-policies.sh` after
changing route manifests or the Octelium public tunnel/DNS host list.

The script must report failed probes as `FAIL:` lines and finish with a nonzero
exit code when any check fails. Keep expected-negative probes inside guarded
conditionals and avoid empty-array expansion under `set -u`, so macOS Bash 3.2
does not exit before the failure summary.

## Policy Bot Checks

Repository-local `.policy.yml` changes need Policy Bot validation, not just YAML
parsing:

```sh
policy-bot validate -p .policy.yml
curl -sS --fail-with-body https://policy-bot.stinkyboi.com/api/validate -T .policy.yml
```

Use the live endpoint when the local binary and Docker validator are
unavailable.

## Terragrunt Checks

Generate explicit stack units before focused validation:

```sh
cd IaC
terragrunt stack generate
```

Focused unit validation:

```sh
cd IaC/live/<stack>/<unit>
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable validate -no-color
terragrunt --log-disable plan -no-color
```

Explicit stack validation:

```sh
cd IaC
terragrunt stack run plan
```

The pull request workflow renders saved Terragrunt `plan.out` files to local
`plan.json` files and runs Terraform-plan Conftest policy during
`scripts/ci/terragrunt-plan.sh`. It then runs `scripts/ci/conftest-policies.sh`
for static YAML policy checks. Run the same order locally when reproducing PR
gate behavior. The live plan, apply, and diagnostics jobs verify the Octelium
Kubernetes access path with `kubectl --request-timeout=15s version` after
`scripts/ci/install-kubeconfig.sh` writes the token-only kubeconfig.

CI plan and apply scripts call `terragrunt stack generate` before filtering
units. When `IaC/terragrunt.stack.hcl`, `IaC/.catalog`, or `IaC/modules`
changes, the scripts plan or apply the matching generated unit groups instead
of relying on `--filter-affected` against ignored generated `terragrunt.hcl`
files. Stack, catalog, module, shared root/provider, and tracked generated-group
changes such as provider locks use the local `*` because each command runs from
its generated-unit root. Plan-only toolchain, Terraform-policy, and execution-
script changes also refresh every plan without widening production apply scope.
Affected-only runs combine the repository-relative group with the Git selector
so Terragrunt cannot queue another unit group. Saved plans can live in generated
module caches; the plan gate discovers them there and writes policy JSON beside
each generated unit.
Production Argo CD Application registration saves each affected plan, evaluates
the Terraform policy JSON, rejects manifest replacement/deletion, then applies
that exact plan. A protected manual dispatch may set one exact `argocd_app` unit
name to reconcile committed desired state without widening the run to its group
or running any unrelated production apply phase. Manual production and
diagnostic dispatches reject every ref except `refs/heads/main`; the production
environment independently limits deployments to the `main` branch.
Deleted-unit handling compares tracked units and explicit-stack paths at
the base and head revisions, so a catalog migration at the same path is not a
destroy while removing a stack block still retires its state. The production
Azure credential gate compares AzureAD unit sources and stack blocks plus the
shared root inputs they consume; unrelated stack changes do not require Azure
credentials.

Production applies resolve their affected-unit base from the latest successful
push-triggered `Terragrunt Apply` workflow `head_sha`, not the immediately
preceding push. Targeted manual reconciliations never advance that checkpoint.
A missing, unreachable, or non-ancestor result fails closed so an apply cannot
become the new successful checkpoint while skipping an unknown deleted-unit
range. Manual-dispatch secret scans cover `HEAD^..HEAD`; the working-tree
Gitleaks scan still covers the complete checkout.

GitHub-hosted live jobs depend on the Octelium clientless Kubernetes route. If
that route is the failed dependency, restore reviewed
`IaC/live/kubernetes-node-labels` state from a trusted LAN machine with a direct
`https://10.1.0.199:6443` kubeconfig, shared-backend AWS credentials, a saved
Terragrunt plan, and the Terraform-plan Conftest gate documented in
`docs/ci-cd.md`. No repository kubeconfig secret is part of that recovery path.

The trusted GitHub Actions PR plan job is serialized with a shared concurrency
group because it reads the same OpenTofu S3 backend state across pull requests.
Do not treat a queued PR plan as unhealthy; it is waiting for the live-state
lock lane. Same-PR replacement runs also queue instead of canceling in-progress
plans, because interrupting OpenTofu while it holds an S3 backend lock can leave
a stale lock that blocks later plans.

## Live Rollout Rule

Do not mutate live cluster, Talos, cloud, Argo CD, or secret-manager state until
the relevant validation has passed or the unavailable validation is recorded
with the risk. Desired state must be represented in the repo before applying it.

## Source Files

- `docs/validation-runbook.md`
- `.agents/skills/terragrunt-workflows/SKILL.md`
