# Homelab

A Talos Linux and Kubernetes homelab managed through Git. This repository
operates the cluster and documents how to build, maintain, and recover a
similar setup. Changes should be reviewable and repeatable.

## How it works

- **Infrastructure as code.** Terragrunt orchestrates OpenTofu modules for
  infrastructure, cluster bootstrap, and Argo CD application registration.
- **GitOps.** Argo CD reconciles Kubernetes workloads from Helm charts,
  Kustomize overlays, and committed manifests.
- **Change delivery.** Put desired-state changes in Git and deliver them
  through pull requests. Executable checks and protections govern merge and
  rollout. See the [CI/CD guide](docs/ci-cd.md).

## Get started

Open the Nix development shell from the repository root:

```sh
nix develop
```

- **Set up a cluster** with the [Talos onboarding guide](ONBOARDING.md) and
  [Argo CD bootstrap guide](docs/argocd-bootstrap.md).
- **Add a workload** with the [application onboarding guide](docs/argocd-app-onboarding.md).
- **Explore the architecture or find a runbook** through the
  [OpenWiki quickstart](openwiki/quickstart.md).

> [!IMPORTANT]
> Adapt networking, identity, DNS, and storage settings to your environment
> before applying the configuration. This repository is public. Commit only
> safe secret references and placeholders. Keep credentials and private key
> material out of Git.

## Validate changes

Run the repository's static validation from the root:

```sh
nix run .#validate
```

Use the [validation runbook](docs/validation-runbook.md) to pick focused checks
for your change and find the relevant plan, render, or rollout verification.
