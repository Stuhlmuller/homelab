mock_provider "kubernetes" {}

variables {
  kms_key_id = "alias/test"
  node_labels = {
    test-node = { "octelium.com/node-mode-dataplane" = "" }
  }
  node_annotations = {
    test-node = { "octelium.com/override-gw-ip" = "192.0.2.10" }
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
      kubernetes_labels.nodes["test-node"].labels == tomap(var.node_labels["test-node"]) &&
      kubernetes_annotations.nodes["test-node"].annotations == tomap(var.node_annotations["test-node"])
    )
    error_message = "Both the dataplane selector and gateway address must remain declared on the same node."
  }
}
