output "id" {
  description = "Argo CD Application namespace/name"
  value       = "${var.manifest.metadata.namespace}/${var.manifest.metadata.name}"
}

output "name" {
  description = "Argo CD Application name"
  value       = var.manifest.metadata.name
}

output "namespace" {
  description = "Namespace containing the Argo CD Application"
  value       = var.manifest.metadata.namespace
}

output "manifest" {
  description = "Rendered Argo CD Application manifest"
  value       = var.manifest
}
