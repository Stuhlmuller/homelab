# Codex Cloud Tailnet Lock signer

A small standard-library Python API receives authenticated Tailscale events at
`https://codex-signer.tail67beb.ts.net/webhooks/tailscale`. The existing
Traefik Funnel exposes only that POST path, with a 64 KiB body limit and rate
limit. Health endpoints and the daemon socket are not public.

The receiver handles only `nodeNeedsSignature`. It verifies HMAC-SHA256 over
the original request bytes, resolves the event's `data.nodeID` with a dedicated
read-only device OAuth client, and requires:

- Exactly `tag:codex-cloud`, with no additional tags.
- An internal, ephemeral Linux device created within 25 hours, authorized and
  connected to the control plane, in this tailnet's DNS suffix.
- Valid node/rotation public keys, unchanged on a second device lookup.
- A running daemon in the expected tailnet, with Tailnet Lock enabled and its
  own key already in the trusted signing-key set.

Only the exact node public key is signed through the local daemon API. This
never wraps an auth key or adds the target as a trusted signer. Unrelated,
already-signed and permanently ineligible events are acknowledged without
signing. A permanent rejection skips only that event, preserving later
enrollments in the same delivery. The HTTP body-size limit bounds the input.
Connecting devices receive three checks one second apart; transient
failures return 503 for Tailscale retry. The 25-hour HMAC/creation window covers
Tailscale's hourly retries for 24 hours. Replays recheck current device policy
and skip an already-signed node; they cannot supply signing keys.

**Trust boundary:** the dedicated enrollment key/tag and authenticated event
identify the allowed class of devices. This is not independent OpenAI workload
attestation: a compromised Tailscale control plane could still misrepresent
Codex device metadata. Keep the auth key exclusively in Codex Cloud. Agent
network grants allow private ingress HTTPS/DNS and the operator's HTTPS proxy;
Kubernetes authorization remains separate. No LAN or raw Kubernetes API grant
is added.

## Provision and activate

The administrator-owned
[`tailscale-access` module](../../../../IaC/terragrunt-catalog/modules/tailscale-access/codex-signer.tf)
creates a single-use persistent signer enrollment key, a reusable ephemeral
Codex enrollment key, a device-reader OAuth client and the webhook. Provider
0.29.2 requires subscription `categoryTailnetManagement`; the API ignores every
other event type. It writes credentials directly to encrypted AWS SSM. No key
material is printed or committed.

The Codex resource provider uses an Owner/Admin Tailscale API key at
`~/.config/homelab/tailscale/codex-signer-owner-api-key` (regular file mode
0600, parent directory 0700). The existing operator OAuth client lacks webhook
write access and cannot create an OAuth client. Generate the shortest practical
API key in Tailscale's Keys console, save it privately, and remove/revoke it
after provisioning. Never paste it into chat or a repository. Changes to these provider-owned resources need another owner API key in this
slot; ordinary refreshes can use the existing read-capable OAuth credential.
The existing policy/CI provider continues to use its separate OAuth client.

Use the existing administrator saved-plan path in the
[Tailscale module runbook](../../../../IaC/terragrunt-catalog/modules/tailscale-access/README.md)
from clean current `main`. First inspect the complete private plan for drift.
For this enrollment rollout, plan with
`-target=aws_ssm_parameter.codex_signer` and a private `-out` path. This selects
the five credentials and their OAuth/webhook/key/ACL dependencies. Require
only nine creates and the expected ACL update, with no DNS, tailnet-settings,
existing-key replacement or deletion. Compare the live ACL to the starting
source before replacing the full policy; preserve unrelated edits. Review and
apply that saved plan, never the earlier broad plan. This unit is outside
workload CI. Applying the shared SSM unit
through protected CI grants External Secrets the four exact runtime parameter
names. Dispatch `terragrunt-apply.yml` on exact current `main` with
`argocd_app=codex-cloud-signer` to reconcile those grants and only this
Application. Its read-only preflight checks the existing `automation` namespace,
actual workload AppProject, ESO scope, platform health and dedicated local
volume before any writes. The cloud enrollment key is excluded from the reader
grant. Apply the
`platform-storage` desired state before the signer; the registration dependency
only orders Application creation, not runtime readiness.

The app is initially registered with automated sync disabled so missing
credentials do not start a broken workload. After the five SSM values, exact
reader grant, retained local PV, and images exist, enable automated sync in
`IaC/homelab/us-west-2/apps/codex-cloud-signer/stack.hcl` through the normal PR
path. Check the ExternalSecret and single StatefulSet pod. Its API stays
unready until the owner trusts the signer, but the daemon can enroll.

On an existing trusted device, bootstrap only the public Funnel proxy using
the fixed-target helper from current main:

```sh
python3 -I scripts/tailscale-ingress-sign.py --codex-funnel-only
python3 -I scripts/tailscale-ingress-sign.py --codex-funnel-only --execute
```

This signs the operator-managed Funnel proxy as a normal node. It does **not**
trust the API's daemon. Read the daemon's public identity:

```sh
kubectl -n automation exec codex-cloud-signer-0 -c tailscale -- \
  tailscale --socket=/run/tailscale/tailscaled.sock lock status
```

The owner must verify this identity and add its public Tailnet Lock key from
an existing trusted signing device. The service cannot promote itself. Then
`/readyz` becomes healthy. Use Tailscale's webhook test endpoint to verify
HMAC delivery; the signed `test` event returns 204 without signing anything.

Configure Codex's managed VPN with the ordinary `cloud-auth-key` from
`/homelab/tailscale/codex-cloud-signer/cloud-auth-key`, using a private
credential-management surface. Both enrollment keys expire after 90 days;
renew them through a reviewed provider replacement before expiry. A running
persistent tagged signer retains its identity after its enrollment key expires.

## State and recovery

`platform-storage` owns a retained 1 GiB local PV at
`acer:/var/lib/codex-cloud-signer`; this app owns its pre-bound retained PVC.
A narrow root init container prepares the volume's root directory owned by
65532 with mode 0700, then both steady containers run without root or added
capabilities. The API mounts only the daemon socket and its three credential
files. It cannot read the persisted private keys or the signer enrollment key.
The daemon mounts the enrollment key and entire state directory, including
`tka-profiles`. Keep one replica and retain this volume across restarts.
Both mounts use the volume directly: Talos kubelet `subPath` mounts can resolve
inside its overlay instead of the retained host directory.

There is no automatic off-node backup of this signing authority. Disk loss
requires another trusted device to revoke the lost signer and authorize a new
identity. Do not clone or restore a signing node alongside a running copy.
Rollback disables the API deployment through GitOps and revokes the signer
with an existing trusted node; retain the PVC for investigation. A source
revert alone does not revoke signatures or recover lost keys.

## Validation and functional acceptance

```sh
python3 -I scripts/ci/codex-cloud-signer-test.py
kubectl kustomize clusters/homelab/apps/codex-cloud-signer
kubectl kustomize clusters/homelab/platform/storage
```

Run the repository static/policy gates and protected PR checks. After rollout,
verify the deployed revision with `scripts/verify-gitops.py`, inspect the
ExternalSecret readiness and StatefulSet convergence, and start a **new real
Codex cloud task**. Require its dedicated-tag node to become signed, private
DNS/HTTPS to work, and unrelated nodes to remain unsigned. Repeat after a
signer pod restart, confirming the same public key. Real event payload,
enrollment flag timing and startup deadline compatibility require this live
test; fixtures alone do not prove them. Track delivery in
[task #1820](https://github.com/Stuhlmuller/homelab/issues/1820).
