output "id" {
  description = "The release ID"
  value       = helm_release.this.id
}

output "name" {
  description = "The release name"
  value       = helm_release.this.name
}

output "namespace" {
  description = "The release namespace"
  value       = helm_release.this.namespace
}

output "chart" {
  description = "The chart used by the release"
  value       = helm_release.this.chart
}

output "version" {
  description = "The chart version used by the release"
  value       = helm_release.this.version
}

output "status" {
  description = "The release status"
  value       = helm_release.this.status
}

output "metadata" {
  description = "Helm release metadata"
  value       = helm_release.this.metadata
}

output "manifest" {
  description = "Rendered release manifest as JSON, when enabled by the provider"
  value       = helm_release.this.manifest
}

output "resources" {
  description = "Rendered release resources as JSON, when enabled by the provider"
  value       = helm_release.this.resources
}
