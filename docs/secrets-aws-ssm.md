# AWS SSM Secret References

External Secrets uses AWS SSM Parameter Store for runtime secret material. This
repository may commit parameter names and Kubernetes Secret target names, but it
must not commit secret values.

## Placeholder Rules

- Parameter paths use the copyable public prefix `/homelab/<app>/<name>`.
- Values live only in AWS SSM Parameter Store or another approved runtime
  secret injection path.
- Placeholder manifests must identify the expected runtime secret and purpose.
- Provider credentials for External Secrets itself are an external prerequisite
  and are not created by this repository.

## Secret Reference Matrix

| App | ExternalSecret | Target Secret | SSM parameters |
|-----|----------------|---------------|----------------|
| external-secrets | external prerequisite | `aws-ssm-auth` | external prerequisite |
| tailscale | `tailscale-oauth` | `operator-oauth` | `/homelab/tailscale/oauth-client-id`, `/homelab/tailscale/oauth-client-secret` |
| grafana | `grafana-admin` | `grafana-admin` | `/homelab/grafana/admin-user`, `/homelab/grafana/admin-password` |
| deluge | `deluge-auth` | `deluge-auth` | `/homelab/deluge/web-password` |
| radarr | `radarr-auth` | `radarr-auth` | `/homelab/radarr/api-key`, `/homelab/radarr/deluge-api-key` |
| sonarr | `sonarr-auth` | `sonarr-auth` | `/homelab/sonarr/api-key`, `/homelab/sonarr/deluge-api-key` |
| litellm | `litellm-provider-keys` | `litellm-provider-keys` | `/homelab/litellm/master-key`, `/homelab/litellm/openai-api-key` |
| openclaw | `openclaw-secrets` | `openclaw-secrets` | `/homelab/openclaw/app-secret`, `/homelab/openclaw/litellm-token` |
| tines | `tines-secrets` | `tines-secrets` | `/homelab/tines/app-secret`, `/homelab/tines/admin-password` |

