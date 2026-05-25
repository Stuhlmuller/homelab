# Grafana Monitoring Profile

Grafana is managed as an Argo CD multi-source Application. The Helm chart
installs Grafana, while this directory owns the safe runtime configuration that
should be reviewed in git.

## Code-Owned Configuration

- `values.yaml` provisions the Prometheus and Alertmanager datasources with
  stable UIDs, enables a `ServiceMonitor` for Grafana metrics, mounts
  dashboards, and provisions Grafana-managed alerting resources.
- `dashboards/homelab-overview.json` is the default Homelab overview dashboard.
  Kustomize packages it into the stable
  `grafana-dashboard-homelab-overview` ConfigMap, which the Helm chart mounts
  through the `homelab` dashboard provider.
- `externalsecret.yaml` references the Grafana admin username and password in
  AWS SSM Parameter Store. No secret values belong in this directory.

## Alerts

Grafana alert rules are provisioned from `values.yaml` and route to the
in-cluster Prometheus Alertmanager contact point. The Alertmanager datasource is
available for viewing Prometheus-managed alerts, while Grafana-managed
notifications stay controlled by the provisioned Grafana policy. This makes
alert rules reviewable and repeatable, but it does not create any external
paging or chat receiver by itself. Add external notification credentials through
secret references only, then document the receiver contract here.

The first provisioned rules cover:

- Prometheus scrape targets down for 10 minutes.
- Grafana metrics missing from Prometheus for 10 minutes.
- Homelab stateful PVC usage above 85 percent for 15 minutes.

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
kubectl -n monitoring get configmap grafana-dashboard-homelab-overview
kubectl -n monitoring get pods -l app.kubernetes.io/name=grafana
```

In Grafana, check that the `Prometheus` datasource is default, the
`Alertmanager` datasource is healthy, the `Homelab Overview` dashboard appears
under the `Homelab` folder, and the three `homelab-*` alert rules are present
under Grafana Alerting.

## Rollback

Revert the dashboard, alerting, or datasource changes in git and let Argo CD
sync the Application. Preserve the Grafana PVC unless the operator explicitly
accepts losing local UI preferences and historical Grafana state.
