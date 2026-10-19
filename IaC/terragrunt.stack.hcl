# Explicit unit index. Application settings live in <app>/stack.hcl.
# Keep generated paths stable: they determine the existing remote-state keys.
unit "bootstrap_argocd" {
  source                  = "./terragrunt-catalog/units/bootstrap/argocd"
  path                    = "bootstrap/argocd"
  no_dot_terragrunt_stack = true
}

unit "argocd_apps_affine" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/affine"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/affine/stack.hcl").inputs
}

unit "argocd_apps_mastodon" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/mastodon"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/mastodon/stack.hcl").inputs
}

unit "argocd_apps_bazarr" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/bazarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/bazarr/stack.hcl").inputs
}

unit "argocd_apps_cert_manager" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cert-manager"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/cert-manager/stack.hcl").inputs
}

unit "argocd_apps_compass" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/compass"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/compass/stack.hcl").inputs
}

unit "argocd_apps_cordium" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/cordium"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/cordium/stack.hcl").inputs
}

unit "argocd_apps_deluge" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/deluge"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/deluge/stack.hcl").inputs
}

unit "argocd_apps_descheduler" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/descheduler"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/descheduler/stack.hcl").inputs
}

unit "argocd_apps_dispatcharr" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/dispatcharr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/dispatcharr/stack.hcl").inputs
}

unit "argocd_apps_external_secrets" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/external-secrets"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/external-secrets/stack.hcl").inputs
}

unit "argocd_apps_fleet" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/fleet"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/fleet/stack.hcl").inputs
}

unit "argocd_apps_grafana" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/grafana"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/grafana/stack.hcl").inputs
}

unit "argocd_apps_istio" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/istio"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/istio/stack.hcl").inputs
}

unit "argocd_apps_harbor" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/harbor"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/harbor/stack.hcl").inputs
}

unit "argocd_apps_kiali" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/kiali"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/kiali/stack.hcl").inputs
}

unit "argocd_apps_litellm" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/litellm"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/litellm/stack.hcl").inputs
}

unit "argocd_apps_langfuse" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/langfuse"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/langfuse/stack.hcl").inputs
}

unit "argocd_apps_media_postgres" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/media-postgres"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/media-postgres/stack.hcl").inputs
}

unit "argocd_apps_metrics_server" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/metrics-server"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/metrics-server/stack.hcl").inputs
}

unit "argocd_apps_multica" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/multica"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/multica/stack.hcl").inputs
}

unit "argocd_apps_nix_builder" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/nix-builder"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/nix-builder/stack.hcl").inputs
}

unit "argocd_apps_nofx" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/nofx"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/nofx/stack.hcl").inputs
}

unit "argocd_apps_n8n" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/n8n/stack.hcl").inputs
}

unit "argocd_apps_n8n_postgres" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/n8n-postgres"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/n8n-postgres/stack.hcl").inputs
}

unit "argocd_apps_octelium" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/octelium/stack.hcl").inputs
}

unit "argocd_apps_octelium_cluster" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-cluster"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/octelium-cluster/stack.hcl").inputs
}

unit "argocd_apps_octelium_enterprise" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-enterprise"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/octelium-enterprise/stack.hcl").inputs
}

unit "argocd_apps_octelium_public" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-public"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/octelium-public/stack.hcl").inputs
}

unit "argocd_apps_octelium_storage" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/octelium-storage"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/octelium-storage/stack.hcl").inputs
}

unit "argocd_apps_openclaw" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/openclaw"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/openclaw/stack.hcl").inputs
}

unit "argocd_apps_platform_crossplane" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-crossplane"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-crossplane/stack.hcl").inputs
}

unit "argocd_apps_platform_dns" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-dns"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-dns/stack.hcl").inputs
}

unit "argocd_apps_platform_envoy_gateway" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-envoy-gateway"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-envoy-gateway/stack.hcl").inputs
}

unit "argocd_apps_platform_image_policy" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-image-policy"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-image-policy/stack.hcl").inputs
}

unit "argocd_apps_platform_multus" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-multus"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-multus/stack.hcl").inputs
}

unit "argocd_apps_platform_network_policy" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-network-policy"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-network-policy/stack.hcl").inputs
}

unit "argocd_apps_platform_network_policy_canary" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-network-policy-canary"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-network-policy-canary/stack.hcl").inputs
}

unit "argocd_apps_platform_network_policy_cleanup" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-network-policy-cleanup"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-network-policy-cleanup/stack.hcl").inputs
}

unit "argocd_apps_platform_storage" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/platform-storage"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/platform-storage/stack.hcl").inputs
}

unit "argocd_apps_policy_bot" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/policy-bot"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/policy-bot/stack.hcl").inputs
}

unit "argocd_apps_prometheus" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prometheus"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/prometheus/stack.hcl").inputs
}

unit "argocd_apps_prowlarr" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/prowlarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/prowlarr/stack.hcl").inputs
}

unit "argocd_apps_renovate" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/renovate"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/renovate/stack.hcl").inputs
}

