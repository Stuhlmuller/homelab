resource "kubernetes_namespace_v1" "openclaw_operator" {
  metadata {
    name = "openclaw-operator-system"
    labels = {
      "name" = "openclaw-operator-system"
    }
  }
}

resource "helm_release" "openclaw_operator" {
  name      = "openclaw-operator"
  chart     = "oci://ghcr.io/openclaw-rocks/charts/openclaw-operator"
  namespace = kubernetes_namespace_v1.openclaw_operator.metadata[0].name
  timeout   = "1500"

  # Optionally, you can add values for configuration
  # values = [
  #   yamlencode({
  #     # Add configuration here if needed
  #   })
  # ]
}
