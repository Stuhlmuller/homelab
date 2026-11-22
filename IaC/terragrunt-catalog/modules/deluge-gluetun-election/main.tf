variable "enabled" {
  description = "Create the Deluge failover election and publication resources."
  type        = bool
  default     = false
}

# Argo CD excludes Leases and EndpointSlices from discovery. Bootstrap these
# exact objects here so the in-pod leader can only read or update them.
resource "kubernetes_manifest" "lease" {
  count = var.enabled ? 1 : 0

  manifest = {
    apiVersion = "coordination.k8s.io/v1"
    kind       = "Lease"
    metadata = {
      name      = "deluge-gluetun"
      namespace = "media"
    }
    spec = {}
  }

  computed_fields = ["spec"]

  lifecycle {
    ignore_changes = [manifest.spec]
  }

  field_manager {
    name            = "terragrunt-deluge-election"
    force_conflicts = false
  }
}

resource "kubernetes_manifest" "active_endpoint" {
  count = var.enabled ? 1 : 0

  manifest = {
    apiVersion = "discovery.k8s.io/v1"
    kind       = "EndpointSlice"
    metadata = {
      name      = "deluge-gluetun"
      namespace = "media"
      labels = {
        "kubernetes.io/service-name"             = "deluge-gluetun"
        "endpointslice.kubernetes.io/managed-by" = "deluge-gluetun"
      }
    }

    addressType = "IPv4"
    ports = [{
      name     = "transit"
      port     = 51820
      protocol = "UDP"
    }]
    endpoints = []
  }

  computed_fields = ["endpoints"]

  lifecycle {
    ignore_changes = [manifest.endpoints]
  }

  field_manager {
    name            = "terragrunt-deluge-election"
    force_conflicts = false
  }
}
