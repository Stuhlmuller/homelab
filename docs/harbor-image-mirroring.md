# Kubernetes images in Harbor

<!-- markdownlint-configure-file { "MD013": false } -->

## Chainguard source provenance

Known Chainguard repositories are imported into the private Harbor destination
by exact repository and stable tag. The public Chainguard rules are enabled; their
copies become deployment-eligible only after the release recipe verifies the
source/index digest, required platform children, and complete consumer pulls.
Successful copies retain their immutable `sha256-<hex>` tag and may advance
`verified-stable`; failed, partial, or inaccessible copies never advance the
alias and are retained for diagnosis. Existing upstream-origin digests remain
available for cold bootstrap and rollback.

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
uses its own generated `/homelab/harbor/mirror-robot-push-password`. Nodes need
no new credentials.

The normal project retains copied artifacts independently of upstream tags or
deletion. It is deliberately not a proxy cache. The protected
`harbor-mirror.yml` workflow copies all platforms with digest preservation,
keeps a digest-named tag for each entry, maintains reviewed source-tag aliases,
and downloads every image anonymously into a fresh temporary directory.
Retries reuse an existing digest-named tag only after its manifest hash matches
the catalog; a missing tag is copied from upstream. Missing-content detection
accepts registry manifest/name-unknown errors and Harbor's exact expected
artifact or repository `not found` message. Generic 404 responses and messages
for another repository or digest tag still stop publication. Other lookup errors
and unexpected hashes stop publication. Source-tag aliases are copied from that
verified Harbor digest, avoiding a second upstream transfer. Every entry still
receives a complete anonymous download and alias verification on each run.
Harbor retains the existing scan-on-push policy and NFS registry storage.
No retention/delete job is introduced. Size NFS for the additional images and
retain registry blobs together with Harbor database/encryption-key backups.

## Delivery

