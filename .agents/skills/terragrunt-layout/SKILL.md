---
name: terragrunt-layout
description: Choose boundaries and paths for new OpenTofu or Terraform modules, Terragrunt units, and stacks across cloud, Kubernetes, and Argo CD infrastructure.
---

# Organize Terragrunt infrastructure

Trace one comparable deployment from its live declaration through its unit to its module. Identify the authored files, shared includes, and backend key before choosing paths.

- **Module** — Put reusable resource implementation in the existing module catalog. Reuse a module when only instance inputs differ. Follow the repository's version-pinning convention for external sources.
- **Unit** — Use a unit for resources that need an independent plan, apply, and state. Keep resources that change and recover together in one unit. Put instance inputs and dependency output wiring in the live declaration or its unit template, following neighboring units.
- **Stack** — Add the unit to the stack that owns its deployment. In an implicit stack, the unit directory establishes membership. In an explicit stack, edit the owning `terragrunt.stack.hcl` or its source catalog and regenerate using the repository workflow. Introduce a reusable stack when the same composition is instantiated together.

Choose paths around the target platform and its deployment boundaries. For Kubernetes, identify the cluster and namespace scope. For Argo CD, identify the owning Application stack and reuse its application module and unit template. Keep chart values and manifests in their existing GitOps source, with application references and dependency wiring in the Terragrunt declaration.

For a new AWS layout, start with `account/region/environment/category/unit`. Omit the environment layer when the account already identifies it. Use `account/_global` for account-wide units and `account/region/_global` for units shared across environments in one region. In an established tree, preserve its deployment boundaries. Put shared inputs at the narrowest common scope.

Verify the resolved unit path, module source, dependencies, and unique backend key using the repository's generation and validation commands. If a proposed layout moves existing units with path-derived keys, keep those paths stable or scope a state migration explicitly.

[Gruntwork infrastructure-live layout guidance](https://docs.gruntwork.io/2.0/docs/overview/concepts/infrastructure-live/)

Follow platform-native naming and metadata conventions. For Kubernetes and Argo CD, preserve namespace scope, resource names, and existing labels and annotations. Check rendered resources and avoid changing selectors through shared metadata.

For AWS resources, derive names from the repository’s organization, environment, application, workload, and region labels where service naming limits allow. Inherit common tags at the provider or shared configuration level and add workload-specific metadata such as owner or cost center at the unit. Check representative planned resources for the effective tags.
[Labels and tags](https://docs.gruntwork.io/2.0/docs/overview/concepts/labels-tags/)

For developer self-service, check the infrastructure catalog for a maintained blueprint before creating a module. Keep shared security defaults and constraints in the blueprint. Expose the inputs developers actually choose in the live unit. If the catalog provides a scaffold, use it to create the instance in the owning stack.
[Developer self-service](https://docs.gruntwork.io/2.0/docs/overview/concepts/developer-self-service/)
