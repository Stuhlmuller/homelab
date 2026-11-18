---
name: terraform-module-layout
description: Organize new Terraform or OpenTofu modules, choose boundaries and caller interfaces, and preserve resource addresses when extracting a module from existing configuration.
---

# Organize Terraform modules

Inspect a neighboring module and its caller to locate the module catalog and learn the repository's conventions. Identify what the new module owns, what the caller already owns, and which values the caller needs back.

**Lay out the module.** Use the module directory as its entry point. Keep the initial implementation in `main.tf`, typed inputs in `variables.tf`, and caller-facing results in `outputs.tf`. Describe inputs and outputs where declared. Give a reusable module a short README with its purpose and a minimal call.
Split a growing implementation by responsibility. Add `modules/<name>/` when a component merits a separate interface and `examples/<scenario>/` when a caller needs a worked configuration. [Standard module structure](https://developer.hashicorp.com/terraform/language/modules/develop/structure)

**Compose at the caller.** Prefer sibling modules when the caller can connect them directly. For example, pass a network module's subnet IDs into a service module. The same service module can then accept IDs for an existing network. Type the input around the fields the service consumes and expose only the outputs its callers need. [Module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)

**Preserve upgrade paths during extraction.** Moving a declaration between files in one directory keeps its address. Moving it into a child module changes its address.
For an existing deployment in the same state, map each changed address with a supported `moved` block in the common ancestor module.
Account for instance keys and retain earlier moves so callers can skip intermediate releases. Preserve existing outputs by forwarding child outputs where needed. [Refactoring modules](https://developer.hashicorp.com/terraform/language/modules/develop/refactoring)

Run the repository's formatting and validation checks. For an extraction, inspect a plan from an existing caller for the expected address moves and investigate any unintended creation, replacement, or destruction.
