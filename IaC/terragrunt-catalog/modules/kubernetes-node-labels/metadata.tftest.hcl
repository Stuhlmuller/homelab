mock_provider "kubernetes" {}

variables {
  kms_key_id = "alias/test"
  node_labels = {
    test-node = { "octelium.com/node-mode-dataplane" = "" }
  }
  node_annotations = {
    test-node = { "octelium.com/override-gw-ip" = "192.0.2.10" }
  }
  node_taints = {
    test-node = {
      key    = "homelab.stinkyboi.com/network-policy-canary"
      value  = "true"
      effect = "NoSchedule"
    }
  }
}

run "independent_node_metadata_ownership" {
  command = plan

  assert {
    condition = (
      kubernetes_labels.nodes["test-node"].field_manager == "terragrunt" &&
      kubernetes_annotations.nodes["test-node"].field_manager != kubernetes_labels.nodes["test-node"].field_manager
    )
    error_message = "Separate metadata apply requests must use distinct managers while retaining existing label ownership."
  }

  assert {
    condition = (
      kubernetes_node_taint.nodes["test-node"].field_manager == "terragrunt-node-taints" &&
      kubernetes_node_taint.nodes["test-node"].force == false &&
      kubernetes_node_taint.nodes["test-node"].taint[0].key == var.node_taints["test-node"].key &&
      kubernetes_node_taint.nodes["test-node"].taint[0].effect == "NoSchedule"
    )
    error_message = "The canary taint must use a separate non-forcing metadata owner."
  }

  assert {
    condition = (
      kubernetes_labels.nodes["test-node"].labels == tomap(var.node_labels["test-node"]) &&
      kubernetes_annotations.nodes["test-node"].annotations == tomap(var.node_annotations["test-node"])
    )
    error_message = "Both the dataplane selector and gateway address must remain declared on the same node."
  }
}
