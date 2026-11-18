resource "kubernetes_labels" "nodes" {
  for_each = var.node_labels

  # Establish annotation ownership before this existing manager relinquishes it.
  depends_on = [kubernetes_annotations.nodes]

  api_version = "v1"
  kind        = "Node"
  labels      = each.value

  metadata {
    name = each.key
  }

  field_manager = "terragrunt"
  force         = true
}

resource "kubernetes_annotations" "nodes" {
  for_each = var.node_annotations

  api_version = "v1"
  kind        = "Node"
  annotations = each.value

  metadata {
    name = each.key
  }

  # Labels and annotations issue separate server-side apply requests per Node.
  field_manager = "terragrunt-node-annotations"
  force         = true
}

resource "kubernetes_node_taint" "nodes" {
  for_each = var.node_taints

  metadata {
    name = each.key
  }

  taint {
    key    = each.value.key
    value  = each.value.value
    effect = each.value.effect
  }

  field_manager = "terragrunt-node-taints"
  force         = false
}
