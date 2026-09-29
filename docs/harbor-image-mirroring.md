# Kubernetes images in Harbor

Talos/containerd redirects upstream image pulls to the normal Harbor `mirror`
project. Repository and Pod image names retain upstream provenance; their bytes
come from `harbor.stinkyboi.com/mirror/<upstream-registry>/<repository>`.
This covers Helm defaults, init containers, hooks, injected sidecars,
operator-created Pods, Kubernetes static Pods, pause, kubelet and etcd without
adding an admission webhook or rewriting controller-generated resources.

`scripts/config/harbor-images.json` is the reviewed, digest-pinned inventory.
It includes repository declarations, rendered Helm charts and the observed
cluster inventory. The initial inventory was captured on 2026-09-28 UTC.
Private custom NOFX artifacts remain in the private `homelab` project.
Only anonymously readable public upstream artifacts enter `mirror`; its
read access is public, including through the existing public Harbor hostname.
The separate `robot$mirror+publisher` can pull/push only within `mirror` and
uses its own generated `/homelab/harbor/mirror-robot-push-password`. Nodes need no new credentials.

The normal project retains copied artifacts independently of upstream tags or
deletion. It is deliberately not a proxy cache. The protected
`harbor-mirror.yml` workflow copies all platforms with digest preservation,
keeps a digest-named tag for each entry, maintains reviewed source-tag aliases,
and downloads every image anonymously into a fresh temporary directory.
Retries reuse an existing digest-named tag only after its manifest hash matches
the catalog; a missing tag is copied from upstream. Missing-content detection
accepts registry manifest/name-unknown errors and Harbor's exact expected
artifact or repository `not found` message. Generic 404 responses and messages
for another repository or digest tag still stop publication. Other lookup errors and
unexpected hashes stop publication. Source-tag aliases are copied from that
verified Harbor digest, avoiding a second upstream transfer. Every entry still
receives a complete anonymous download and alias verification on each run.
Harbor retains the existing scan-on-push policy and NFS registry storage.
No retention/delete job is introduced. Size NFS for the additional images and
retain registry blobs together with Harbor database/encryption-key backups.

## Delivery

