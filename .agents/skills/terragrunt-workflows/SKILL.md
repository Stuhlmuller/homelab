---
name: terragrunt-workflows
description: Use Terragrunt safely in this homelab repository. Trigger when Codex needs to add, modify, validate, explain, or troubleshoot Terragrunt catalog entries, reusable OpenTofu/Terraform modules, Terragrunt units, implicit or explicit stacks, stack generation, stack run/output/clean commands, run/list/find/filter workflows, or Terragrunt/OpenTofu validation commands.
---

# Terragrunt Workflows

## Overview

Use this skill to keep Terragrunt changes declarative, reviewable, and aligned with this repo's public homelab conventions. Prefer repository-owned HCL and docs over live fixes, pin reusable sources, validate before mutation, make the command scope obvious, and keep the Obsidian knowledge base current.

## First Pass

1. Read the nearby runbook and the target HCL before changing anything.
2. For substantive work, read `docs/knowledge-base/00-home.md` and the relevant linked note before building new infrastructure behavior.
3. Inspect `IaC/root.hcl` for shared locals, remote state, provider generation, and `catalog.urls`.
4. Inspect peer units under the same stack root before inventing a new shape.
5. Identify whether the request is about a reusable module, a Terragrunt unit, an implicit stack, an explicit stack, or catalog/scaffold usage.
6. Choose read-only discovery and planning commands first. Do not apply, destroy, migrate backends, or mutate live infrastructure unless the user explicitly asks and the relevant validation has passed.

Use these source docs when command behavior might have drifted:

- Stacks overview: https://docs.terragrunt.com/features/stacks/
- Explicit stacks: https://docs.terragrunt.com/features/stacks/explicit/
- Stack operations: https://docs.terragrunt.com/features/stacks/stack-operations/
- Catalog: https://docs.terragrunt.com/features/catalog/
- CLI reference: https://docs.terragrunt.com/reference/cli/

## Vocabulary

- Module: reusable OpenTofu/Terraform code, either in `IaC/modules/<name>` or a remote catalog repo.
- Unit: a deployable directory with `terragrunt.hcl`; the unit points at a module with `terraform.source` and supplies inputs.
- Implicit stack: a directory tree of units. Terragrunt discovers the stack from the filesystem and runs it with `terragrunt run --all ...`.
- Explicit stack: a `terragrunt.stack.hcl` blueprint that generates units and nested stacks into `.terragrunt-stack/`.
- Catalog: one or more trusted module catalogs configured in `catalog { urls = [...] }`, browsed with `terragrunt catalog` or used by `terragrunt scaffold`.

## Repo Conventions

- Keep desired-state inputs in committed HCL or non-secret data. Do not introduce `get_env`, `TF_VAR_*`, shell-exported values, or hidden local inputs for normal configuration.
- Keep secrets out of git. Commit safe references, templates, encrypted material, or external-secret contracts only.
- Include `IaC/root.hcl` from every normal unit so shared providers, remote state, tags, and catalog settings stay consistent.
- For Argo CD Application registrations, follow `IaC/live/argocd-apps/<app>/terragrunt.hcl`: include `root`, include `argocd-provider.hcl`, source the pinned catalog module, and declare upstream ordering with `dependencies`.
- Keep Git-backed Argo CD `target_revision` values on `main` unless a temporary non-default revision is explicitly documented.
- Pin remote catalog module sources by tag or commit. Do not point production units at an unpinned branch.
- Add or update docs when changing architecture, bootstrap flow, storage, secrets, networking, or operational assumptions.
- Update `docs/knowledge-base` in the same change when Terragrunt work changes module ownership, bootstrap behavior, app registration patterns, dependency structure, validation gates, or platform/workload inventory.

## Catalog And Scaffold

Use the catalog when the task is to browse or instantiate trusted reusable modules.

Common commands:

```sh
terragrunt catalog
terragrunt catalog --root-file-name root.hcl
terragrunt catalog --no-shell --no-hooks
terragrunt scaffold <MODULE_URL> --root-file-name root.hcl --no-shell --no-hooks
```

Guidance:

- Treat catalog/scaffold templates as executable supply chain. Use only trusted catalogs that have been reviewed.
- Prefer `--no-shell --no-hooks` unless a reviewed template needs shell or hook behavior.
- Review generated `terragrunt.hcl` before committing. Make it match local include, source pinning, dependency, and input conventions.
- If a catalog module is missing, stop and either update the catalog in a separate change or use the documented local fallback for that one unit.

## Modules And Units

When adding reusable infrastructure behavior:

1. Put reusable OpenTofu/Terraform code in a module or consume a trusted catalog module.
2. Keep module inputs typed, small, and copyable. If a new resource requires copying a large HCL block, introduce or extend a module.
3. In each unit, set `terraform.source` to a local module path or pinned remote catalog module.
4. Use `dependencies { paths = [...] }` for ordering when outputs are not needed.
5. Use `dependency "<name>" { config_path = "../unit" }` only when the unit must read outputs from another unit.
6. Keep all non-secret inputs explicit in the unit or inherited root config.

