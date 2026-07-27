unit "bootstrap_argocd" {
  source                  = "./.catalog/units/bootstrap/argocd"
  path                    = "bootstrap/argocd"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_affine" {
  source                  = "./.catalog/units/live/argocd-apps/affine"
  path                    = "live/argocd-apps/affine"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_argocd_image_updater" {
  source                  = "./.catalog/units/live/argocd-apps/argocd-image-updater"
  path                    = "live/argocd-apps/argocd-image-updater"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_cert_manager" {
  source                  = "./.catalog/units/live/argocd-apps/cert-manager"
  path                    = "live/argocd-apps/cert-manager"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_compass" {
  source                  = "./.catalog/units/live/argocd-apps/compass"
  path                    = "live/argocd-apps/compass"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_cordium" {
  source                  = "./.catalog/units/live/argocd-apps/cordium"
  path                    = "live/argocd-apps/cordium"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_deluge" {
  source                  = "./.catalog/units/live/argocd-apps/deluge"
  path                    = "live/argocd-apps/deluge"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_descheduler" {
  source                  = "./.catalog/units/live/argocd-apps/descheduler"
  path                    = "live/argocd-apps/descheduler"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_dispatcharr" {
  source                  = "./.catalog/units/live/argocd-apps/dispatcharr"
  path                    = "live/argocd-apps/dispatcharr"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_external_secrets" {
  source                  = "./.catalog/units/live/argocd-apps/external-secrets"
  path                    = "live/argocd-apps/external-secrets"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_github_actions_runner" {
  source                  = "./.catalog/units/live/argocd-apps/github-actions-runner"
  path                    = "live/argocd-apps/github-actions-runner"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_grafana" {
  source                  = "./.catalog/units/live/argocd-apps/grafana"
  path                    = "live/argocd-apps/grafana"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_grafana_alert_cleanup" {
  source                  = "./.catalog/units/live/argocd-apps/grafana-alert-cleanup"
  path                    = "live/argocd-apps/grafana-alert-cleanup"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_istio" {
  source                  = "./.catalog/units/live/argocd-apps/istio"
  path                    = "live/argocd-apps/istio"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_kiali" {
  source                  = "./.catalog/units/live/argocd-apps/kiali"
  path                    = "live/argocd-apps/kiali"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_litellm" {
  source                  = "./.catalog/units/live/argocd-apps/litellm"
  path                    = "live/argocd-apps/litellm"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_media_postgres" {
  source                  = "./.catalog/units/live/argocd-apps/media-postgres"
  path                    = "live/argocd-apps/media-postgres"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_n8n" {
  source                  = "./.catalog/units/live/argocd-apps/n8n"
  path                    = "live/argocd-apps/n8n"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_n8n_postgres" {
  source                  = "./.catalog/units/live/argocd-apps/n8n-postgres"
  path                    = "live/argocd-apps/n8n-postgres"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_octelium" {
  source                  = "./.catalog/units/live/argocd-apps/octelium"
  path                    = "live/argocd-apps/octelium"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_octelium_cluster" {
  source                  = "./.catalog/units/live/argocd-apps/octelium-cluster"
  path                    = "live/argocd-apps/octelium-cluster"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_octelium_enterprise" {
  source                  = "./.catalog/units/live/argocd-apps/octelium-enterprise"
  path                    = "live/argocd-apps/octelium-enterprise"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_octelium_public" {
  source                  = "./.catalog/units/live/argocd-apps/octelium-public"
  path                    = "live/argocd-apps/octelium-public"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_octelium_storage" {
  source                  = "./.catalog/units/live/argocd-apps/octelium-storage"
  path                    = "live/argocd-apps/octelium-storage"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_octobot" {
  source                  = "./.catalog/units/live/argocd-apps/octobot"
  path                    = "live/argocd-apps/octobot"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_openclaw" {
  source                  = "./.catalog/units/live/argocd-apps/openclaw"
  path                    = "live/argocd-apps/openclaw"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_platform_dns" {
  source                  = "./.catalog/units/live/argocd-apps/platform-dns"
  path                    = "live/argocd-apps/platform-dns"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_platform_multus" {
  source                  = "./.catalog/units/live/argocd-apps/platform-multus"
  path                    = "live/argocd-apps/platform-multus"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_platform_storage" {
  source                  = "./.catalog/units/live/argocd-apps/platform-storage"
  path                    = "live/argocd-apps/platform-storage"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_policy_bot" {
  source                  = "./.catalog/units/live/argocd-apps/policy-bot"
  path                    = "live/argocd-apps/policy-bot"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_prometheus" {
  source                  = "./.catalog/units/live/argocd-apps/prometheus"
  path                    = "live/argocd-apps/prometheus"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_prowlarr" {
  source                  = "./.catalog/units/live/argocd-apps/prowlarr"
  path                    = "live/argocd-apps/prowlarr"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_radarr" {
  source                  = "./.catalog/units/live/argocd-apps/radarr"
  path                    = "live/argocd-apps/radarr"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_sonarr" {
  source                  = "./.catalog/units/live/argocd-apps/sonarr"
  path                    = "live/argocd-apps/sonarr"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_tailscale" {
  source                  = "./.catalog/units/live/argocd-apps/tailscale"
  path                    = "live/argocd-apps/tailscale"
  no_dot_terragrunt_stack = true
}

unit "aws_ssm_parameters" {
  source                  = "./.catalog/units/live/aws-ssm-parameters"
  path                    = "live/aws-ssm-parameters"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_grafana" {
  source                  = "./.catalog/units/live/azuread-applications/grafana"
  path                    = "live/azuread-applications/grafana"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_octelium" {
  source                  = "./.catalog/units/live/azuread-applications/octelium"
  path                    = "live/azuread-applications/octelium"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_node_labels" {
  source                  = "./.catalog/units/live/kubernetes-node-labels"
  path                    = "live/kubernetes-node-labels"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_secrets_external_secrets_aws_ssm_auth" {
  source                  = "./.catalog/units/live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  path                    = "live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  no_dot_terragrunt_stack = true
}

unit "operator_github_actions_role_policy" {
  source                  = "./.catalog/units/operator/github-actions-role-policy"
  path                    = "operator/github-actions-role-policy"
  no_dot_terragrunt_stack = true
}
