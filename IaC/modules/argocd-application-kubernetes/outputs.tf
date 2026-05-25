output "id" {
  description = "Argo CD Application namespace/name"
  value       = "${local.metadata.namespace}/${local.metadata.name}"
}

output "name" {
  description = "Argo CD Application name"
  value       = local.metadata.name
}

output "namespace" {
  description = "Namespace containing the Argo CD Application"
  value       = local.metadata.namespace
}

output "manifest" {
  description = "Rendered Argo CD Application manifest"
  value       = local.manifest
}
