# Talos Control-Plane Maintenance

This runbook owns repository-backed control-plane maintenance for Talos and
Kubernetes. It covers the current service-account issuer drift and the upgrade
checklist for Talos and Kubernetes patch releases.

Do not use this runbook to make ad hoc live changes. First express desired
state in this repository, validate the rendered Talos machine config, then
apply that reviewed config through the documented Talos path.

## Current Audit Findings

The parent audit reported:

- Live Kubernetes OIDC discovery issuer:
  `https://10.1.0.216:6443`.
- Canonical Kubernetes API endpoint:
  `https://10.1.0.199:6443`.
- Live node versions: Kubernetes `v1.34.1` and Talos `v1.11.3`.

Treat `10.1.0.216` as stale. It may still appear in live service-account issuer
discovery until the control-plane machine config is corrected and applied.

## Desired Service-Account Issuer State

The desired service-account issuer is the canonical Kubernetes API endpoint:

```text
https://10.1.0.199:6443
```

The repository-owned patch fragment lives at
`.talos/patches/controlplane-service-account-issuer.yaml` and sets:

```yaml
cluster:
  controlPlane:
    endpoint: https://10.1.0.199:6443
  apiServer:
    extraArgs:
      service-account-issuer: https://10.1.0.199:6443
```

This keeps the control-plane endpoint and Kubernetes service-account issuer
aligned. The kube-apiserver `service-account-issuer` value becomes the `iss`
claim in issued service-account tokens and drives service-account issuer
discovery. The rendered control-plane config must also keep `10.1.0.199` in
`cluster.apiServer.certSANs` so clients can verify the canonical endpoint.

## Render And Validate The Issuer Fix

This checkout does not currently contain `.talos/controlplane.yaml` or
`.talos/talosconfig`. Add or restore those files only through the established
secret-safe Talos config workflow. Do not commit Talos secrets, raw certificate
material, private keys, or kubeconfigs.

When `.talos/controlplane.yaml` is available locally, render a candidate config:

```sh
talosctl machineconfig patch .talos/controlplane.yaml \
  --patch @.talos/patches/controlplane-service-account-issuer.yaml \
  --output /private/tmp/controlplane-service-account-issuer.yaml
```

Validate before any live apply:

```sh
talosctl validate \
  --config /private/tmp/controlplane-service-account-issuer.yaml \
  --mode metal \
  --strict
```

Review the rendered config and confirm the only intended control-plane changes
are:

- `cluster.controlPlane.endpoint: https://10.1.0.199:6443`
- `cluster.apiServer.certSANs` includes `10.1.0.199`
- `cluster.apiServer.extraArgs.service-account-issuer:
  https://10.1.0.199:6443`

## Apply Sequence For Issuer Drift

Do not run these commands until the rendered config has passed validation and
the operator has explicitly approved the live Talos apply sequence.

1. Confirm API and Talos access are healthy with read-only commands:

   ```sh
   kubectl get nodes -o wide
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     get services
   ```

2. Apply the validated rendered config to the Acer control-plane node:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     apply-config \
     --file /private/tmp/controlplane-service-account-issuer.yaml
   ```

3. Watch the control plane recover:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     get services

   kubectl get nodes -o wide
   ```

4. Verify issuer discovery no longer reports `10.1.0.216`:

   ```sh
   kubectl get --raw /.well-known/openid-configuration
   ```

   Expected issuer:

   ```json
   {"issuer":"https://10.1.0.199:6443"}
   ```

5. Refresh local kubeconfig only after the API is healthy:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     kubeconfig ~/.kube/config --force

   kubectl config set-cluster homelab --server=https://10.1.0.199:6443
   ```

## Issuer Apply Risks

- A malformed control-plane config can interrupt the only control-plane node.
- If the rendered config accidentally changes cluster secrets, the node can
  lose trust with the existing cluster. Never regenerate secrets for this fix.
- If `certSANs` omits `10.1.0.199`, clients may fail TLS verification after the
  endpoint correction.
- Existing projected service-account tokens minted with the stale issuer may
  continue to exist until they rotate. Verify new discovery state first, then
  restart only workloads that prove they are still using stale projected tokens
  through their normal GitOps path.
- Do not use `talosctl patch machineconfig` or `talosctl edit machineconfig` as
  the durable fix. Those are acceptable only for emergency recovery when the
  final desired state is immediately backfilled into this repository.

## Talos And Kubernetes Upgrade Checklist

Use this checklist before changing Talos or Kubernetes versions. The observed
baseline from the parent audit is Talos `v1.11.3` and Kubernetes `v1.34.1`.

1. Refresh official release information:

   ```sh
   talosctl version
   kubectl version
   kubectl get nodes -o wide
   ```

   Then check the Talos support matrix, Talos release notes, and Kubernetes
   release notes for the selected target versions.

2. Choose targets:

   - For a Kubernetes patch upgrade within `1.34`, choose the latest supported
     `1.34.z` patch that is compatible with the installed Talos release.
   - For a Talos patch upgrade within `1.11`, choose the latest supported
     `1.11.z` installer image.
   - For a Talos minor upgrade, confirm Kubernetes compatibility and read every
     machine-config migration note before changing anything.

3. Validate repository state:

   ```sh
   nix flake check
   talosctl validate --config <rendered-control-plane-config> --mode metal --strict
   talosctl validate --config <rendered-worker-config> --mode metal --strict
   ```

4. Preflight live state with read-only commands:

   ```sh
   kubectl get nodes -o wide
   kubectl get pods -A
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 \
     get services
   ```

5. For a Kubernetes upgrade, run the Talos-managed Kubernetes upgrade from the
   control-plane node after reading the target release notes:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     upgrade-k8s --to <target-kubernetes-version>
   ```

   Verify every node reports the target Kubernetes version before considering
   the Kubernetes upgrade complete.

6. For a Talos upgrade, upgrade one node at a time, starting with workers:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes <node-ip> \
     upgrade --image ghcr.io/siderolabs/installer:<target-talos-version>
   ```

   Wait for the node to return `Ready` and for Talos services to become healthy
   before continuing to the next node. Upgrade the single control-plane node
   last.

7. Post-upgrade verification:

   ```sh
   kubectl get nodes -o wide
   kubectl get pods -A
   kubectl get --raw /.well-known/openid-configuration
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199,10.1.0.200,10.1.0.201,10.1.0.202 \
     get systemdisk
   ```

   Required results:

   - All nodes are `Ready`.
   - Kubernetes versions match the target.
   - The OIDC discovery issuer is `https://10.1.0.199:6443`.
   - Talos still reports the intended internal system disks.

## Upgrade Risks

- Talos OS upgrades do not automatically upgrade Kubernetes; plan and validate
  them as separate operations.
- A single control-plane cluster has no API-server redundancy. Schedule a
  maintenance window before upgrading or applying control-plane config.
- Skipping supported version paths can strand the node on an unsupported Talos
  or Kubernetes combination.
- Storage workloads depend on QNAP-backed NFS. Verify stateful applications and
  storage health after every node reboot.
- If a version change requires machine-config schema migration, commit the
  desired config update first, render it locally, and validate it before the
  live upgrade.
