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

For Image Updater changes, also render the controller overlay and confirm the
managed write-back targets stay intentional:

```sh
kubectl kustomize clusters/homelab/apps/argocd-image-updater
rg -n "writeBackTarget|imageName|manifestTargets" clusters/homelab/apps/argocd-image-updater/imageupdater.yaml
```

## Octelium Cutover Checks

Before removing any Tailscale-backed app route, the Octelium replacement path
must pass:

```sh
scripts/octelium-e2e-check.sh
```

Pass `--octelium-context` and `--homelab-context` when the Octelium control
plane and homelab connector live in different Kubernetes clusters.

The gate checks the Octelium control plane, synced workload credential, ready
connector replica, non-Istio Cluster/API/portal responses, the complete homelab
WEB Service catalog, and a tunnel to `homelab-demo.homelab`.

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

Focused unit validation:

```sh
cd IaC/live/<stack>/<unit>
terragrunt --log-disable init -backend=false -no-color
terragrunt --log-disable validate -no-color
terragrunt --log-disable plan -no-color
```

Implicit stack validation:

```sh
cd IaC/live/argocd-apps
terragrunt run --all --filter-affected --parallelism 1 --source-update -- plan -no-color
```

The pull request workflow renders saved Terragrunt `plan.out` files to local
`plan.json` files and runs Terraform-plan Conftest policy during
`scripts/ci/terragrunt-plan.sh`. It then runs `scripts/ci/conftest-policies.sh`
for static YAML policy checks. Run the same order locally when reproducing PR
gate behavior.

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
