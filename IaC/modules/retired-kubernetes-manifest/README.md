# Retired Kubernetes Manifest

This module intentionally declares no Kubernetes resources.

Use it from an existing Terragrunt unit when a previously managed Kubernetes
manifest must be destroyed through the normal Terragrunt apply path before the
unit is removed from the repository. The provider and state encryption
configuration remain present so OpenTofu can read the existing state and plan
the deletion cleanly.
