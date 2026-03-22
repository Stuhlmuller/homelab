terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/nomad-csi-volume-registration?ref=0.2.0"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  # Volume identification
  volume_id   = "shared-data"
  name        = "Shared Application Data"
  plugin_id   = "nfs-csi"        # Adjust if your CSI plugin has a different ID
  external_id = "10.1.0.2:/data" # Change to your actual NFS export path

  # Access configuration - allows multiple nodes to read and write
  capabilities = [
    {
      access_mode     = "multi-node-multi-writer"
      attachment_mode = "file-system"
    }
  ]

  # NFS mount options
  mount_options = {
    fs_type = "nfs"
    mount_flags = [
      "vers=4.1",
      "noatime",
      "nodiratime"
    ]
  }

  # Keep volume registration when destroying Terraform resources
  deregister_on_destroy = false
}
