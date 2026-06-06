# Octelium Client Bridge

This repository runs Octelium as a parallel secure-access path without removing
Tailscale. Tailscale remains the active tailnet ingress and homelab exit-node
layer; Octelium runs as a client connector that serves selected in-cluster
services to an external Octelium Cluster.

## Current Model

The Argo CD Application at `IaC/live/argocd-apps/octelium` installs two source
types:

- The official Octelium client Helm chart from `ghcr.io/octelium/helm-charts`.
- Repo-owned Kubernetes support manifests from
  `clusters/homelab/apps/octelium`.

The Kubernetes namespace is `octelium-client`. It contains:

- `octelium-client-auth`, an ExternalSecret that reads
  `/homelab/octelium/client-auth-token`.
- `octelium-client`, the Helm-managed Octelium client Deployment.
- `octelium-demo`, a small Podinfo HTTP service exposed only as a ClusterIP.
- `octelium-demo-allow-client`, a NetworkPolicy that allows only the Octelium
  client pod to call the demo service once a policy-enforcing CNI exists.

The namespace is enrolled in Istio ambient mesh so protected apps can allow the
connector by service-account principal. The connector's principal is:

```text
cluster.local/ns/octelium-client/sa/octelium-client
```

The Octelium client is configured for `--implementation=gvisor`, so the
connector does not need `NET_ADMIN`, a TUN device, or privileged Pod Security.
That is slower than kernel WireGuard mode but is the safer default for this
cluster.

## Octelium Service Catalog

The external Octelium Cluster resources live at:

```text
docs/examples/octelium/homelab-services.yaml
```

They create:

- Octelium Namespace `homelab`.
- Policy `homelab-human-web-access`, allowing authenticated human client
  sessions to WEB Services in that namespace.
- Workload User `homelab-octelium-client`.
- WEB Services for the current homelab app routes:
  `argocd.homelab`, `compass.homelab`, `deluge.homelab`, `grafana.homelab`,
  `homelab-demo.homelab`, `kiali.homelab`, `litellm.homelab`, `n8n.homelab`,
  `octobot.homelab`, `openclaw.homelab`, `policy-bot.homelab`,
  `prowlarr.homelab`, `radarr.homelab`, and `sonarr.homelab`.

Each Service upstream points at the Kubernetes Service DNS name reachable from
inside this homelab cluster and is served by the workload user. The Kubernetes
Deployment serves the same explicit list through `octelium.serve`, and its
workload credential is constrained with matching `--scope` flags.

Apply the service catalog to the Octelium Cluster:

```sh
octeliumctl apply docs/examples/octelium/homelab-services.yaml
```

Create a workload authentication token:

```sh
octeliumctl create cred --user homelab-octelium-client homelab-octelium-client
```

Store the printed token in SSM, not git:

```sh
aws ssm put-parameter \
  --region us-west-2 \
  --name /homelab/octelium/client-auth-token \
  --type SecureString \
  --overwrite \
  --value '<authentication-token>'
```

## Bootstrap UI Access

The Octelium Cluster domain for this homelab is `octelium.stinkyboi.com`.
With that domain, Octelium clients contact
`octelium-api.octelium.stinkyboi.com`, and browser access may also use
`portal.octelium.stinkyboi.com`. The Istio wildcard certificate now requests
both `octelium.stinkyboi.com` and `*.octelium.stinkyboi.com` so the nested API
and portal names can present a valid certificate.

Until DNS or another private route reaches the Octelium Cluster ingress, use a
local port-forward as the bootstrap path:

```sh
kubectl -n octelium get svc
sudo kubectl -n octelium port-forward svc/<octelium-ingress-service> 443:443
```

For the bootstrap workstation only, point the Octelium Cluster names at the
local port-forward:

```text
127.0.0.1 octelium.stinkyboi.com
127.0.0.1 portal.octelium.stinkyboi.com
127.0.0.1 octelium-api.octelium.stinkyboi.com
```

