---
name: terragrunt-self-service
description: Design or use reusable infrastructure catalogs and scaffolding so developers can instantiate Terragrunt deployments through supported module interfaces.
---

# Terragrunt developer self-service

Find a maintained catalog entry that matches the requested deployment.
Inspect its inputs, outputs, versioning, examples, and validation before choosing
reuse, a scoped extension, or a new entry.

Keep reusable implementation and shared constraints in catalog modules.
Expose inputs developers need to choose per deployment, with typed interfaces
and useful defaults. Put deployment-specific values in live declarations.

Use existing catalog discovery and scaffolding when available. Inspect generated
files for unresolved placeholders, source versions, instance paths, dependencies,
and state configuration before running the declared validation workflow.

When adding a reusable entry, include the smallest working usage example and
validation that exercises its interface. Explain which values callers supply and
which behaviors the module owns. Keep upgrade guidance proportional to interface
or lifecycle changes.

A catalog entry supports the repository's delivery workflow. Deployment authority
and readiness remain governed by the user's task and executable pipeline controls.

[Developer self-service](https://docs.gruntwork.io/2.0/docs/overview/concepts/developer-self-service/)
