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
umask 077
plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/homelab-operator.XXXXXX")"
trap 'rm -rf -- "$plan_dir"' EXIT
AWS_PROFILE=<administrator-profile> terragrunt --log-disable plan \
  -out="$plan_dir/plan.out" -no-color
AWS_PROFILE=<administrator-profile> terragrunt --log-disable show -no-color "$plan_dir/plan.out"
AWS_PROFILE=<administrator-profile> terragrunt --log-disable apply -no-color "$plan_dir/plan.out"
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

The pull-request `Terragrunt Gate` is an always-present aggregate. Its
unprivileged static job runs for every PR and owns live-scope detection. Only a
trusted same-repository PR whose diff contains a declared live input may enter
the `homelab-plan` environment; forks and other changes must leave the live job
skipped. The aggregate fails unless static checks succeed and the applicable
live plan or same-repository skip-note job has the expected result. Keep the
exact workflow contract asserted in `scripts/ci/static-checks.sh`.
That assertion pins the normalized live-scope and aggregate-gate bodies by
SHA-256 and pins each credentialed job as normalized JSON, so comments, dead
code, or added post-authentication steps cannot satisfy the check. Its closed
inventory rejects new environment-, secret-, token-, or write-permission jobs
until their complete job definition is reviewed and hashed. Conftest also
rejects direct live `kubectl`, `talosctl`, AWS, Terragrunt, OpenTofu, Terraform,
or non-rendering Helm output and any command after the private-log wrapper;
credentials stay scoped to the one live step.

The local secret hook rejects common plan/state filenames and inspects ZIP
members or JSON structure for OpenTofu plan/state signatures, including staged
blobs whose working-tree file was removed.

Do not require a new Actions context in ruleset `14700233` before the workflow
that emits it is merged. First observe `Terragrunt Gate` on a no-live-plan PR, a
trusted live-plan PR, and a fork; then add only that context while preserving
the existing required checks and verify a fresh no-live-plan PR does not
deadlock.

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
rg -n \
  "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" \
  docs/knowledge-base .agents/skills
