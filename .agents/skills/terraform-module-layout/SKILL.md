---
name: terraform-module-layout
description: Organize Terraform or OpenTofu module directories, files, documentation, submodules, and examples.
---

# Organize Terraform modules

Inspect a neighboring module and its caller to locate the module catalog and learn the repository's conventions. Identify what the new module owns, what the caller already owns, and which values the caller needs back.

**Lay out the module.** Use the module directory as its entry point. Keep the initial implementation in `main.tf`, typed inputs in `variables.tf`, and caller-facing results in `outputs.tf`. Describe inputs and outputs where declared. Give a reusable module a short README with its purpose and a minimal call.
Split a growing implementation by responsibility. Add `modules/<name>/` when a component merits a separate interface and `examples/<scenario>/` when a caller needs a worked configuration. [Standard module structure](https://developer.hashicorp.com/terraform/language/modules/develop/structure)
