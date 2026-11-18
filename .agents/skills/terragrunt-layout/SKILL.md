---
name: terragrunt-layout
description: Organize reusable modules, Terragrunt units, and stacks across infrastructure providers using explicit deployment scopes, shared configuration, and stable state boundaries.
---

# Organize Terragrunt infrastructure

Trace a neighboring unit from its authored declaration through generated configuration,
module source, dependencies, and backend key. Follow the repository's existing scopes
and generation workflow when extending it.

## Choose boundaries

A module owns reusable resource implementation. A unit instantiates a module with
its own inputs, dependencies, and state. A stack groups units deployed together.
Choose unit boundaries around lifecycle, ownership, permissions, and recovery.
Resources that must change together generally belong in one unit.

Keep reusable implementation in the module catalog and deployment instances in
the live tree. Independently versioned catalogs support staged upgrades.
Preserve an established monorepo catalog when that is the repository convention.

## Place units

Use meaningful deployment scopes, from broad to narrow. Include only levels that
distinguish actual targets. The names below are illustrative placeholders.

```text
live/
  root.hcl
  shared.hcl
  scope-a/
    scope.hcl
    _global/
      shared-service/
        terragrunt.hcl
    target-a/
      target.hcl
      _global/
        shared-service/
          terragrunt.hcl
      environment-a/
        environment.hcl
        category-a/
          service-a/
            terragrunt.hcl
```

- Scope identifies an administrative or isolation boundary.
- Target selects where infrastructure runs.
- Environment distinguishes deployments sharing a target. Omit it when an
  enclosing scope already identifies the environment.
- Category groups related units for navigation. Add it when it improves discovery.
- Unit is the leaf deployment with its own state.
- `_global` holds units shared by the children of its immediate parent.
  Provider configuration must still select the appropriate execution target.

Put shared data at the narrowest common ancestor. Load named HCL data files with
the repository's include or `read_terragrunt_config` pattern. Keep common module
defaults in shared templates and instance differences beside the live declaration.

These placement principles adapt Gruntwork's hierarchy and per-unit state guidance.
[Infrastructure live](https://docs.gruntwork.io/2.0/docs/overview/concepts/infrastructure-live/)

## Arrange explicit stacks

When the repository uses explicit stacks, distinguish authored catalog templates,
live stack instances, and generated units. Follow its actual output-path settings.

```text
catalog/
  modules/
    service/
      main.tf
      variables.tf
      outputs.tf
  units/
    service/
      terragrunt.hcl
  stacks/
    service-group/
      terragrunt.stack.hcl
live/
  root.hcl
  scope-a/
    target-a/
      service-group/
        terragrunt.stack.hcl
        stack.hcl
```

The module implements resources. The unit template connects module source, shared
configuration, and declared values. A reusable stack composes recurring groups.
The live stack selects templates and instance paths. An adjacent data file such
as `stack.hcl` is appropriate when that convention already exists.

Add a new instance to its owning stack. Introduce a reusable stack template when
the composition itself repeats. Edit the authored source and regenerate using
the repository workflow. For implicit stacks, directory placement defines the
group of units available to orchestration.

Before creating anything, identify the existing module and template that fit.
Expose inputs callers need, retain shared constraints in the reusable implementation,
and use existing catalog scaffolding when available.
[Developer self-service](https://docs.gruntwork.io/2.0/docs/overview/concepts/developer-self-service/)

## Preserve state and dependency ownership

For each proposed unit, record its authored path, generated path if applicable,
module source, backend key, and dependencies. A directory move can change a
path-derived backend key. Preserve existing mappings or explicitly plan a state
migration before moving an existing unit.

Use dependency outputs when values must flow between units. Use ordering
dependencies when only execution order matters. Check that the dependency graph
has no cycle and each managed resource has one owner.

Name resources and attach metadata using the target platform's conventions.
Keep shared metadata at its common scope and instance metadata near the unit.
Inspect effective values for naming limits and fields that affect resource identity.
[Labels and tags](https://docs.gruntwork.io/2.0/docs/overview/concepts/labels-tags/)

## Verify the layout

Show the proposed tree and explain each new boundary. Identify reusable files,
instance files, and generated output. Run the repository's formatting, generation,
and focused validation commands, then inspect the affected plan when available.
Verify resolved sources, input inheritance, dependency paths, unique state keys,
and unintended replacement or deletion before delivery.