1. Merge the bootstrap, inventory, publisher and unapplied Talos patches through
   normal signed-commit, review and CI gates. Apply the reviewed
   `IaC/live/aws-ssm-parameters` saved plan through the existing
   [Harbor rollout path](../openwiki/operations/harbor-oci.md#rollout-and-acceptance),
   inspecting it for unrelated changes first. This creates the independent mirror
   publisher secret. Wait for Harbor secrets to reconcile and its PostSync
   bootstrap to finish Synced/Healthy before publication.
2. Run the protected copy workflow against exact reviewed current `main`:

   ```sh
   reviewed_sha=$(git rev-parse HEAD)
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha"
   ```

   For the Traefik ingress prerequisite, use the fixed one-image scope already
   selected from the full reviewed catalog:

   ```sh
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha" -f image_scope=traefik
   ```

   `image_scope` accepts only `all`, `fleet`, `bazarr`, `traefik`, or `chainguard`; no image,
   digest, inventory path, or destination can be supplied by the caller.
   `scripts/config/harbor-traefik-images.json` selects the pinned public Traefik
   image. Its publication uses the same all-platform digest copy, reviewed tag
   alias, and fresh complete anonymous download checks. A scoped success proves
   only its selected entries; it cannot establish full-catalog coverage. Require
   successful Traefik publication before merging the consuming ingress rollout.

   The `chainguard` scope selects the ten digest-pinned public candidates in
   `scripts/config/harbor-chainguard-images.json`: Python, curl, BusyBox,
   Redis, Valkey, PostgreSQL, Cosign, Node (runtime and development) and Go. It publishes to the same normal
   `mirror/cgr.dev/chainguard/<image>` repositories, with all platforms,
   digest preservation and fresh anonymous downloads. It does not change
   consumers or prove runtime compatibility. Run after the prerequisite merges:

   ```sh
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha" -f image_scope=chainguard
   ```

   See [migration gates and current findings](image-egress-hardening.md).
   Keep the public import source distinct from the internal runtime reference.
   New consuming references use `harbor.stinkyboi.com/mirror/cgr.dev/chainguard/<image>:<reviewed-tag>@sha256:<verified-index-digest>`
   only after successful publication and compatibility validation.

   Require a successful run, including complete anonymous downloads. A completed
   successful `main` dispatch on an ancestor is reusable only when its publication
   bundle is byte-identical to current reviewed `main`: `scripts/config/harbor-images.json`,
   `.github/workflows/harbor-mirror.yml`, `scripts/ci/harbor-publish.sh`,
   `scripts/ci/install-kubeconfig.sh`, `flake.nix`, and `flake.lock`. A scoped
   receipt additionally requires the same selected scope and byte-identical
   scope inventory (for Traefik, `scripts/config/harbor-traefik-images.json`).
   Run titles record the scope and full commit: `Mirror traefik @ <SHA>`, for
   example. The Talos helper requires the exact `Mirror all @ <run head SHA>`
   title for full-catalog provenance; scoped or older untitled runs do not
   qualify. Publish `image_scope=all` if that evidence is absent.
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
   Talos's native `image pull --namespace system` using the selected client
   config. Rollback and dry-run do not pull images. It never drains, restarts or
   deletes workloads.
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

## Private Talos registry route

Talos nodes do not join the tailnet. Before moving Harbor's public DNS to the
mesh, apply the separate
[`harbor-registry-host.yaml`](../.talos/patches/harbor-registry-host.yaml) through
the existing helper's `--registry-host-only` mode. This maps only
`harbor.stinkyboi.com` to the dedicated `traefik/traefik-registry` ClusterIP
`10.96.0.50:443`. That address is explicitly reserved in the `10.96.0.0/12`
Service CIDR; read-only inventory on 2026-10-10 found it unused. Node
kube-proxy routes the connection to Traefik's registry entrypoint on port 9443.
Only `/v2`, `/v2/…`, and `/service/token` for the Harbor hostname are served;
dashboard and management API paths return 404. No LAN or public listener is added.
The URL, TLS certificate name, Authorization header and bearer-token realm remain
`harbor.stinkyboi.com`.

The same inspection found no configured mirrors or extra host entries on any
of the four Talos nodes. This DNS cutover must preserve that state: it does
**not** activate the strict mirror patch. The helper preserves unrelated host
aliases, refuses a conflicting existing Harbor mapping, and validates that
the complete machine configuration changes only `extraHostEntries`.

Talos 1.11.3 can expose only the active `v1alpha1` machine-config resource after
loading configuration from STATE at boot; `persistent` is populated by later
configuration submissions. The helper reads the complete active document stream.
When `persistent` exists, both streams must agree, including additional documents;
staged or try-mode differences fail closed. An absent persistent resource is
accepted only for initial active resource version 1. Changed active state without
that counterpart requires investigation, not a forced apply. Read errors, unknown
or duplicate resources, and missing active configuration remain fatal. Every
pre-apply and post-apply capture repeats these checks; unrelated configuration,
node identity, no-reboot and image-pull gates remain intact.
[Upstream boot acquisition](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/config/acquire.go#L195-L205),
[resource lifecycle](https://github.com/siderolabs/talos/blob/v1.11.3/pkg/machinery/resources/config/machine_config.go#L21-L31).
All four live configurations passed the hostname-only strict validation on
2026-10-10, workers first, without applying. An existing host-network Flannel
Pod on `zimaboard-0` also reached Harbor's existing ClusterIP and received the
expected `/v2/` HTTP 401. This proves current node-to-ClusterIP connectivity;
the new Traefik TLS route and uncached node pull still require live acceptance.

After the Traefik registry Service, TLS certificate and mirrored pause image
are ready, validate all nodes with the pinned Talos 1.11.3 executable and a
private client configuration:

```sh
for node in 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199; do
  python3 -I scripts/talos-harbor-mirrors.py --node "$node" \
    --registry-host-only \
    --talosctl /path/to/talosctl-1.11.3 \
    --talosconfig /path/to/private/talosconfig
done
```

From clean reviewed current `main`, repeat **one node at a time**, in that
order, adding `--execute --expected-sha '<reviewed-main-sha>'`. Execution first
checks the fixed Service and uses a bounded loopback port-forward to verify
TLS, the registry challenge, token issuance, and rejection of dashboard paths.
It applies with `--mode no-reboot`, checks configuration readback and node
identity, then pulls `harbor.stinkyboi.com/mirror/registry.k8s.io/pause:3.10`
through the node's native image API. Correlate a previously uncached pull with
Harbor access logs; cached success alone is not transport evidence. Verify
`talosctl ... read /etc/hosts` contains the exact mapping before moving DNS.

`--registry-host-only --rollback` removes only the owned Harbor alias while
preserving other aliases and every registry setting; execution still requires
the reviewed main SHA. Keep the replacement route operational until rollback
DNS is reachable. The ordinary `--rollback` mode remains the upstream mirror
recovery path. An empty node cannot start Kubernetes, Traefik and Harbor from
that same in-cluster registry: bootstrap their upstream images first, then
enable the private hostname route and any separately reviewed strict mirrors.
Cached restarts do not prove cold bootstrap. This change has no image-cache
deletion or workload restart path.

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
`.talos/talosconfig`), authenticates directly to Talos and verifies its boot
identity; it does not require Kubernetes API availability or a Ready node. Exact-main
verification still requires GitHub access. Apply only through this validated
repository-owned path. Retain mirrored blobs;
rollback changes image transport, not workload versions or stored data.

Sources: [Talos 1.11 Harbor mirror configuration](https://docs.siderolabs.com/talos/v1.11/configure-your-talos-cluster/images-container-runtime/pull-through-cache),
[Harbor proxy-cache behavior and retention](https://goharbor.io/docs/2.14.0/administration/configure-proxy-cache/).