unit "argocd_apps_radarr" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/radarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/radarr/stack.hcl").inputs
}

unit "argocd_apps_sonarr" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/sonarr"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/sonarr/stack.hcl").inputs
}

unit "argocd_apps_tailscale" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/tailscale"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/tailscale/stack.hcl").inputs
}

unit "argocd_apps_tailnet_dns" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/tailnet-dns"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/tailnet-dns/stack.hcl").inputs
}

unit "argocd_apps_traefik" {
  source                  = "./terragrunt-catalog/units/live/argocd-app"
  path                    = "live/argocd-apps/traefik"
  no_dot_terragrunt_stack = true

  values = read_terragrunt_config("${get_terragrunt_dir()}/traefik/stack.hcl").inputs
}

unit "aws_ssm_parameters" {
  source                  = "./terragrunt-catalog/units/live/aws-ssm-parameters"
  path                    = "live/aws-ssm-parameters"
  no_dot_terragrunt_stack = true
}

unit "langfuse_blob_storage" {
  source                  = "./terragrunt-catalog/units/live/langfuse-blob-storage"
  path                    = "live/langfuse-blob-storage"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_fleet" {
  source                  = "./terragrunt-catalog/units/live/azuread-applications/fleet"
  path                    = "live/azuread-applications/fleet"
  no_dot_terragrunt_stack = true
}

# A cloud-only device user; placed here to use the existing AzureAD CI scope.
unit "azuread_fleet_pilot_user" {
  source                  = "./terragrunt-catalog/units/live/azuread-applications/fleet-pilot-user"
  path                    = "live/azuread-applications/fleet-pilot-user"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_grafana" {
  source                  = "./terragrunt-catalog/units/live/azuread-applications/grafana"
  path                    = "live/azuread-applications/grafana"
  no_dot_terragrunt_stack = true
}

unit "azuread_applications_octelium" {
  source                  = "./terragrunt-catalog/units/live/azuread-applications/octelium"
  path                    = "live/azuread-applications/octelium"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_node_labels" {
  source                  = "./terragrunt-catalog/units/live/kubernetes-node-labels"
  path                    = "live/kubernetes-node-labels"
  no_dot_terragrunt_stack = true
}

unit "kubernetes_secrets_external_secrets_aws_ssm_auth" {
  source                  = "./terragrunt-catalog/units/live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  path                    = "live/kubernetes-secrets/external-secrets-aws-ssm-auth"
  no_dot_terragrunt_stack = true
}

unit "operator_github_actions_role_policy" {
  source                  = "./terragrunt-catalog/units/operator/github-actions-role-policy"
  path                    = "operator/github-actions-role-policy"
  no_dot_terragrunt_stack = true
}

unit "operator_state_bucket_encryption" {
  source                  = "./terragrunt-catalog/units/operator/state-bucket-encryption"
  path                    = "operator/state-bucket-encryption"
  no_dot_terragrunt_stack = true
}

unit "operator_etcd_backup_storage" {
  source                  = "./terragrunt-catalog/units/operator/etcd-backup-storage"
  path                    = "operator/etcd-backup-storage"
  no_dot_terragrunt_stack = true
}

unit "operator_application_backup_storage" {
  source                  = "./terragrunt-catalog/units/operator/application-backup-storage"
  path                    = "operator/application-backup-storage"
  no_dot_terragrunt_stack = true
}

unit "operator_azuread_ci_identities" {
  source                  = "./terragrunt-catalog/units/operator/azuread-ci-identities"
  path                    = "operator/azuread-ci-identities"
  no_dot_terragrunt_stack = true
}

# Read and verify a non-default managed Entra domain before creating the one
# scoped cloud-only Mac pilot. These operator units never modify Google users.
unit "operator_entra_stuhlmuller_domain" {
  source                  = "./terragrunt-catalog/units/operator/entra-stuhlmuller-domain"
  path                    = "operator/entra-stuhlmuller-domain"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_stuhlmuller_pilot_user" {
  source                  = "./terragrunt-catalog/units/operator/entra-stuhlmuller-pilot-user"
  path                    = "operator/entra-stuhlmuller-pilot-user"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_google_workspace_federation" {
  source                  = "./terragrunt-catalog/units/operator/entra-google-workspace-federation"
  path                    = "operator/entra-google-workspace-federation"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_emergency_global_admin" {
  source                  = "./terragrunt-catalog/units/operator/entra-emergency-global-admin"
  path                    = "operator/entra-emergency-global-admin"
  no_dot_terragrunt_stack = true
}

unit "operator_entra_owner_mail" {
  source                  = "./terragrunt-catalog/units/operator/entra-owner-mail"
  path                    = "operator/entra-owner-mail"
  no_dot_terragrunt_stack = true
}

unit "operator_tailscale_access" {
  source                  = "./terragrunt-catalog/units/operator/tailscale-access"
  path                    = "operator/tailscale-access"
  no_dot_terragrunt_stack = true
}
