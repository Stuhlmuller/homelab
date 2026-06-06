include "root" {
  path = find_in_parent_folders("root.hcl")
}

terraform {
  source = "../../modules/kubernetes-node-labels"
}

inputs = {
  node_labels = {
    zimaboard-0 = {
      "octelium.com/node-mode-dataplane" = ""
    }
    zimaboard-1 = {
      "octelium.com/node-mode-controlplane" = ""
    }
    zimaboard-2 = {
      "octelium.com/node-mode-dataplane" = ""
    }
  }
}
