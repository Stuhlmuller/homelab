# Octelium Client Bridge

This repository now prepares Octelium as a parallel secure-access path without
removing Tailscale. Tailscale remains the active tailnet ingress and homelab
exit-node layer; Octelium is staged as a client connector and demo service that
can be enabled after an Octelium Cluster and workload credential exist.

## Current Model

The Argo CD Application at `IaC/live/argocd-apps/octelium` installs two source
types:

- The official Octelium client Helm chart from `ghcr.io/octelium/helm-charts`.
- Repo-owned Kubernetes support manifests from
  `clusters/homelab/apps/octelium`.

The Kubernetes namespace is `octelium-client`. It contains:

- `octelium-client-auth`, an ExternalSecret that reads
  `/homelab/octelium/client-auth-token`.
- `octelium-demo`, a small Podinfo HTTP service exposed only as a ClusterIP.
- `octelium-demo-allow-client`, a NetworkPolicy that allows only the Octelium
  client pod to call the demo service.
- A disabled-by-default Octelium client Deployment from the Helm chart.

`clusters/homelab/apps/octelium/values.yaml` keeps `replicaCount: 0` so Argo CD
can sync the app without crash-looping on a placeholder token. Once the external
Octelium Cluster is ready, changing `replicaCount` to `1` starts the connector.

The Octelium client is configured for `--implementation=gvisor`, so the
connector does not need `NET_ADMIN`, a TUN device, or privileged Pod Security.
That is slower than kernel WireGuard mode but is the safer first demo for this
cluster.

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

## Demo Resources

The Octelium Cluster resources for the demo live at:

```text
docs/examples/octelium/homelab-demo.yaml
```

They create:

- Octelium Namespace `homelab`.
- Workload User `homelab-octelium-client`.
- WEB Service `homelab-demo.homelab`, upstreaming to
  `http://octelium-demo.octelium-client.svc:8080` through that workload user.

Apply them to the Octelium Cluster:

```sh
octeliumctl apply docs/examples/octelium/homelab-demo.yaml
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

Then set `replicaCount: 1` in
`clusters/homelab/apps/octelium/values.yaml` and sync the `octelium` Argo CD
Application.

## Validation

Before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
helm template octelium-client oci://ghcr.io/octelium/helm-charts/octelium \
  --version 0.3.0 \
  --namespace octelium-client \
  -f clusters/homelab/apps/octelium/values.yaml
```

After Argo CD syncs the app:

```sh
kubectl -n octelium-client get externalsecret octelium-client-auth
kubectl -n octelium-client get deploy,svc,pod -l app.kubernetes.io/part-of=octelium
kubectl -n octelium-client logs deploy/octelium-client
```

Check the in-cluster demo locally:

```sh
kubectl -n octelium-client port-forward svc/octelium-demo 8080:8080
curl http://127.0.0.1:8080/version
```

Check it through Octelium from a client machine:

```sh
octelium connect --domain octelium.stinkyboi.com -p homelab-demo.homelab:18080
curl http://127.0.0.1:18080/version
```

## Rollback

Set `replicaCount` back to `0` and sync the `octelium` Argo CD Application.
That stops the connector while leaving Tailscale untouched.

If the external demo resources are no longer wanted:

```sh
octeliumctl delete svc homelab-demo.homelab
octeliumctl delete user homelab-octelium-client
```

Do not delete or change Tailscale resources as part of Octelium rollback unless
a later migration PR explicitly replaces the tailnet ingress and exit-node
model.