Then authenticate and set up the cluster resources:

```sh
octelium login --domain octelium.stinkyboi.com
octeliumctl apply docs/examples/octelium/homelab-services.yaml
octeliumctl create cred --user homelab-octelium-client homelab-octelium-client
```

Keep the port-forward and temporary host entries in place until the first VPN
or other private access path is working. Remove the temporary host entries once
real DNS can resolve the same names to the Octelium ingress.

## Octelium Enterprise Package

Octelium Enterprise comes from
`https://github.com/octelium/octelium-ee` as the `octeliumee` Octelium package.
It is not a replacement for the Kubernetes client chart in this repository.
The package installs into an already running Octelium Cluster with `octops`,
while the homelab Kubernetes side remains the client connector and private
service bridge described above.

The current desired Enterprise package version for this homelab is `0.22.0`.
The upstream Enterprise README requires `octops` `v0.29.0` or later and an
existing Octelium Cluster. Commercial or production use requires an Enterprise
license; license material must stay outside git.

The configured Octelium Cluster domain is `octelium.stinkyboi.com`, which makes
the client use `octelium-api.octelium.stinkyboi.com`. The certificate must
cover both `octelium.stinkyboi.com` and `*.octelium.stinkyboi.com`; the existing
one-level `*.stinkyboi.com` wildcard is not enough for the API hostname.

Install the pinned package:

```sh
scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0
```

Upgrade an existing Enterprise installation after this repository has been
updated to the intended package version:

```sh
scripts/octelium-enterprise-package.sh \
  --domain octelium.stinkyboi.com \
  --version 0.22.0 \
  --upgrade
```

Use `--kubeconfig <path>` when the Octelium Cluster kubeconfig is not the
default kubeconfig for the operator shell.

## Why Not A Full Cluster Yet

Octelium's production install path for an existing Kubernetes cluster uses
`octops init`, labels data-plane and control-plane nodes, requires Multus CNI,
and needs PostgreSQL, Redis, public DNS, and a wildcard-capable TLS certificate.
Those are real platform decisions, not a small Helm app.

Before self-hosting the Octelium Cluster inside this homelab, add a separate
design PR that models:

- Multus installation and Talos CNI compatibility.
- Which workers are Octelium data-plane and control-plane nodes.
- PostgreSQL and Redis persistence, backup, and restore.
- Public DNS and TLS ownership for the Octelium Cluster domain.
- A repo-owned `octops init` or equivalent bootstrap workflow that does not rely
  on manual live mutation as steady state.

## Validation

Before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
helm template octelium-client oci://ghcr.io/octelium/helm-charts/octelium \
  --version 0.3.0 \
  --namespace octelium-client \
  -f clusters/homelab/apps/octelium/values.yaml
scripts/octelium-enterprise-package.sh --help
```

After Argo CD syncs the app:

```sh
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,pod -l app.kubernetes.io/instance=octelium-client
kubectl -n octelium-client logs deploy/octelium-client
```

Check the in-cluster demo locally:

```sh
kubectl -n octelium-client port-forward svc/octelium-demo 8080:8080
curl http://127.0.0.1:8080/version
```

Check a service through Octelium from a client machine:

```sh
octelium connect --domain octelium.stinkyboi.com -p grafana.homelab:18080
curl http://127.0.0.1:18080/api/health
```

## Rollback

Set `replicaCount` back to `0` and sync the `octelium` Argo CD Application.
That stops the connector while leaving Tailscale untouched.

If the external resources are no longer wanted, delete the homelab Services,
the `homelab-octelium-client` User, and the `homelab-human-web-access` Policy
from the Octelium Cluster with `octeliumctl`. Do not delete or change Tailscale
resources as part of Octelium rollback unless a later migration PR explicitly
replaces the tailnet ingress and exit-node model.

Remove or downgrade the Enterprise package through an Octelium-supported
package operation. Record the target package version in this document before
running the operator script again.
