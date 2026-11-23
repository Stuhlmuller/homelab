locals {
  shared = read_terragrunt_config(find_in_parent_folders("stack-defaults.hcl")).locals
  image  = "harbor.stinkyboi.com/mirror/docker.io/library/busybox"
}

inputs = {
  defaults     = local.shared.argocd_defaults
  dependencies = ["../../argocd-image-updater/argocd"]
  spec = {
    project = "homelab-workloads"
    destination = {
      namespace = "automation"
    }
    sources = [{
      repoURL        = local.shared.argocd_defaults.repo_url
      targetRevision = local.shared.argocd_defaults.target_revision
      path           = "${local.shared.argocd_defaults.source_root}/image-updater-busybox-canary"
      kustomize      = {}
    }]
  }
  image_update = {
    paused = true
    images = [{
      alias        = "busybox"
      image_name   = "${local.image}:issue-1846-canary"
      source_paths = ["clusters/homelab/apps/image-updater-busybox-canary/deployment.yaml"]
      kustomize    = { name = local.image }
    }]
  }
}
