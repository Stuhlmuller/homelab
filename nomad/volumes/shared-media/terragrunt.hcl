terraform {
  source = "git::https://github.com/Stuhlmuller/terragrunt-catalog.git//modules/nomad-csi-volume-registration?ref=0.2.0"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  # Volume identification
  volume_id   = "shared-media"
  name        = "Shared Media and Config"
  plugin_id   = "nfs-csi"         # Adjust if your CSI plugin has a different ID
  external_id = "10.1.0.2:/media" # Change to your actual NFS export path

  # Access configuration - allows multiple nodes to read (read-only)
  capabilities = [
    {
      access_mode     = "multi-node-reader-only"
      attachment_mode = "file-system"
    }
  ]

  # NFS mount options
  mount_options = {
    fs_type = "nfs"
    mount_flags = [
      "vers=4.1",
      "noatime",
      "nodiratime",
      "ro" # Read-only mount
    ]
  }

  # Keep volume registration when destroying Terraform resources
  deregister_on_destroy = false
}
