---
type: pattern
title: "Helm Chart Organization"
description: "Upstream Helm charts, local values, shared Terragrunt Application ownership, and the smallest source layout for deployment changes."
tags: ["pattern", "helm", "argocd", "terragrunt"]
---

# Helm Chart Organization

Decision researched 2026-10-04: keep pinned upstream charts, app-local values,
and Kustomize extras. Generate Application boilerplate in the shared Terragrunt
stack/template. This minimizes the files and configuration languages an agent
must read for an ordinary deployment.

## Source Layout

```text
IaC/terragrunt.stack.hcl                    # unit identity and output-path index
IaC/stacks/<app>/stack.hcl                  # app registration inputs and chart pins
IaC/stack-defaults.hcl                      # shared Application defaults
IaC/.catalog/units/live/argocd-app/          # shared Application construction
clusters/homelab/apps/<app>/
  values.yaml                              # overrides for the upstream chart
  kustomization.yaml                       # only when local resources exist
  externalsecret.yaml, networkpolicy.yaml   # app-owned resources, as needed
  README.md                                # readiness, storage, rollback
```

Platform resources keep their existing `clusters/homelab/platform/<service>`
ownership. The inspected repository has no committed `Chart.yaml` or
`Chart.lock`; it already references remote charts directly. Its
[application stacks](../../IaC/stacks),
[OpenClaw values and extras](../../clusters/homelab/apps/openclaw), and
[Harbor values and extras](../../clusters/homelab/apps/harbor) demonstrate
this layout.

Argo CD supports an upstream Helm source plus Git-hosted `$values`, avoiding a
local copy of the upstream chart. A third source can supply app-owned
Kustomize resources. Keep these sources within one application's lifecycle;
Argo explicitly discourages using multiple sources to combine unrelated apps.
[Argo CD multiple sources](https://argo-cd.readthedocs.io/en/release-3.4/user-guide/multiple_sources/)

## Reuse Boundaries

- Keep chart name, repository, exact revision, release name, and exceptional
  Helm parameters explicit in `IaC/stacks/<app>/stack.hcl`. Generate common Application metadata,
  destination, sync policy, and repository defaults. Inspect the evaluated
  manifest rather than copying a previous generated unit.
- Use the existing `app-template` chart for suitable generic container apps.
  Its maintained Common Library already generates Kubernetes resources from
  values; a homelab wrapper would add another configuration layer.
  [App Template documentation](https://bjw-s-labs.github.io/helm-charts/docs/app-template/)
- Keep values beside their app. Introduce shared values only for actual repeated
  settings consumed by the same chart schema; list shared files before app
  overrides. Later value files win, and `parameters`, `valuesObject`, and
  inline `values` can override them. Keep intentional exceptions visible.
  [Argo CD Helm precedence](https://argo-cd.readthedocs.io/en/release-3.4/user-guide/helm/#helm-value-precedence)
- Do not add umbrella charts merely to collect independent applications.
  Retain explicit multi-chart platform compositions such as Istio, where
  versions, release names, and resource ownership are already reviewed together.
- Introduce a local chart only when maintaining reusable custom templates is
  the actual requirement. A library chart shares template functions but cannot
  itself be installed. A dependency-bearing application chart should commit
  `Chart.lock` and rebuild dependencies with `helm dependency build`.
  [Helm library charts](https://helm.sh/docs/topics/library_charts/),
  [Helm dependency build](https://helm.sh/docs/helm/helm_dependency_build/)

This is a repository design decision, not a claim that one layout fits every
deployment. It preserves the existing chart behavior while concentrating
repetition in the Application registration layer.

## Generated Output and Upgrade Checks

Keep generated Terragrunt units ignored and regenerate them from the stack.
Let Helm render workloads during Argo reconciliation; Argo uses Helm for
templating and owns their lifecycle. Commit app-specific values and generator
inputs, not an additional copy of rendered chart YAML.
[Argo CD Helm lifecycle](https://argo-cd.readthedocs.io/en/release-3.4/user-guide/helm/)

For a chart upgrade, render the exact chart revision with its release name,
namespace, all value files, and declared parameters. Check resource identities,
storage, secrets, CRDs, and workload-specific assertions before rollout.
Preserve the existing `$values` placeholder-source shape during this structural
refactor; Argo documents that a values source with `path` also generates
resources, while an omitted `path` makes it values-only. Changing that shape
requires separate rendered/live verification.
[Argo CD values-source behavior](https://argo-cd.readthedocs.io/en/release-3.4/user-guide/multiple_sources/#helm-value-files-from-external-git-repository)

The existing
[Harbor chart inventory check](../../scripts/ci/harbor-images-check.py)
compares chart declarations with
[reviewed inventory](../../scripts/config/harbor-image-charts.json).
Keep its coverage when changing stack representation. Refresh the inventory
only after rendering changed charts and satisfying the image-publication gates
in [Harbor Private OCI Registry](../operations/harbor-oci.md). An inventory refresh alone does not verify images.

## Chart Update Coverage Finding

Repository-configured Renovate coverage remains incomplete: [renovate.json](../../renovate.json)
configures image discovery, but no Argo CD file matching or custom chart
extractor. Renovate's Terragrunt manager reads module dependencies in
`terragrunt.hcl`; it does not cover chart revisions in the app `stack.hcl` files. Its
Argo CD manager requires explicit YAML file matching. Do not infer automated
chart updates from successful image-update PRs.
[Renovate Terragrunt manager](https://docs.renovatebot.com/modules/manager/terragrunt/),
[Renovate Argo CD manager](https://docs.renovatebot.com/modules/manager/argocd/)

Follow-up: add a tested custom manager for committed HCL chart declarations
and Argo CD matching for child Application YAML. Cover HTTP charts with the
Helm datasource and OCI charts with the Docker datasource; compare extracted
dependencies with the Harbor inventory. Keep the inventory/image publication
gate, and do not update ignored generated units. Renovate supports custom regex
extraction for dependencies outside built-in managers.
[Renovate regex manager](https://docs.renovatebot.com/modules/manager/regex/),
[Renovate OCI charts](https://docs.renovatebot.com/modules/manager/argocd/#oci-open-container-initiative-helm-charts)

## Small Context for the Next Deployment

Read [New Application Pattern](new-application.md), the target app directory, and its
`IaC/stacks/<app>/stack.hcl` inputs.
Generate once, then inspect only that app's effective sources and policy:

```sh
terragrunt --working-dir IaC stack generate
terragrunt --log-disable --working-dir IaC/live/argocd-apps/descheduler \
  render --json --write=false --no-color \
  | jq '{manifest: .inputs.manifest, dependencies: .dependencies.paths}'
```

Replace `descheduler` with the app name. This evaluates local configuration;
it does not plan or apply infrastructure. The command was verified against the
existing generated `descheduler` unit. See [Validation Gates](../operations/validation-gates.md) for
the full repository and deployment checks.
