---
name: terraform-module-refactoring
description: Preserve Terraform or OpenTofu state addresses and caller interfaces when renaming, moving, or extracting existing resources and modules.
---

# Refactor Terraform modules

Moving a declaration between files in one directory keeps its address. Moving it into a child module changes its address.
For an existing deployment in the same state, map each changed address with a supported `moved` block in the common ancestor module.
Account for instance keys and retain earlier moves so callers can skip intermediate releases. Preserve existing outputs by forwarding child outputs where needed. [Refactoring modules](https://developer.hashicorp.com/terraform/language/modules/develop/refactoring)

Run the repository's formatting and validation checks. For an extraction, inspect a plan from an existing caller for the expected address moves and investigate any unintended creation, replacement, or destruction.