```

## Scanner Runtime Pin

For #791, this follow-up replaces Trivy `0.69.3` proposed in PR #905 with a
temporary package-only `0.74.0` override. The proposed older scanner is affected
by [CVE-2026-55092](https://github.com/aquasecurity/trivy/security/advisories/GHSA-mcj4-mphf-j9ff),
fixed in `0.71.1`; this is not evidence of an already-merged scanner job on
`main`. The version, source hash, and vendor hash come from the
[upstream nixpkgs recipe](https://github.com/NixOS/nixpkgs/blob/83199d0d373dd3ac2b9a1996b1d0263f76ab7a4c/pkgs/by-name/tr/trivy/package.nix).
The scanner-only builder also uses Go `1.26.7`, with its source hash from the
[upstream Go recipe](https://github.com/NixOS/nixpkgs/blob/83199d0d373dd3ac2b9a1996b1d0263f76ab7a4c/pkgs/development/compilers/go/1.26.nix).
Go `1.26.3` meets Trivy's build requirement but lacks subsequent
[standard-library security fixes](https://go.dev/doc/devel/release#go1.26.0).
The native Go recipe and bootstrap remain unchanged; `flake.lock`, other
tools, Checkov inclusion, and all four platforms remain unchanged.

The #888 full-lock candidate at `83199d0d373dd3ac2b9a1996b1d0263f76ab7a4c`
cannot replace this pin: its Checkov dependency `ecdsa-0.19.2` is blocked for
`CVE-2024-23342`, and nixpkgs 26.11 drops Intel Mac support. Remove the override
only when a reviewed full refresh supplies a patched scanner and passes the
all-platform, static, Conftest, and pre-commit gates. Roll back the package
change through a reviewed revert; do not substitute unpinned local binaries.

Operator client skew is unchanged and tracked in #788. The documented cluster
is Kubernetes `1.34.1` / Talos `1.11.3`, but the existing shell supplies
kubectl `1.36.1` / talosctl `1.13.2`. This exceeds the supported
[kubectl minor skew](https://kubernetes.io/releases/version-skew-policy/#kubectl)
and does not match
[Talosctl guidance](https://docs.siderolabs.com/talos/v1.11/getting-started/talosctl).
No new live version check was performed. Correct clients together with the
supported server baseline; this scanner change does not endorse live use.

PR #905's wrapper isolation and #915 reference/argument validation are separate
requirements. The runtime pin does not fix option injection or replace those
controls. They are not an OS sandbox or a local credential boundary; other
inherited Trivy settings and credential providers may still apply locally.

The local Go `1.26.7` and Trivy `0.74.0` source builds passed on
`aarch64-darwin`, after an initial disk-space failure and approved cleanup of
disposable caches. All three source/vendor hashes were independently verified.
All four no-build evaluations pass; native builds on the other three platforms
were not run. Combined static, Conftest, scanner self-check, ShellCheck, scoped
workflow lint, Markdown and pre-commit checks pass. The newly covered images
still fail the vulnerability policy (#918, #919); BusyBox coverage is unknown
(#920). Local code checks are not a successful hosted vulnerability gate.

Issue #916 records a scanner-audit limitation: `govulncheck 1.7.0` rejects the
`-X:jsonv2` suffix in Go build versions and can silently omit standard-library
findings. Preserve each binary's original extraction and remove only that
suffix in a separate diagnostic copy; never rewrite the binary or substitute
a different compiler version. A fresh extraction from the Go `1.26.7` build
removed all 13 standard-library matches found with Go `1.26.3`.
These extracts lack `pkgSymbols`, so results have module/version precision,
not proof of symbol presence or call reachability.

The module-level [OpenPGP finding GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932)
is not an affected package in the exact Linux/amd64 import graph checked under
issue #917. Offline dependency selection with the final source/vendor and Go `1.26.7`
(`CGO_ENABLED=1`, `GOEXPERIMENT=jsonv2`, no extra tags) selected 3,082 packages,
with zero unsafe OpenPGP or Rekor PKI imports and no incomplete packages/errors.
Other `x/crypto` packages explain the module metadata match; the selected
OpenPGP implementation is the maintained ProtonMail library. This is cross-target
package analysis, not verification of a built Linux executable. Keep #917 open
for that artifact check; no exception or vulnerability-free claim is made.

## Runtime Image Inventory

Issue #791's scanner uses native Terragrunt evaluation and Helm/Kustomize
rendering, not only literal images in values files. The same current helper
and toolchain inspect both revisions; historical scanner scripts are never
executed. Current-source snapshots include non-ignored local edits and exclude
ignored generated units/caches. Base snapshots come from the exact Git commit.
Neither snapshot changes the operator's checkout or Git refs.

```sh
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --self-check
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --list
nix develop --command bash scripts/ci/image-vulnerability-scan.sh --list <base-commit-sha>
```

The self-check is offline. Listing may fetch public charts; it reports selected
image references, not a successful vulnerability scan. Scan mode rejects
selected unpinned references while still scanning selected immutable images.
Unchanged images remain the weekly/full scan's responsibility. Malformed
references, failed renders, missing values, and unsupported image-generation
contracts fail before scanning; none become an empty successful inventory.

The renderer covers the bootstrap Helm release, evaluated Argo CD sources,
and nested Applications discovered in local Kustomize output. It preserves
values-file ordering, inline values/values-object precedence, parameters,
release names, and namespaces. Unsupported source/options fail instead of
silently approximating Argo CD. Native client-only rendering uses no cluster
connection, provider initialization, state, or apply hook. Reviewed HCL and
charts still need to be trusted: this is not an arbitrary-code sandbox.
Temporary rendered output carries an inventory-only namespace annotation;
never apply it or reuse it as a deployment manifest.

Each chart source/version is fetched once per run and the same bytes are reused
for current/base comparison. HTTPS and an exact version are not signature
verification or a committed chart digest; that provenance work remains in #791.
The offline Kubernetes capability baseline is `1.34.1`, unless the Application
explicitly supplies a version. It is not a live cluster/API-discovery result.

Typed extraction includes PodSpecs, installation/upgrade/deletion hooks,
Prometheus and Alertmanager image fields, reloader and cert-manager solver
arguments, Tailscale proxy configuration, and the local-path helper Pod template.
Monitoring sidecar/init-container overrides, Thanos, PrometheusAgent and
ThanosRuler require explicit review and currently fail closed. Istio
gateway `auto` images must resolve through rendered injector/mesh settings;
unknown overrides fail. Kiali's hidden server default is restricted to the
source-verified `v2.26.0` operator/default-CR contract, which uses the operator
Pod's version label. A new operator release or customization needs its image
contract reviewed, not an assumed default. See the upstream
[Kiali supported-image mapping](https://github.com/kiali/kiali-operator/blob/v2.26.0/playbooks/kiali-default-supported-images.yml)
and [resolution logic](https://github.com/kiali/kiali-operator/blob/v2.26.0/roles/default/kiali-deploy/tasks/main.yml).

The 2026-08-30 local regression rendered 29 Helm releases and expanded the
inventory from 66 to 90 textual references: 24 unpinned additions, no removals.
One existing BusyBox alias accounts for the difference from unique identities.
An unchanged-base comparison selected nothing. Replaying draft #820's six
Prometheus digest overrides selected all six, including the reloader argument;
the old values-only extractor selected none. These are inventory checks, not
successful vulnerability scans or rollout approval.

This is repository-declared image coverage, not a live Pod census, proof of
complete package/SBOM coverage, or a vulnerability exception. No runtime image
pins or protected-job permissions change. Roll back through a reviewed revert;
do not waive the pin or package-coverage checks to obtain a green result.

## GitHub Commit Signature Verification

[Issue #931](https://github.com/Stuhlmuller/homelab/issues/931) records a
2026-08-30 signing-identity mismatch. Local `git verify-commit` succeeds, but
GitHub returns `verified: false`, `reason: bad_email` for draft #930 and two
sampled parent/peer drafts. The repository's configured no-reply committer
address is absent from the registered signing key identities; the key itself
is registered, signing-capable and has a verified email. Do not confuse local
cryptographic validity with GitHub's identity verification or CI test results.

For a proposed commit, replace `COMMIT_SHA` below with its exact SHA. The check
must return `true` and exit 0; the sampled commits currently return `false`.

```sh
gh api repos/Stuhlmuller/homelab/commits/COMMIT_SHA \
  --jq '.commit.verification | {verified,reason}' |
  jq -e '.verified == true and .reason == "valid"'