Remote catalog source pattern:

```hcl
terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/<module-name>?ref=<tag-or-commit>"
}
```

Local module source pattern:

```hcl
terraform {
  source = "../../modules/<module-name>"
}
```

Choose the relative path from the unit to `IaC/modules/<module-name>` based on nearby units; do not add shell-derived paths.

## Implicit Stacks

Use implicit stacks for the current repo's normal layout: a directory such as `IaC/live/argocd-apps` containing one child unit per application.

Commands:

```sh
terragrunt run --all plan -no-color
terragrunt run --all --filter './cert-manager' -- plan -no-color
terragrunt run --all --filter-affected -- plan
terragrunt find --filter 'type=unit'
terragrunt list --filter './IaC/live/** | type=unit'
```

Notes:

- Run from the intended stack root so `--all` scopes to the right units.
- Use `--filter` for focused work and `--filter-affected` for changes between the default branch and `HEAD`.
- Use `--` when separating Terragrunt flags from OpenTofu/Terraform flags would avoid ambiguity.
- Be careful with `run --all apply` and `run --all destroy`: Terragrunt may add auto-approval because multiple units cannot share interactive approval safely.
- Check external dependency prompts and never destroy external dependencies casually.
- Do not set `TF_PLUGIN_CACHE_DIR` for `run --all`; use Terragrunt's provider cache features if provider caching is needed.

## Explicit Stacks

Use explicit stacks when repeated patterns need to generate units or nested stacks from `terragrunt.stack.hcl`.

Core blocks:

```hcl
unit "example" {
  source = "git::https://github.com/org/catalog.git//units/example?ref=v1.2.3"
  path   = "example"
  values = {
    name = "example"
  }
}

stack "environment" {
  source = "git::https://github.com/org/catalog.git//stacks/environment?ref=v1.2.3"
  path   = "environment"
  values = {
    environment = "dev"
  }
}
```

Commands:

```sh
terragrunt stack generate
terragrunt stack generate --parallelism 4
terragrunt stack run plan
terragrunt stack run plan --source-update
terragrunt stack output --format json
terragrunt stack clean
```

Rules:

- Do not place `terragrunt.hcl` and `terragrunt.stack.hcl` in the same component directory.
- Do not commit `.terragrunt-stack/`; add it to `.gitignore` when explicit stacks are introduced.
- Expect `terragrunt.stack.hcl` generation to create `.terragrunt-stack/<unit>/terragrunt.hcl` and `terragrunt.values.hcl`.
- Do not rely on includes inside `terragrunt.stack.hcl`; design values and generated units accordingly.
- Do not put dependencies on `stack` blocks. Model dependency relationships between generated units.
- Clean stale generated files with `terragrunt stack clean` when units or values are removed, then regenerate.
- Keep local state outside `.terragrunt-stack/` if experimenting with local state, and never commit local state files.

## Command Selection

- Format HCL: `terragrunt hcl fmt` or `terragrunt hcl fmt --check`.
- Validate HCL syntax and config shape: `terragrunt hcl validate`.
- Initialize for local validation without touching remote state: `terragrunt --log-disable init -backend=false -no-color`.
- Validate the selected unit with OpenTofu/Terraform: `terragrunt --log-disable validate -no-color`.
- Plan one unit: run from that unit directory with `terragrunt --log-disable plan -no-color`.
- Plan an implicit stack: run from the stack root with `terragrunt run --all plan -no-color`.
- Inspect matching units/stacks: `terragrunt find --filter '<query>'` or `terragrunt list --filter '<query>'`.
- Generate an explicit stack: run from the directory containing `terragrunt.stack.hcl` with `terragrunt stack generate`.
- Run an explicit stack: `terragrunt stack run plan`, `apply`, or `destroy` only after validation and explicit user intent.
- Read stack outputs: `terragrunt stack output`, optionally `--format json` or `--format raw <unit.output>`.

## Validation Gate

Use the smallest validation that proves the change and record anything unavailable:

```sh
nix flake check
terragrunt hcl fmt --check
terragrunt hcl validate
```

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
terragrunt run --all plan -no-color
```

Kubernetes or Argo CD source validation, when relevant:

```sh
kubectl kustomize clusters/homelab/apps/<app>
kubectl kustomize clusters/homelab/platform/storage
rg -n "password|token|secret|api[_-]?key|PRIVATE KEY|BEGIN CERTIFICATE|kubeconfig" clusters IaC docs
```

Do not proceed to live apply if formatting, validation, render, or plan fails unless the user explicitly accepts the recorded risk.
