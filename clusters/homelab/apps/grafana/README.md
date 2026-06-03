# Grafana Monitoring Profile

Grafana is managed as an Argo CD multi-source Application. The Helm chart
installs Grafana, while this directory owns the safe runtime configuration that
should be reviewed in git.

## Microsoft Entra SSO

Grafana uses the built-in `auth.azuread` provider for SSO. The Helm values set
the public `root_url`, enable PKCE, and mount the `grafana-azuread-sso`
Kubernetes Secret at `/etc/secrets/grafana-azuread-sso`; `grafana.ini` reads
the OAuth client ID, client secret, authorization URL, token URL, and allowed
tenant from those files.

The Entra application registration is managed by
`IaC/live/azuread-applications/grafana` with the Terragrunt catalog
`azuread-application` module pinned to `0.4.0`. That unit registers these
redirect URIs:

- `https://grafana.stinkyboi.com/`
- `https://grafana.stinkyboi.com/login/azuread`

The same unit writes the `/homelab/grafana/azuread/*` SecureString parameters
consumed by the `grafana-azuread-sso` ExternalSecret. The client ID comes from
the managed Entra application, the client secret comes from the generated
one-year application password, and the tenant-specific authorization values
come from the active AzureAD client configuration.

Grafana maps the Entra app role value `GrafanaAdmin` to the Grafana `Admin`
role, maps `Editor` to `Editor`, and assigns `Viewer` when neither role is
present. Local admin login remains available through `grafana-admin`.

## Code-Owned Configuration

- `values.yaml` provisions the Prometheus and Alertmanager datasources with
  stable UIDs, provisions the GitHub Infinity datasource with the stable
  `github` UID, enables a `ServiceMonitor` for Grafana metrics, mounts
  dashboards, configures Microsoft Entra SSO, and provisions Grafana-managed
  alerting resources.
- The Helm release uses a `Recreate` deployment strategy because Grafana stores
  SQLite state on a single PVC. Avoid overlapping old and new pods against the
  same database during rollouts.
- The Deployment carries the Argo CD `Replace=true` sync option so Argo replaces
  the Deployment instead of server-side applying stale `rollingUpdate` fields
  when reconciling the `Recreate` strategy.
- Datasource provisioning deletes the old `Prometheus` and `Alertmanager`
  entries before recreating them with stable UIDs. This handles first-rollout
  databases that already contain Grafana-generated datasource UIDs.
- `dashboards/homelab-overview.json` is the default Homelab overview dashboard.
  `dashboards/argocd-overview.json` is the Argo CD GitOps operations
  dashboard. `dashboards/github-pr-status.json` tracks open pull request status
  filters and recent failed GitHub Actions runs. Kustomize packages these
  dashboards into the stable `grafana-dashboard-homelab-overview` ConfigMap,
  which the Helm chart mounts through the `homelab` dashboard provider.
- `values.yaml` imports pinned Grafana.com dashboard revisions for Kubernetes
  and Prometheus views that are maintained by the
  `dotdc/grafana-dashboards-kubernetes` project.
- `values.yaml` installs the pinned Infinity datasource plugin so Grafana can
  read public GitHub REST API endpoints from the server side. The GitHub
  queries are intentionally unauthenticated because this repository is public;
  keep the alert interval conservative unless a reviewed token-backed secret
  contract is added later.
- `externalsecret.yaml` references the Grafana admin username, admin password,
  Entra SSO values, and Discord webhook URL in AWS SSM Parameter Store. No
  secret values belong in this directory.
- `values.yaml` sets a non-secret
  `homelab.rst.io/discord-webhook-ssm-version` pod annotation. Bump this value
  to the SSM parameter version after rotating the Discord webhook so Argo CD
  rolls Grafana and file provisioning re-reads the webhook value.

## Imported Dashboards

The imported dashboards are pinned by dashboard ID and revision so dashboard
changes are reviewable. The Grafana chart downloads these JSON documents from
Grafana.com during pod startup, so first rollout depends on outbound HTTPS from
the cluster to Grafana.com.

| Folder | Dashboard | ID | Revision |
|--------|-----------|----|----------|
| Kubernetes | Kubernetes / Views / Global | 15757 | 43 |
| Kubernetes | Kubernetes / Views / Namespaces | 15758 | 46 |
| Kubernetes | Kubernetes / Views / Pods | 15760 | 39 |
| Kubernetes | Kubernetes / System / API Server | 15761 | 21 |
| Kubernetes | Kubernetes / System / CoreDNS | 15762 | 22 |
| Monitoring | Prometheus | 19105 | 9 |

