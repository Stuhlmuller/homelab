include "root" {
  path = find_in_parent_folders("root.hcl")
}

include "kubernetes_provider" {
  path = find_in_parent_folders("kubernetes-provider.hcl")
}

terraform {
  source = "../../modules/kubernetes-node-labels"
}

inputs = {
  node_annotations = {
    # Octelium otherwise advertises the ISP-facing IPv6 address, which is not
    # reachable through the reviewed Tailscale 10.1.0.0/24 fallback route.
    zimaboard-0 = {
      "octelium.com/override-gw-ip" = "10.1.0.200"
    }
  }
  node_labels = {
    zimaboard-0 = {
      "octelium.com/node-mode-dataplane" = ""
    }
    zimaboard-1 = {
      "octelium.com/node-mode-controlplane" = ""
      "octelium.com/node-mode-cordium"      = ""
    }
    # Keep label ownership while removing dataplane eligibility: 1.28 GiB
    # allocatable cannot hold the measured 2.7 GiB retained Octelium fleet.
    zimaboard-2 = {}
  }
}
