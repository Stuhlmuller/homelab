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
terragrunt run --all --parallelism 1 --source-update plan -no-color
```

## Live Rollout Rule

Do not mutate live cluster, Talos, cloud, Argo CD, or secret-manager state until
the relevant validation has passed or the unavailable validation is recorded
with the risk. Desired state must be represented in the repo before applying it.

## Source Files

- `docs/validation-runbook.md`
- `.agents/skills/terragrunt-workflows/SKILL.md`
