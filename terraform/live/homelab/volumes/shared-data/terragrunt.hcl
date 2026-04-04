terraform {
  source = "../../../../modules/nomad_csi_volume_registration"
}

include "root" {
  path = find_in_parent_folders("root.hcl")
}

dependencies {
  paths = ["../../jobs/nfs-csi-plugin"]
}

inputs = {
  volume_id   = "shared-data"
  name        = "Shared Application Data"
  plugin_id   = "nfs-csi"
  external_id = "10.1.0.2:/data"

  context = {
    server = "10.1.0.2"
    share  = "/data"
  }

  capabilities = [
    {
      access_mode     = "multi-node-multi-writer"
      attachment_mode = "file-system"
    }
  ]

  mount_options = {
    fs_type     = "nfs"
    mount_flags = ["vers=4.1", "noatime", "nodiratime"]
  }

  deregister_on_destroy = false
}