The dotdc node dashboard is intentionally not imported while the
`kube-prometheus-stack` node-exporter subchart is disabled for this cluster's
current Pod Security baseline. Add it after node-exporter has a compatible,
documented path.

## Alerts

Grafana alert rules are provisioned from `values.yaml` and route to the
`homelab-alertmanager` contact point. That contact point fans out to the
in-cluster Prometheus Alertmanager, Discord, and OpenClaw. The Discord webhook
URL is read from the `grafana-discord-webhook` Kubernetes Secret. The OpenClaw
hook token is read from the `grafana-openclaw-alert-hook` Kubernetes Secret.
Both are managed by External Secrets from AWS SSM Parameter Store and refreshed
every five minutes.

The Alertmanager datasource is available for viewing Prometheus-managed alerts,
while Grafana-managed notifications stay controlled by the provisioned Grafana
policy. This makes alert rules and routing reviewable and repeatable without
putting notification credentials in git.

Grafana reads webhook credentials through environment variables while
provisioning alerting resources at startup. After replacing the Discord webhook
SSM value, update the `homelab.rst.io/discord-webhook-ssm-version` annotation
to the new SSM parameter version. After rotating the OpenClaw hook token,
update `homelab.rst.io/openclaw-alert-hook-ssm-version`. Either change lets
the GitOps rollout restart Grafana and reload the contact point.
For alerting-only provisioning changes that do not rotate credentials, bump
`homelab.rst.io/alerting-provisioning-version` so Grafana restarts and processes
rule additions, changes, and deletions.

The first provisioned rules cover:

- Prometheus scrape targets down for 10 minutes.
- Grafana metrics missing from Prometheus for 10 minutes.
- Kubernetes pod containers stuck in `CrashLoopBackOff` for 5 minutes.
- Deluge having no available Deployment replicas, or missing Deluge Deployment
  metrics, for 5 minutes.
- Homelab stateful PVC usage above 85 percent for 15 minutes.
- Argo CD application metrics missing from Prometheus for 10 minutes.
- Argo CD Applications not `Healthy` for 10 minutes.
- Argo CD Applications remaining explicitly `OutOfSync` for 30 minutes.
- GitHub Actions workflow runs in `failure` or `timed_out` state during the
  two-hour alert window.

The provisioning file also deletes the retired OctoBot-specific deployment
availability rule so Grafana only evaluates the generic workload alerts after
startup or an alerting provisioning reload.

The Argo CD application health and sync rules intentionally keep the original
`argocd_app_info` series labels instead of aggregating them. Grafana sends one
alert instance per affected application so notifications include the application
name, namespace, and current Argo CD status for triage.
The notification policy groups on those Argo CD labels as well as the shared
alert labels so Discord messages keep the affected application dimensions
visible instead of collapsing them into a folder-level aggregate.

## Validation

Render the raw Grafana resources:

```sh
kubectl kustomize clusters/homelab/apps/grafana
```

Render the pinned Helm chart with this values file:

```sh
helm template grafana grafana \
  --repo https://grafana.github.io/helm-charts \
  --version 10.5.15 \
  --namespace monitoring \
  --values clusters/homelab/apps/grafana/values.yaml
```

After Argo CD syncs, verify the monitoring wiring:

```sh
kubectl -n monitoring get servicemonitor grafana
kubectl -n monitoring get externalsecret grafana-admin
kubectl -n monitoring get externalsecret grafana-azuread-sso
kubectl -n monitoring get externalsecret grafana-discord-webhook
kubectl -n monitoring get externalsecret grafana-openclaw-alert-hook
kubectl -n monitoring get secret grafana-admin
kubectl -n monitoring get secret grafana-azuread-sso
kubectl -n monitoring get secret grafana-discord-webhook
kubectl -n monitoring get secret grafana-openclaw-alert-hook
kubectl -n monitoring get configmap grafana-dashboard-homelab-overview
kubectl -n monitoring get pods -l app.kubernetes.io/name=grafana
```

In Grafana, check that the `Prometheus` datasource is default, the
`Alertmanager` datasource is healthy, the `GitHub` datasource can query
`https://api.github.com`, the `Homelab Overview`, `Argo CD Overview`, and
`GitHub PR Status` dashboards appear under the `Homelab` folder, the imported
dashboards appear under the `Kubernetes` and `Monitoring` folders, the
`Entra ID` login path works, and the nine `homelab-*` alert rules are present
under Grafana Alerting. Use the Grafana contact point test action after the
Discord webhook parameter and OpenClaw hook token have been populated in SSM.

## Rollback

Revert the dashboard, alerting, or datasource changes in git and let Argo CD
sync the Application. Preserve the Grafana PVC unless the operator explicitly
accepts losing local UI preferences and historical Grafana state.
