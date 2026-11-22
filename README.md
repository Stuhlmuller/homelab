# Homelab

**One Acer, three ZimaBoards, and a NAS walk into a Kubernetes cluster.**

This is my Talos Linux homelab and a field guide for building your own.
The lab doubles as a place to self-host, try out infrastructure ideas,
and practice getting services back online when things break.

[![Latest homelab commit][last-commit]][history]
[![Monthly homelab commit activity][commit-activity]][activity]

## Meet the hardware

| Node | Hardware | Role | Logical CPUs | RAM visible to Kubernetes |
| --- | --- | --- | ---: | ---: |
| `acer` | Acer PC | Talos control plane | 8 | 15.5 GiB |
| `zimaboard-0` | ZimaBoard | Talos worker | 4 | 7.6 GiB |
| `zimaboard-1` | ZimaBoard | Talos worker | 4 | 7.6 GiB |
| `zimaboard-2` | ZimaBoard | Talos worker | 2 | 1.8 GiB |

**Storage sidekick.** A QNAP TS-451+ serves Kubernetes persistent volumes
over NFS. Its storage pool uses four 2 TB disks in RAID 5.
See the [storage guide](docs/storage-nfs.md).

## Lab notebook

Green squares mark GitHub contributions by [@rstuhlmuller][profile]
across repositories. For homelab-specific changes, see the repository's
[commit activity chart][activity] and [contributor graphs][contributors].

[![GitHub contribution heatmap for rstuhlmuller][heatmap]][profile]

## How it works

- **Infrastructure as code.** Terragrunt orchestrates OpenTofu modules for
  infrastructure, cluster bootstrap, and Argo CD application registration.
- **GitOps.** Argo CD reconciles Kubernetes workloads from Helm charts,
  Kustomize overlays, and committed manifests.
- **Change delivery.** Put desired-state changes in Git and deliver them
  through pull requests. Executable checks and protections govern merge and
  rollout. See the [CI/CD guide](docs/ci-cd.md).

## Agents in the lab

I use Codex to work on the lab. [OpenWiki](openwiki/quickstart.md) helps it
find the relevant source and runbooks, and repository skills give it
repeatable workflows for jobs like adding an app or repairing a PR.

For larger changes, Spec Kit turns an idea into a spec, plan, and task list.
Agents work in isolated Git worktrees, run focused checks, and follow signed
PRs through protected merge. When a change rolls out, they verify the deployed
revision and exercise the service. See the
[agent workflows](openwiki/operations/agent-workflows.md).

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

[last-commit]: https://img.shields.io/github/last-commit/Stuhlmuller/homelab?style=flat-square
[commit-activity]: https://img.shields.io/github/commit-activity/m/Stuhlmuller/homelab?style=flat-square
[history]: https://github.com/Stuhlmuller/homelab/commits/main/
[activity]: https://github.com/Stuhlmuller/homelab/graphs/commit-activity
[contributors]: https://github.com/Stuhlmuller/homelab/graphs/contributors
[heatmap]: https://ghchart.rshah.org/22a06b/rstuhlmuller
[profile]: https://github.com/rstuhlmuller#contribution-graph
