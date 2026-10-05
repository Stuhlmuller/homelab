# Explicit unit index. Application settings live in stacks/<app>/stack.hcl.
# Keep generated paths stable: they determine the existing remote-state keys.
unit "bootstrap_argocd" {
  source                  = "./.catalog/units/bootstrap/argocd"
  path                    = "bootstrap/argocd"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_affine" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/affine"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/affine/stack.hcl").inputs
}

unit "argocd_apps_argocd_image_updater" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/argocd-image-updater"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/argocd-image-updater/stack.hcl").inputs
}

unit "argocd_apps_bazarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/bazarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/bazarr/stack.hcl").inputs
}

unit "argocd_apps_cert_manager" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cert-manager"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/cert-manager/stack.hcl").inputs
}

unit "argocd_apps_compass" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/compass"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/compass/stack.hcl").inputs
}

unit "argocd_apps_cordium" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cordium"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/cordium/stack.hcl").inputs
}

unit "argocd_apps_deluge" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/deluge"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/deluge/stack.hcl").inputs
}

unit "argocd_apps_descheduler" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/descheduler"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/descheduler/stack.hcl").inputs
}

unit "argocd_apps_dispatcharr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/dispatcharr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/dispatcharr/stack.hcl").inputs
}

unit "argocd_apps_external_secrets" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/external-secrets"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/external-secrets/stack.hcl").inputs
}

unit "argocd_apps_fleet" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/fleet"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/fleet/stack.hcl").inputs
}

unit "argocd_apps_github_actions_runner" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/github-actions-runner"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/github-actions-runner/stack.hcl").inputs
}

unit "argocd_apps_grafana" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/grafana/stack.hcl").inputs
}

unit "argocd_apps_grafana_alert_cleanup" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana-alert-cleanup"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/grafana-alert-cleanup/stack.hcl").inputs
}

unit "argocd_apps_istio" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/istio"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/istio/stack.hcl").inputs
}

unit "argocd_apps_harbor" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/harbor"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/harbor/stack.hcl").inputs
}

unit "argocd_apps_kiali" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/kiali"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/kiali/stack.hcl").inputs
}

unit "argocd_apps_litellm" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/litellm"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/litellm/stack.hcl").inputs
}

unit "argocd_apps_langfuse" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/langfuse"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/langfuse/stack.hcl").inputs
}

unit "argocd_apps_media_postgres" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/media-postgres"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/media-postgres/stack.hcl").inputs
}

unit "argocd_apps_metrics_server" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/metrics-server"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/metrics-server/stack.hcl").inputs
}

unit "argocd_apps_multica" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/multica"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/multica/stack.hcl").inputs
}

unit "argocd_apps_nofx" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/nofx"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/nofx/stack.hcl").inputs
}

unit "argocd_apps_n8n" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/n8n/stack.hcl").inputs
}

unit "argocd_apps_n8n_postgres" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n-postgres"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/n8n-postgres/stack.hcl").inputs
}

unit "argocd_apps_octelium" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/octelium/stack.hcl").inputs
}

unit "argocd_apps_octelium_cluster" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-cluster"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/octelium-cluster/stack.hcl").inputs
}

unit "argocd_apps_octelium_enterprise" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-enterprise"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/octelium-enterprise/stack.hcl").inputs
}

unit "argocd_apps_octelium_public" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-public"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/octelium-public/stack.hcl").inputs
}

unit "argocd_apps_octelium_storage" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-storage"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/octelium-storage/stack.hcl").inputs
}

unit "argocd_apps_octobot" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octobot"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/octobot/stack.hcl").inputs
}

unit "argocd_apps_openclaw" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/openclaw"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/openclaw/stack.hcl").inputs
}

unit "argocd_apps_platform_crossplane" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-crossplane"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/platform-crossplane/stack.hcl").inputs
}

unit "argocd_apps_platform_dns" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-dns"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/platform-dns/stack.hcl").inputs
}

unit "argocd_apps_platform_multus" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-multus"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/platform-multus/stack.hcl").inputs
}

unit "argocd_apps_platform_storage" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-storage"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/platform-storage/stack.hcl").inputs
}

unit "argocd_apps_policy_bot" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/policy-bot"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/policy-bot/stack.hcl").inputs
}

unit "argocd_apps_prometheus" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prometheus"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/prometheus/stack.hcl").inputs
}

unit "argocd_apps_prowlarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prowlarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/prowlarr/stack.hcl").inputs
}

unit "argocd_apps_radarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/radarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/radarr/stack.hcl").inputs
}

unit "argocd_apps_sonarr" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/sonarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/sonarr/stack.hcl").inputs
}

unit "argocd_apps_tailscale" {
  source                  = "./.catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/tailscale"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/tailscale/stack.hcl").inputs
}

unit "argocd_apps_wazuh" {
  # Preserve the encrypted state address while the scoped retirement is applied.
  source                  = "./.catalog/units/live/retired-argocd-app"
  path                    = "live/argocd-apps/wazuh"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/stacks/wazuh/stack.hcl").inputs
}

unit "aws_ssm_parameters" {
  source                  = "./.catalog/units/live/aws-ssm-parameters"
  path                    = "live/aws-ssm-parameters"
  no_dot_terragrunt_stack = true
}

unit "langfuse_blob_storage" {
  source                  = "./.catalog/units/live/langfuse-blob-storage"
  path                    = "live/langfuse-blob-storage"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_fleet" {
  source                  = "./.catalog/units/live/azuread-applications/fleet"
  path                    = "live/azuread-applications/fleet"
  no_dot_terragrunt_stack = true
}

# A cloud-only device user; placed here to use the existing AzureAD CI scope.
unit "azuread_fleet_pilot_user" {
  source                  = "./.catalog/units/live/azuread-applications/fleet-pilot-user"
  path                    = "live/azuread-applications/fleet-pilot-user"
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

unit "operator_state_bucket_encryption" {
  source                  = "./.catalog/units/operator/state-bucket-encryption"
  path                    = "operator/state-bucket-encryption"
  no_dot_terragrunt_stack = true
}

unit "operator_legacy_kms_retirement" {
  source                  = "./.catalog/units/operator/legacy-kms-retirement"
  path                    = "operator/legacy-kms-retirement"
  no_dot_terragrunt_stack = true
}

unit "operator_etcd_backup_storage" {
  source                  = "./.catalog/units/operator/etcd-backup-storage"
  path                    = "operator/etcd-backup-storage"
  no_dot_terragrunt_stack = true
}

unit "operator_azuread_ci_identities" {
  source                  = "./.catalog/units/operator/azuread-ci-identities"
  path                    = "operator/azuread-ci-identities"
  no_dot_terragrunt_stack = true
}

# Read and verify a non-default managed Entra domain before creating the one
# scoped cloud-only Mac pilot. These operator units never modify Google users.
unit "operator_entra_stuhlmuller_domain" {
  source                  = "./.catalog/units/operator/entra-stuhlmuller-domain"
  path                    = "operator/entra-stuhlmuller-domain"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_stuhlmuller_pilot_user" {
  source                  = "./.catalog/units/operator/entra-stuhlmuller-pilot-user"
  path                    = "operator/entra-stuhlmuller-pilot-user"
  no_dot_terragrunt_stack = true
}
