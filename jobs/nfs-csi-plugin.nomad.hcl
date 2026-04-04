job "nfs-csi-plugin" {
  datacenters = ["homelab"]
  type        = "system"

  group "nodes" {
    task "plugin" {
      driver = "docker"

      config {
        image = "registry.k8s.io/sig-storage/nfsplugin:v4.9.0"

        args = [
          "--nodeid=${node.unique.id}",
          "--endpoint=unix://csi/csi.sock",
          "--v=5",
        ]

        privileged = true
      }

      csi_plugin {
        id        = "nfs-csi"
        type      = "monolith"
        mount_dir = "/csi"
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