```

[GitHub's documented reason](https://docs.github.com/en/rest/commits/commits#get-a-commit)
and the registered-key metadata isolate the cause, so broad bisection or
temporary instrumentation is unnecessary. Repair requires an owner-approved
key/identity change. Preserve no-reply privacy; never silently publish another
email, edit private/global signing state, disable signing, or rewrite stacked
history. Verify a new commit through GitHub, then explicitly decide how to
repair existing records. This does not waive #813/#815 or rollout approvals.

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
bash -n \
  scripts/octelium-gateway-dns.sh \
  scripts/octelium-public-dns.sh \
  scripts/octelium-cloudflare-origin-port.sh \
  scripts/octelium-entra-oidc.sh
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
kubectl -n istio-system get cronjob octelium-api-upnp \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'
scripts/octelium-e2e-check.sh
```

The gRPC check resolves the API host through `1.1.1.1` and pins curl to that
public address, so an Octelium split-DNS answer cannot hide a broken WAN edge.
It accepts only the expected unauthenticated response: HTTP `200` with
`grpc-status: 16`; generic HTTP responses fail the gate.
Do not treat the repository-side target change as recovery until the CronJob
has a recent success and the public probe passes.

Before treating Tailscale as unnecessary for Kubernetes access, validate both
human paths from outside the homelab. On the operator workstation, run
`octelium connect -d`, generate the client kubeconfig with `octelium config
kubernetes-api.homelab`, run its printed export, set the file to mode `0600`,
and require `kubectl --request-timeout=15s get nodes` to succeed. Repeat the
config, mode, and `kubectl` check inside a Cordium Workspace, whose client
session is created automatically. Also require Secret reads and a server-side
dry-run create to be denied there; Cordium has restricted read-only access.
Keep the Tailscale fallback until both pass; Talos transport is a separate
retirement gate.

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
resolved workflow commit differs. Every push to `main` runs only the cancellable
`Terragrunt Apply Request` check; it uses no protected environment, stored
secret, or OIDC permission and prints the exact dispatch command plus active
apply links without opening a production approval. The protected apply's first
post-approval step requires the expected, workflow, and current `main` SHAs to
match before credentials or live commands.
The live job retains only the newest pending run and never cancels an
in-progress apply. GitHub's native environment/concurrency queue cannot enforce
an automatic approval SLA; strict expiry needs an externally hosted GitHub App
deployment-protection rule with a durable lease. Until then, dispatch only when
a reviewer is ready to approve.

