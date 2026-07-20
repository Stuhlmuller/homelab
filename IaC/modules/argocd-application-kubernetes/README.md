# Argo CD Application via Kubernetes

This module is a small policy wrapper around the Kubernetes provider's native
`kubernetes_manifest` resource. Callers pass an Argo CD `Application` manifest
using the same field names as the CRD instead of a second, module-specific
schema.

The wrapper retains the repository's required OpenTofu state and plan
encryption, field-manager ownership, and computed-field normalization for
metadata, destinations, and multi-source paths. Repository-owned source fields
such as `targetRevision` remain declarative.

The non-destructive `removed` block preserves the completed migration from the
old `argocd_application.this` resource address. The managed resource remains
`kubernetes_manifest.this`, so simplifying the inputs does not move state.
