# Homelab

This repository is the declarative control surface for a Talos Linux
Kubernetes homelab. It is both production infrastructure and learning material:
changes should be safe to review, repeatable to apply, and useful to someone
building a similar setup from scratch.

The cluster is managed through repository-owned desired state. Infrastructure
uses OpenTofu modules orchestrated by Terragrunt, and Kubernetes runtime state
is delivered through Argo CD, Helm, Kustomize, and committed manifests.

## Repository Map

| Path | Purpose |
| --- | --- |
| `.talos/` | Talos machine configuration, patches, and Talos client references. |
| `IaC/` | OpenTofu modules and Terragrunt stacks for cloud, bootstrap, and GitOps registration. |
| `clusters/homelab/` | Kubernetes desired state for Argo CD, platform services, and applications. |
| `docs/` | Operator runbooks and learner-facing explanations. |
| `docs/knowledge-base/` | Obsidian-compatible Markdown vault for cross-cutting architecture and operations context. |
| `policy/` | Conftest/Rego policies for Terraform, Kubernetes, and GitHub Actions checks. |
| `scripts/ci/` | Reusable local and CI validation helpers. |
| `specs/` | Feature specs, plans, task lists, and design artifacts. |

## Change Flow

```text
pull request
  -> Terragrunt/OpenTofu desired state
  -> Argo CD Application registration
  -> Helm, Kustomize, or repo-owned manifests
  -> Kubernetes cluster state
```

Do not repair live state by hand-editing cloud resources, Talos config,
Kubernetes objects, Argo CD resources, or secret-manager resources. Capture the
desired state in this repository, validate it, then apply it through the
documented Terragrunt, Argo CD, Helm, Kustomize, or Talos path.

## Getting Started

Use the Nix development shell when possible. It provides the expected local
operator tools, including `awscli2`, `conftest`, `kubectl`, `opentofu`,
`ripgrep`, `talosctl`, and `terragrunt`.

```sh
nix develop
```

Start with these documents:

- `ONBOARDING.md` for Talos nodes, cluster endpoints, storage assumptions, and
  the bootstrap story.
- `docs/argocd-bootstrap.md` for the initial Argo CD Terragrunt stack.
- `docs/argocd-app-onboarding.md` for adding GitOps-managed applications.
- `docs/ci-cd.md` for GitHub Actions, Tailscale, AWS OIDC, and rollout gates.
- `docs/secrets-aws-ssm.md` for the External Secrets and AWS SSM contract.
- `docs/storage-nfs.md` for QNAP-backed Kubernetes persistent storage.
- `docs/knowledge-base/00-home.md` for the Obsidian knowledge-base index.

This is a public repository. Keep raw secrets, kubeconfigs, Talos secrets,
tokens, private keys, and raw certificate material out of git. Commit safe
references such as ExternalSecret names, SSM parameter paths, placeholders, and
non-secret defaults instead.

## Validation

Run the smallest validation that proves the change. For most infrastructure or
GitOps changes, start with:

```sh
terragrunt hcl fmt --check
terragrunt hcl validate
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
git diff --check
```

For docs-only changes, focused Markdown and whitespace checks are usually
enough:

```sh
git diff --check -- README.md docs/ AGENTS.md ONBOARDING.md .agents/skills
rg -n "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" README.md docs AGENTS.md ONBOARDING.md .agents/skills
```

See `docs/validation-runbook.md` and
`docs/knowledge-base/operations/validation-gates.md` for the full validation
model, including Terragrunt plans, Kustomize renders, server-side diffs, and
live readiness checks.

## Operating Principles

- Prefer declarative, reproducible configuration over manual mutation.
- Keep desired-state inputs in committed non-secret code or data.
- Use environment variables only for CI/CD credential plumbing and secret
  injection, not as normal Terragrunt, OpenTofu, Helm, Kustomize, Talos, or app
  configuration inputs.
- Keep ingress, storage, backup, and restore implications explicit and
  documented.
- Update the knowledge base when a change materially affects architecture,
  workflows, platform services, workloads, storage, secrets, validation, or
  operating assumptions.

## Reuse Notes

The repository includes homelab-specific values such as LAN addresses, storage
paths, and application hostnames. Treat those as examples of the pattern, not
universal defaults. Before reusing this project, replace local topology,
identity, DNS, storage, and secret contracts with values that match your own
environment.
