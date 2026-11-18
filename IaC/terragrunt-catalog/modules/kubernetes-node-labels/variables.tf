variable "node_labels" {
  description = "Map of node name to labels that should be managed by OpenTofu."
  type        = map(map(string))
}

variable "node_annotations" {
  description = "Map of node name to annotations that should be managed by OpenTofu."
  type        = map(map(string))
  default     = {}
}

variable "node_taints" {
  description = "Reviewed per-node taints managed without replacing unrelated node metadata."
  type = map(object({
    key    = string
    value  = string
    effect = string
  }))
  default = {}
}
