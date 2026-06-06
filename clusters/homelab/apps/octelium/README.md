# Octelium Client Desired State

This app prepares a repo-owned Octelium client connector in the homelab.
Octelium is the replacement target for human app access. Tailscale remains the
temporary fallback for app routes until `scripts/octelium-e2e-check.sh` proves
the Octelium Cluster, service catalog, workload credential, connector, and
client tunnel are all working.

The deployed Kubernetes pieces are:

- `octelium-client` namespace with baseline Pod Security and Istio ambient
  enrollment.
- `octelium-client-auth`, an ExternalSecret sourced from
  `/homelab/octelium/client-auth-token`.
- The official Octelium client Helm chart, configured for rootless gVisor mode
  so it does not need `NET_ADMIN` or a privileged namespace.
- `octelium-demo`, a tiny in-cluster HTTP service that remains available as a
  harmless smoke-test target.
- `octelium-demo-allow-client`, a NetworkPolicy limiting demo ingress to the
  Octelium client pod once a policy-enforcing CNI exists.

The Octelium resource catalog for the external Octelium Cluster is
`docs/examples/octelium/homelab-services.yaml`. It defines:

- Octelium Namespace `homelab`.
- Policy `homelab-human-web-access`, which allows authenticated human client
  sessions to WEB Services in the namespace.
- Workload User `homelab-octelium-client`.
- WEB Services for Argo CD, Compass, Deluge, Grafana, Kiali, LiteLLM, n8n,
  OctoBot, OpenClaw, Policy Bot, Prowlarr, Radarr, Sonarr, and the demo.

`values.yaml` keeps the connector at `replicaCount: 0` until the Octelium
Cluster API, service catalog, and workload credential are verified. The
prepared `--scope` entries keep the workload credential constrained to the same
service names when the connector is activated.

## Activation And Cutover

Apply the external Octelium resources to the Octelium Cluster:

```sh
octeliumctl apply docs/examples/octelium/homelab-services.yaml
```

Create an authentication token credential for the workload user:

```sh
octeliumctl create cred --user homelab-octelium-client homelab-octelium-client
```

Store the printed token outside git:

```sh
aws ssm put-parameter \
  --region us-west-2 \
  --name /homelab/octelium/client-auth-token \
  --type SecureString \
  --overwrite \
  --value '<authentication-token>'
```

After the Octelium API is verified, change `replicaCount` to `1` in a follow-up
PR and let Argo CD sync `octelium`. The connector then serves each configured
Octelium Service from inside the homelab cluster.

Then run:

```sh
scripts/octelium-e2e-check.sh
```

Use separate contexts when the Octelium control plane is not the homelab
cluster:

```sh
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

Only remove the old Tailscale-backed app UI routes after this e2e gate passes.

## Bootstrap UI Access

Use `octelium.stinkyboi.com` as the Octelium Cluster domain. With this nested
domain, clients call `octelium-api.octelium.stinkyboi.com`, and the browser
portal may use `portal.octelium.stinkyboi.com`. The existing Istio
`*.stinkyboi.com` certificate covers `octelium.stinkyboi.com`; it also requests
`*.octelium.stinkyboi.com` because the one-level wildcard does not cover the API
hostname.

Before DNS or VPN access reaches the Octelium Cluster ingress, bootstrap
through a local port-forward:

```sh
kubectl -n octelium get svc
sudo kubectl -n octelium port-forward svc/<octelium-ingress-service> 443:443
```

Add temporary host entries on the bootstrap workstation:

```text
127.0.0.1 octelium.stinkyboi.com
127.0.0.1 portal.octelium.stinkyboi.com
127.0.0.1 octelium-api.octelium.stinkyboi.com
```

Then authenticate and apply the catalog while the port-forward is running:

```sh
octelium login --domain octelium.stinkyboi.com
octeliumctl apply docs/examples/octelium/homelab-services.yaml
octeliumctl create cred --user homelab-octelium-client homelab-octelium-client
```

Store the generated workload credential in SSM as shown above, sync the Argo CD
Application, and remove the temporary host entries after the VPN or real DNS
path works.

## Enterprise Package

Octelium Enterprise is tracked as the `octeliumee` package from
`https://github.com/octelium/octelium-ee`. The package installs into an
already running Octelium Cluster with `octops`; it is not synced by this Argo CD
Application and it does not replace the in-cluster client connector.

Current desired Enterprise package version:

```text
0.22.0
```

The Octelium Cluster domain is `octelium.stinkyboi.com`, so the client talks to
`octelium-api.octelium.stinkyboi.com`. Keep certificates valid for the existing
`*.stinkyboi.com` wildcard plus `*.octelium.stinkyboi.com`.

Install or upgrade it with the repo-owned wrapper:

```sh
scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0

scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0 \
  --upgrade
```

The operator host must have `octops` `v0.29.0` or later and kubeconfig access
to the Octelium Cluster. Keep any Enterprise license material outside git.

## Validation

Render before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
helm template octelium-client oci://ghcr.io/octelium/helm-charts/octelium \
  --version 0.3.0 \
  --namespace octelium-client \
  -f clusters/homelab/apps/octelium/values.yaml
scripts/octelium-enterprise-package.sh --help
scripts/octelium-e2e-check.sh --help
```

After activation with `replicaCount: 1`:

```sh
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,pod -l app.kubernetes.io/instance=octelium-client
kubectl -n octelium-client logs deploy/octelium-client
scripts/octelium-e2e-check.sh \
  --octelium-context <octelium-cluster-context> \
  --homelab-context <homelab-context>
```

From an Octelium client session, query one of the private service names:

```sh
octelium connect --domain octelium.stinkyboi.com -p grafana.homelab:18080
curl http://127.0.0.1:18080/api/health
```

Use the smoke-test service when you want to validate the bridge separately from
app-specific auth:

```sh
octelium connect --domain octelium.stinkyboi.com -p homelab-demo.homelab:18081
curl http://127.0.0.1:18081/version
```

## Adding A Service

1. Add the Octelium `Service` to
   `docs/examples/octelium/homelab-services.yaml`.
2. Add the service name to both `octelium.args` as a `--scope=...` entry and
   `octelium.serve` in `values.yaml`.
3. If the destination workload has an Istio `AuthorizationPolicy`, add
   `cluster.local/ns/octelium-client/sa/octelium-client` as an allowed source.
4. If the destination workload has a Kubernetes `NetworkPolicy`, add the
   `octelium-client` namespace as an ingress source. This is currently intent
   only while kube-flannel is the CNI.
5. Re-render the Octelium app and the changed destination app.

## Rollback

Set `replicaCount` back to `0` and sync the Argo CD Application. That stops the
connector without touching Tailscale.

To remove the external Octelium resources:

```sh
for service in \
  argocd.homelab compass.homelab deluge.homelab grafana.homelab \
  homelab-demo.homelab kiali.homelab litellm.homelab n8n.homelab \
  octobot.homelab openclaw.homelab policy-bot.homelab \
  prowlarr.homelab radarr.homelab sonarr.homelab; do
  octeliumctl delete svc "${service}"
done

octeliumctl delete user homelab-octelium-client
octeliumctl delete policy homelab-human-web-access
```

Do not delete or change Tailscale resources as part of Octelium rollback unless
a later migration PR explicitly replaces the tailnet ingress and exit-node
model.

Remove or downgrade the Enterprise package through an Octelium-supported
package operation. Update the desired package version in this README and the
knowledge-base runbook before running the wrapper again.
