---
name: infrastructure-labels-tags
description: Choose consistent infrastructure resource names and metadata when adding or changing naming, labels, annotations, or tags.
---

# Infrastructure names and metadata

Inspect neighboring resources and shared provider or module configuration before
choosing a convention. Identify which metadata supports ownership, environment,
application identity, operations, or cost allocation.

Compose names from the identifiers needed in the target scope. Keep abbreviations
consistent and check the target platform's character, length, and uniqueness rules.
Distinguish a resource's immutable identity from descriptive metadata.

Place shared metadata at the narrowest common configuration scope. Merge instance
metadata through the existing module interface and establish which values win
when keys overlap. Keep secrets and sensitive identifiers out of metadata.

Check effective names and metadata in rendered configuration or the plan.
Inspect replacement effects, selectors, and references before renaming existing
resources or changing identity-bearing labels.

Gruntwork's examples describe AWS naming and tags. Apply the naming and ownership
principles using the target platform's supported metadata mechanisms.
[Labels and tags](https://docs.gruntwork.io/2.0/docs/overview/concepts/labels-tags/)
