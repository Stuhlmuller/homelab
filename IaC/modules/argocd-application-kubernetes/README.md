# Argo CD Application via Kubernetes

This module manages an Argo CD `Application` custom resource with the
Kubernetes provider. It keeps application registration declarative without
requiring a locally authenticated Argo CD API session.

Use this module for private or core-only Argo CD installations where Terraform
can reach the Kubernetes API but should not depend on an exposed Argo CD API
server. The input shape intentionally mirrors the catalog `argocd-application`
module so existing Terragrunt units can keep the same readable application
definition.

The module includes a non-destructive `removed` block for the previous
`argocd_application.this` resource address. The live homelab state has already
been migrated to the Kubernetes manifest address, so this module does not carry
a persistent import block that would prevent future brand-new Applications from
being created normally.
