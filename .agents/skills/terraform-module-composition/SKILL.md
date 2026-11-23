---
name: terraform-module-composition
description: Design Terraform or OpenTofu module boundaries and connect dependencies through typed inputs and outputs.
---

# Compose Terraform modules

Prefer sibling modules when the caller can connect them directly. For example, pass a network module's subnet IDs into a service module.
The same service module can then accept IDs for an existing network. Type the input around the fields the service consumes and expose only the outputs its callers need. [Module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)