1. Merge the bootstrap, inventory, publisher and unapplied Talos patches through
   normal signed-commit, review and CI gates. Apply the reviewed
   `IaC/live/aws-ssm-parameters` saved plan through the existing
   [Harbor rollout path](knowledge-base/operations/harbor-oci.md#rollout-and-acceptance),
   inspecting it for unrelated changes first. This creates the independent mirror
   publisher secret. Wait for Harbor secrets to reconcile and its PostSync
   bootstrap to finish Synced/Healthy before publication.
2. Run the protected copy workflow against exact reviewed current `main`:

   ```sh
   reviewed_sha=$(git rev-parse HEAD)
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha"
   ```

   Require a successful run, including complete anonymous downloads. A completed
   successful `main` dispatch on an ancestor is reusable only when its publication
   bundle is byte-identical to current reviewed `main`: `scripts/config/harbor-images.json`,
   `.github/workflows/harbor-mirror.yml`, `scripts/ci/harbor-publish.sh`,
   `scripts/ci/install-kubeconfig.sh`, `flake.nix`, and `flake.lock`.
   Missing commit history or blobs cannot establish that evidence. Probe or docs
   changes alone therefore do not require another full image copy. New workflow
   dispatches and credential access still require exact current `main`.
   A running Harbor UI or manifest request alone does not prove complete copies.
   Failed runs expose only the catalog source, operation phase, exit status and
   a fixed error category. Raw transport logs and credentials remain private.
3. From that clean checkout, render and strictly validate each existing machine
   configuration. The helper defaults to inspection; use Talos client 1.11.3.
   Restore the private client config at `.talos/talosconfig`, or pass an existing
   private file explicitly with `--talosconfig /path/to/private/talosconfig` on
   every command below. It never falls back to the user config or `TALOSCONFIG`;
   an absent selected file stops before any network call. Never commit this file.

   ```sh
   for node in 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199; do
     python3 -I scripts/talos-harbor-mirrors.py --node "$node"
   done
   ```

4. Apply one node at a time, workers first and the sole control plane last:

   ```sh
   python3 -I scripts/talos-harbor-mirrors.py --node 10.1.0.202 \
     --execute --expected-sha "$reviewed_sha"
   ```

   Repeat for `.201`, `.200`, then `.199` only after the preceding node passes.
   The helper requires successful publication of the same bundle, verifies destination
   manifests, preserves the full persistent machine configuration, allows only
   registry-mirror differences, validates with `--mode metal --strict`, and
   applies with `--mode no-reboot`. It checks configuration readback and node
   readiness/boot identity, then requests `registry.k8s.io/pause:3.10` through
   Talos's native `image pull --namespace system` using the selected client config.
   Rollback and dry-run do not pull images. It never drains, restarts or deletes workloads.
5. Verify every node's `registryconfigs` resource contains the committed
   endpoints and `skipFallback: true`. Correlate each native pause pull with
   Harbor manifest access logs from that node before claiming live migration.
   Talos skips an already pulled and unpacked reference entirely. Before the
   first apply, inspect `talosctl ... image list --namespace system` on each node
   and confirm `registry.k8s.io/pause:3.10` is absent. Repeat runs can return from
   cache without a registry request; require correlated Harbor manifest logs
   before claiming a fresh fetch. Do not delete cached images to force this test.
   Unchanged Pod image strings are not evidence of an upstream pull.

Talos 1.11.3 [kubelet](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/system/services/kubelet.go#L64-L74)
and [etcd](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/system/services/etcd.go#L88-L104)
use the CRI daemon's `system` namespace and the same registry builder as the
native image API. Both therefore consume `machine.registries.mirrors`; there is
no separate kubelet/etcd mirror configuration. The [image pull cache check](https://github.com/siderolabs/talos/blob/v1.11.3/internal/pkg/containers/image/image.go#L85-L99)
explains why the probe uses the initially uncached system-namespace reference.

The operator helper verifies destination manifests with curl using the fixed
`https://1.1.1.1/dns-query` DNS-over-HTTPS resolver. Workstation split DNS can
otherwise return the unreachable Istio ClusterIP. Requests retain the Harbor
hostname and TLS verification; no system DNS, hosts file, or environment override
is changed. Anonymous Bearer tokens stay in a private temporary header file and
are removed on exit. Every digest-named tag and source-tag alias must return the
catalog's exact manifest bytes after a successful copy workflow for the same
publication bundle. Rollout still requires a clean checkout of exact current `main`.

Talos host DNS currently reaches the existing public Harbor HTTPS route.
The registry and artifacts are hosted in the cluster, but node traffic still
traverses Cloudflare/Octelium. Pod-only CoreDNS split resolution does not change
host/containerd DNS. A private node-to-registry route is a separate networking
change; do not claim network isolation or air-gapped operation.

## Initial secret plan scope

The 2026-09-28 shared SSM plan also contained pending AI secret creation.
For this migration, plan only the new parameter and its declared dependencies:

```sh
cd IaC/live/aws-ssm-parameters
terragrunt plan \
  -target='aws_ssm_parameter.generated["/homelab/harbor/mirror-robot-push-password"]' \
  -out /path/to/private/mirror-secret.plan
terragrunt --log-disable show -json /path/to/private/mirror-secret.plan \
  > /path/to/private/mirror-secret.json
conftest test --policy ../../../policy /path/to/private/mirror-secret.json
```

Keep both files private. Review the saved plan before applying that exact plan
from clean reviewed `main`. The inspected plan creates only the Harbor SSM
parameter, with its independent password. Shared dependencies create 12 other
pending random values in encrypted state and add 14 already-declared AI secret
paths to the External Secrets reader policies; they do not create those SSM
parameters, rotate existing values, or delete resources. Those shared changes
require explicit operator approval; do not silently treat them as Harbor-only.
Reject any further change or replan/review if state advances. This is a one-time
scope limit, not the steady-state bootstrap command; normal full Terragrunt
apply still owns the whole declared stack.

## Updates and coverage

Add new image digests to the catalog in a prerequisite PR, publish/verify them,
then merge the consuming image or chart upgrade. Never combine first publication
and a new consuming reference in one rollout: Argo follows `main` immediately.
Run `scripts/harbor-image-inventory.py` and the coverage check when changing
charts, generated-image settings or Talos versions. Include live Pod images and
Talos system images; images created dynamically outside declared configuration
must be inventoried before use. Strict mirrors intentionally reject missing
artifacts instead of silently contacting upstream.

Resolve source digests anonymously with `skopeo inspect --raw --no-creds` and
hash the exact manifest bytes. For `tag@sha256` references pass `repo@sha256`
to Skopeo; it rejects combined tag/digest addresses. Preserve historical pinned
digests when a mutable tag has moved. Each repository/tag has one catalog alias;
additional old digests use digest-only sources. Never import private artifacts
into the public mirror project.

## Bootstrap and recovery

An in-cluster registry cannot cold-start from itself on empty nodes. Fresh
bootstrap uses upstream image names without the steady-state mirror patch.
Bring up networking, DNS, secret management, ingress, Harbor and its retained
storage, restore or republish the catalog, verify complete pulls, then enable
strict mirrors. Preserve upstream references and recovery material.

For an unavailable Harbor, the reviewed rollback patch restores direct upstream
endpoints without requiring Harbor or a successful publication run:

```sh
python3 -I scripts/talos-harbor-mirrors.py --node 10.1.0.202 --rollback
python3 -I scripts/talos-harbor-mirrors.py --node 10.1.0.202 --rollback \
  --execute --expected-sha "$reviewed_sha"
```

Rollback uses the same explicit `--talosconfig` selection (default
`.talos/talosconfig`), authenticates directly to Talos and verifies its boot identity; it
does not require Kubernetes API availability or a Ready node. Exact-main
verification still requires GitHub access. Apply only through this validated
repository-owned path. Retain mirrored blobs;
rollback changes image transport, not workload versions or stored data.

The [proposed recovery contract](harbor-mirror-recovery-contract.md) records
the GitHub/control-plane dependency, Talos 1.11.3 endpoint source evidence,
synthetic failure coverage and approval gates for a future offline path. It
does not change the commands above or establish live recovery capability.

Sources: [Talos 1.11 Harbor mirror configuration](https://docs.siderolabs.com/talos/v1.11/configure-your-talos-cluster/images-container-runtime/pull-through-cache),
[Harbor proxy-cache behavior and retention](https://goharbor.io/docs/2.14.0/administration/configure-proxy-cache/).