The focused Octelium private Kubernetes workflow has the same exact-`main`,
current-head, production-approval, serialized-run, private-log, static, and
Conftest gates. Its fixed helper extracts exactly
`Policy/homelab-private-kubernetes-access` and
`Service/kubernetes-api.homelab`, never prunes, and requires a second apply to
report no changes. The lifecycle helper installs cleanup before creating its
30-minute, one-authentication Credential, binds its watch to the unique run it
dispatches, and verifies Credential, Session, and GitHub-secret revocation on
exit. See `docs/ci-cd.md`.

The gate checks the Octelium control plane, IdentityProvider `entra`, private
`kubernetes-api.homelab` Service, synced
workload credential, ready connector replica, and
`ambient.istio.io/redirection=enabled` on every active connector pod. It also
checks Cluster/API/portal TLS responses, the complete homelab WEB Service
catalog, public DNS for each existing
`*.stinkyboi.com` app hostname, and HTTPS access to each app hostname through
Octelium public WEB access. It requires AFFiNE's anonymous Service mode, NOFX's
`homelab-human-web-access` policy, and unauthenticated NOFX `/` and `/api/health`
responses to carry Octelium's `401` denial header. It also validates AFFiNE's
native-client CORS preflight plus public `serverConfig` GraphQL query, confirms
AFFiNE rejects an unauthenticated workspace query, and ensures every other
public app Service remains non-anonymous. App hostnames
must not resolve to private
Octelium service IPs or the old Tailscale wildcard. The same script probes the
Cordium nested workspace wildcard for valid edge TLS and probes the reviewed
callback hostnames for public DNS and path-limited reachability; the
n8n expected-negative webhook probe must see an n8n webhook response body, not
only a generic HTTP 404 from Cloudflare or the Istio gateway, while the Policy
Bot webhook probe must use the POST shape GitHub sends and require the app-level
HTTP 400 webhook validation response, not just any non-404 response.

Rendered Kubernetes policy also enforces the access contract:
`policy/kubernetes.rego` rejects Tailscale Funnel and classifies every
gateway-attached `VirtualService`, every `Gateway`, and every `Ingress` except
the explicit `compass-discovery` class as externally reachable by default.
Those resources must declare `homelab.rst.io/access-plane: octelium`; only
gatewayless or mesh-only `VirtualService` resources and Compass discovery
entries are exempt. The policy also requires reviewed
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

The pull request workflow renders temporary Terragrunt plans to policy JSON and
runs Terraform-plan Conftest policy during `scripts/ci/terragrunt-plan.sh`. It
then runs `scripts/ci/conftest-policies.sh` for static YAML policy checks. Plan
details and live command output are withheld from the public PR and Actions
logs. Run the same order locally when reproducing a failure.

CI plan and apply scripts call `terragrunt stack generate` before filtering
units. When `IaC/terragrunt.stack.hcl`, `IaC/.catalog`, or `IaC/modules`
changes, the scripts plan or apply the matching generated unit groups instead
of relying on `--filter-affected` against ignored generated `terragrunt.hcl`
files. Stack, catalog, module, shared root/provider, and tracked generated-group
changes such as provider locks use the local `*` because each command runs from
its generated-unit root. Plan-only toolchain, Terraform-policy, and execution-
script changes also refresh every plan without widening production apply scope.
Affected-only runs combine the repository-relative group with the Git selector
so Terragrunt cannot queue another unit group. Intentional operator plans use
mode `0700` temporary directories. CI may save plans in generated unit caches
for exact apply and policy checks; its scripts use `umask 077` and delete those
files on exit. Normal local `terragrunt plan` commands do not write plan
artifacts into generated caches.
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

Production applies resolve their affected-unit base from the newest successful
historical push apply or full dispatch. Full runs are named `Full @ <sha>`;
targeted runs are named `Targeted <app> @ <sha>` and never advance that
checkpoint. A missing, unreachable, or non-ancestor result fails closed so an
apply cannot become the new successful checkpoint while skipping an unknown
deleted-unit range. Manual-dispatch secret scans cover `HEAD^..HEAD`; the
working-tree Gitleaks scan still covers the complete checkout.

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
