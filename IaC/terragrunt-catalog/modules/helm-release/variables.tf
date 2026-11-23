variable "name" {
  description = "Helm release name. Helm limits release names to 53 characters"
  type        = string
}

variable "chart" {
  description = "Chart name, chart path, or absolute chart archive URL"
  type        = string
}

variable "namespace" {
  description = "Kubernetes namespace to install the release into"
  type        = string
  default     = "default"
}

variable "repository" {
  description = "Repository URL or repository name containing the chart"
  type        = string
  default     = null
}

variable "chart_version" {
  description = "Exact chart version to install. If omitted, Helm uses the latest matching version"
  type        = string
  default     = null
}

variable "atomic" {
  description = "Purge the release on install or upgrade failure"
  type        = bool
  default     = false
}

variable "cleanup_on_fail" {
  description = "Delete newly-created resources when an upgrade fails"
  type        = bool
  default     = false
}

variable "create_namespace" {
  description = "Create the namespace if it does not exist"
  type        = bool
  default     = false
}

variable "dependency_update" {
  description = "Run helm dependency update before installing the chart"
  type        = bool
  default     = false
}

variable "description" {
  description = "Custom release description"
  type        = string
  default     = null
}

variable "devel" {
  description = "Allow development chart versions"
  type        = bool
  default     = false
}

variable "disable_crd_hooks" {
  description = "Prevent CRD hooks from running"
  type        = bool
  default     = false
}

variable "disable_openapi_validation" {
  description = "Disable validation of rendered templates against the Kubernetes OpenAPI schema"
  type        = bool
  default     = false
}

variable "disable_webhooks" {
  description = "Prevent Helm hooks from running"
  type        = bool
  default     = false
}

variable "force_update" {
  description = "Force resource updates through delete and recreate if needed"
  type        = bool
  default     = false
}

variable "keyring" {
  description = "Public keyring location used when verify is true"
  type        = string
  default     = null
}

variable "lint" {
  description = "Run helm lint when planning"
  type        = bool
  default     = false
}

variable "max_history" {
  description = "Maximum release revisions to keep. Use 0 for no limit"
  type        = number
  default     = 0
}

variable "pass_credentials" {
  description = "Pass credentials to all domains"
  type        = bool
  default     = false
}

variable "recreate_pods" {
  description = "Perform pod restarts during upgrade or rollback"
  type        = bool
  default     = false
}

variable "render_subchart_notes" {
  description = "Render subchart notes along with parent chart notes"
  type        = bool
  default     = true
}

variable "replace" {
  description = "Reuse a release name even if that name is already used"
  type        = bool
  default     = false
}

variable "repository_ca_file" {
  description = "Repository CA file path"
  type        = string
  default     = null
}

variable "repository_cert_file" {
  description = "Repository client certificate file path"
  type        = string
  default     = null
}

variable "repository_key_file" {
  description = "Repository client key file path"
  type        = string
  default     = null
}

variable "repository_password" {
  description = "Repository password or token for HTTP basic authentication"
  type        = string
  default     = null
  sensitive   = true
}

variable "repository_username" {
  description = "Repository username for HTTP basic authentication"
  type        = string
  default     = null
}

variable "reset_values" {
  description = "Reset values to chart defaults when upgrading"
  type        = bool
  default     = false
}

variable "reuse_values" {
  description = "Reuse the previous release values and merge overrides during upgrade"
  type        = bool
  default     = false
}

variable "set" {
  description = "Scalar Helm values to merge into the chart"
  type = list(object({
    name  = string
    value = optional(string)
    type  = optional(string)
  }))
  default = []
}

variable "set_list" {
  description = "List Helm values to merge into the chart"
  type = list(object({
    name  = string
    value = list(string)
  }))
  default = []
}

variable "set_sensitive" {
  description = "Sensitive scalar Helm values to merge into the chart"
  type = list(object({
    name  = string
    value = string
    type  = optional(string)
  }))
  default   = []
  sensitive = true
}

variable "set_wo" {
  description = "Write-only Helm values for providers that support write-only inputs"
  type = list(object({
    name  = string
    value = optional(string)
    type  = optional(string)
  }))
  default   = []
  sensitive = true
}

variable "set_wo_revision" {
  description = "Revision number for write-only Helm values. Increment to force an update"
  type        = number
  default     = null
}

variable "skip_crds" {
  description = "Do not install CRDs from the chart"
  type        = bool
  default     = false
}

variable "take_ownership" {
  description = "Allow Helm to adopt existing resources not already marked as managed by the release"
  type        = bool
  default     = false
}

variable "timeout" {
  description = "Time in seconds to wait for each Kubernetes operation"
  type        = number
  default     = 300
}

variable "upgrade_install" {
  description = "Install the release during upgrade if a release not controlled by Terraform is present"
  type        = bool
  default     = false
}

variable "values" {
  description = "Raw YAML value documents to pass to Helm"
  type        = list(string)
  default     = []
}

variable "verify" {
  description = "Verify chart package signatures before installing"
  type        = bool
  default     = false
}

variable "wait" {
  description = "Wait until all resources are ready before marking the release successful"
  type        = bool
  default     = true
}

variable "wait_for_jobs" {
  description = "When wait is enabled, wait for Jobs to complete"
  type        = bool
  default     = false
}

variable "postrender" {
  description = "Helm post-render command configuration"
  type = object({
    binary_path = string
    args        = optional(list(string))
  })
  default = null
}
