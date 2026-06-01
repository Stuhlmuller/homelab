# Octelium Client Desired State

This app prepares a repo-owned Octelium client connector for the homelab while
leaving Tailscale in place as the current tailnet ingress and exit-node layer.

The deployed Kubernetes pieces are intentionally small:

- `octelium-client` namespace with baseline Pod Security labels.
- `octelium-client-auth` ExternalSecret, sourced from
  `/homelab/octelium/client-auth-token`.
- `octelium-demo`, a tiny in-cluster HTTP service that Octelium can serve as
  `homelab-demo.homelab`.
- `octelium-demo-allow-client`, a NetworkPolicy limiting demo ingress to the
  Octelium client pod.
- The official Octelium client Helm chart, configured for rootless gVisor mode
  so it does not need `NET_ADMIN` or a privileged namespace.

`values.yaml` keeps `replicaCount: 0` until a real Octelium Cluster, service
definition, and workload-user credential exist. This prevents a placeholder SSM
value from creating a crash-looping connector after Argo CD syncs the app.

## Activation

1. Apply the external Octelium resources from
   `docs/examples/octelium/homelab-demo.yaml` to the Octelium Cluster:

   ```sh
   octeliumctl apply docs/examples/octelium/homelab-demo.yaml
   ```

2. Create an authentication token credential for the workload user:

   ```sh
   octeliumctl create cred --user homelab-octelium-client homelab-octelium-client
   ```

3. Store the printed token outside git:

   ```sh
   aws ssm put-parameter \
     --region us-west-2 \
     --name /homelab/octelium/client-auth-token \
     --type SecureString \
     --overwrite \
     --value '<authentication-token>'
   ```

4. Change `replicaCount` to `1` in `values.yaml`, review the diff, and let Argo
   CD sync the app.

## Validation

Render before rollout:

```sh
kubectl kustomize clusters/homelab/apps/octelium
helm template octelium-client oci://ghcr.io/octelium/helm-charts/octelium \
  --version 0.3.0 \
  --namespace octelium-client \
  -f clusters/homelab/apps/octelium/values.yaml
```

After activation:

```sh
kubectl -n octelium-client get externalsecret,secret octelium-client-auth
kubectl -n octelium-client get deploy,svc,pod -l app.kubernetes.io/part-of=octelium
kubectl -n octelium-client logs deploy/octelium-client
```

The local demo should answer inside the cluster:

```sh
kubectl -n octelium-client port-forward svc/octelium-demo 8080:8080
curl http://127.0.0.1:8080/version
```

From an Octelium client session, publish the private demo service locally and
query it:

```sh
octelium connect --domain octelium.stinkyboi.com -p homelab-demo.homelab:18080
curl http://127.0.0.1:18080/version
```

## Rollback

Set `replicaCount` back to `0` and sync the Argo CD Application. That stops the
connector without touching Tailscale. If the demo is no longer needed, remove
the `homelab-demo.homelab` Service and `homelab-octelium-client` User from the
Octelium Cluster with `octeliumctl`.
