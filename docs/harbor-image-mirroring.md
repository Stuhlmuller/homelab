# Kubernetes images in Harbor

<!-- markdownlint-configure-file { "MD013": false } -->

## Chainguard source provenance

`scripts/config/harbor-chainguard-images.json` is the reviewed, digest-pinned
public Chainguard source catalog. The protected `harbor-mirror.yml`
`chainguard` scope copies its thirteen entries to
`mirror/cgr.dev/chainguard/<image>`. That proves source provenance and Harbor
custody only; it does not make an artifact deployment-eligible or move a
consumer to the public `mirror` project.

Native Harbor replication is currently limited to
`cgr.dev/chainguard/python:latest` and `cgr.dev/chainguard/curl:latest`, which
it imports into private `homelab/chainguard-python:latest` and
`homelab/chainguard-curl:latest` repositories. After bootstrap has reconciled
those rules, the protected
`harbor-native-chainguard-receipt.yml` workflow must run from exact current
`main`. Its receipt is bound to the automation configuration, replication
rules, and catalog pins. It proves that the source root index, private
destination root index, and a complete authenticated `robot$homelab+pull`
download have identical bytes; that the required `linux/amd64` and
`linux/arm64` child descriptors match; and that Harbor reports `Success` with
every reported finding count zero for those children.

Protected CI queries those child scans directly with the separate
`robot$homelab+scan` credential, limited to project-scoped `artifact:read`.
It does not create an in-cluster scanner Job or use the Harbor administrator
credential. Both receipt identities are read from exact SSM parameters into
private temporary files and are excluded from workflow output and artifacts.

The receipt is protected-workflow evidence only. It does not create a digest
tag or `verified-stable` alias, update Image Updater state, or change a
workload. A checked-in receipt cannot enroll a consumer until a verifiable
artifact-attestation importer exists. A later reviewed migration must add
namespace pull authorization, compatibility evidence, and a direct,
digest-pinned private reference such as
`harbor.stinkyboi.com/homelab/chainguard-python@sha256:<verified-index-digest>`.

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
stage-one read access remains public, including through the existing public
Harbor hostname. The separate `robot$mirror+publisher` is used only for writes
within `mirror`, while `robot$mirror+pull` independently reads publication receipts;
they use generated `/homelab/harbor/mirror-robot-push-password` and
`/homelab/harbor/mirror-robot-pull-password` credentials. The reviewed node-auth
step gives Talos the pull credential before project privacy changes; workloads
do not receive it.

The normal project retains copied artifacts independently of upstream tags or
deletion. It is deliberately not a proxy cache. The protected
`harbor-mirror.yml` workflow copies all platforms with digest preservation,
keeps a digest-named tag for each entry, maintains reviewed source-tag aliases,
and downloads every Harbor image with the dedicated pull robot into a fresh
temporary directory.
Retries reuse an existing digest-named tag only after its manifest hash matches
the catalog; a missing tag is copied from upstream. Missing-content detection
accepts registry manifest/name-unknown errors and Harbor's exact expected
artifact or repository `not found` message. Generic 404 responses and messages
for another repository or digest tag still stop publication. Other lookup errors
and unexpected hashes stop publication. Source-tag aliases are copied from that
verified Harbor digest, avoiding a second upstream transfer. Every entry still
receives a complete authenticated Harbor download and alias verification on
each run.
Harbor retains the existing scan-on-push policy and NFS registry storage.
No retention/delete job is introduced. Size NFS for the additional images and
retain registry blobs together with Harbor database/encryption-key backups.

## Delivery

1. Merge the bootstrap, inventory, publisher and unapplied Talos patches through
   normal signed-commit, review and CI gates. The reviewed Stage A saved plan has
   created and metadata-verified the independent mirror reader SSM parameter.
   This consumer revision advances `harbor-secrets` to `v4`; wait for External
   Secrets to reconcile it and Harbor's PostSync bootstrap to finish
   Synced/Healthy before publication. The parameter alone does not create a
   Harbor robot, enable authenticated receipts, or change Talos.
2. Run the protected copy workflow against exact reviewed current `main`:

   ```sh
   reviewed_sha=$(git rev-parse HEAD)
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha"
   ```

   For the Traefik ingress prerequisite, use the fixed two-image scope already
   selected from the full reviewed catalog:

   ```sh
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha" -f image_scope=traefik
   ```

   `image_scope` accepts only `all`, `fleet`, `bazarr`, `traefik`, or `chainguard`; no image,
   digest, inventory path, or destination can be supplied by the caller.
   `scripts/config/harbor-traefik-images.json` selects the pinned public Traefik
   image and the pinned `pause:3.10` image used by native Talos pull acceptance.
   Their publication uses the same all-platform digest copy, reviewed tag
   alias, and fresh complete authenticated Harbor download checks. A scoped success proves
   only its selected entries; it cannot establish full-catalog coverage. Require
   successful Traefik publication before merging the consuming ingress rollout.

   Mastodon PostgreSQL candidate uses the separate upstream tag
   postgres:18-bookworm at index
   afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c.
   Its amd64 configuration reports PostgreSQL 18.6-1.pgdg12+2 and the unchanged
   /var/lib/postgresql/18/docker data directory. The older 18.6-bookworm digest
   remains enrolled for Harbor; this preparation changes no live database.
   Publish and inspect fresh scan results before changing the Mastodon consumer.

   The `chainguard` scope selects the thirteen digest-pinned public candidates in
   `scripts/config/harbor-chainguard-images.json`: Python, curl, BusyBox,
   Redis, Valkey, PostgreSQL, Cosign, nginx, Node (runtime and development), Go,
   Wolfi base and static runtime. It publishes to the same normal
   `mirror/cgr.dev/chainguard/<image>` repositories, with all platforms,
   digest preservation and fresh authenticated Harbor downloads. It does not
   change consumers, prove native `homelab` imports, or prove runtime
   compatibility. Run after the prerequisite merges:

   ```sh
   gh workflow run harbor-mirror.yml --ref main -f expected_sha="$reviewed_sha" -f image_scope=chainguard
   ```

   See [migration gates and current findings](image-egress-hardening.md).
   Keep the public source copy distinct from the internal runtime reference.
   No application consumes these `mirror` copies. Python and curl need a
   successful native receipt from the separate protected workflow before a
   reviewed compatibility migration may reference a private direct digest such
   as `harbor.stinkyboi.com/homelab/chainguard-python@sha256:<verified-index-digest>`.

   After that public source copy and Harbor's native Python/curl replication
   have both completed, verify the private imports from exact reviewed current
   `main`:

   ```sh
   gh workflow run harbor-native-chainguard-receipt.yml --ref main -f expected_sha="$reviewed_sha"
   ```

   The receipt workflow accepts no image, registry, destination, or credential
   input. It verifies only the committed Python and curl plan and uploads the
   bounded receipt artifact. A successful receipt is necessary protected-workflow
   evidence for a later workload migration; a checked-in copy cannot enroll a
   consumer until a verifiable artifact-attestation importer exists.

   Require a successful run, including complete authenticated Harbor downloads. A completed
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
   Missing artifacts are staged through an anonymous all-platform source download
   (`upstream-download`) and exact original-manifest hash check (`upstream-verify`)
   before authenticated Harbor upload (`destination-copy`). Preserve the original
   index bytes, including repeated descriptors; do not normalize the index to
   manufacture a different digest. The temporary source is removed before the
   independent authenticated Harbor pull, keeping one full image tree on disk at a
   time. Existing artifacts retain their strict resume/hash/full-pull checks.
   Failed runs expose only the catalog source, operation phase, exit status and
   a fixed error category. Raw transport logs and credentials remain private.
   Operator-approved diagnostics encrypt mirror stderr, including setup errors, to
   the primary fingerprint `2E0AE9393F24306F26A9AEB5A86F8F76C83C03EC` and exact
   encryption subkey `4CF2875A21C967B08566F07D686CEA719DC4B96D` before cleanup.
   Readiness and port-forward details include at most 64 KiB from each log.
   GitHub Actions retains only `harbor-publication-error.gpg` for one day.
   Key download, fingerprint or encryption failure leaves no artifact; there is
   no plaintext fallback. Download and decrypt locally with `gpg --decrypt`
   into a private file, then remove it after diagnosis. Remove the workflow
   upload step and helper call to disable capture.
   Categories also distinguish bare HTTP 403, payload-size limits, 5xx server
   responses and quota exhaustion. A category is a diagnostic hint, not source
   or destination attribution, an absent-artifact proof, or permission to retry.
3. After a successful full-catalog publication, materialize the fixed mirror
   reader credential into an existing owner-only directory outside every Git
   checkout. Use a named AWS profile with only this parameter's declared read
   grant; never pass the password through an argument or environment variable.

   ```sh
   mkdir -p -m 700 /path/to/private/harbor-mirror
   python3 -I scripts/talos-harbor-mirror-credential.py \
     --profile <named-aws-profile> \
     --directory /path/to/private/harbor-mirror \
     --expected-sha "$reviewed_sha"
   ```

   The command writes only
   `/path/to/private/harbor-mirror/harbor-mirror-registry-auth.json` at mode
   `0600`. It verifies exact current `main` before and after SSM read.

4. From that clean checkout, render and strictly validate each existing machine
   configuration with that credential. The helper defaults to inspection; use Talos client 1.11.3.
   Restore the private client config at `.talos/talosconfig`, or pass an existing
   private file explicitly with `--talosconfig /path/to/private/talosconfig` on
   every command below. It never falls back to the user config or `TALOSCONFIG`;
   an absent selected file stops before any network call. Never commit this file.

   ```sh
   for node in 10.1.0.202 10.1.0.201 10.1.0.200 10.1.0.199; do
     python3 -I scripts/talos-harbor-mirrors.py --node "$node" \
       --registry-auth-file /path/to/private/harbor-mirror/harbor-mirror-registry-auth.json
   done
   ```

5. Apply one node at a time, workers first and the sole control plane last:

   ```sh
   python3 -I scripts/talos-harbor-mirrors.py --node 10.1.0.202 \
     --registry-auth-file /path/to/private/harbor-mirror/harbor-mirror-registry-auth.json \
     --execute --expected-sha "$reviewed_sha"
   ```

   Repeat for `.201`, `.200`, then `.199` only after the preceding node passes.
   The helper requires successful publication of the same bundle, verifies destination
   manifests with the dedicated mirror reader, preserves the full persistent machine
   configuration, allows only registry-mirror and owned Harbor-auth differences, validates with `--mode metal --strict`, and
   applies with `--mode no-reboot`. It checks configuration readback and node
   readiness/boot identity, then requests `registry.k8s.io/pause:3.10` through
   Talos's native `image pull --namespace system` using the selected client
   config. Execution without the reader credential proceeds only when the
   captured configuration already has valid `robot$mirror+pull` auth.
   Rollback and dry-run do not pull images. It never drains, restarts or deletes
   workloads.
6. Verify every node's `registryconfigs` resource contains the committed
   endpoints, `skipFallback: true`, and only the owned Harbor reader auth.
   Keep `mirror` public until all node readbacks and native pulls pass. Then make
   its project metadata private through a separate reviewed bootstrap change;
   prove anonymous Harbor pulls fail and a previously uncached node pull still
   succeeds. Correlate each native pause pull with
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
is changed. Registry authentication and Bearer token headers stay in private
temporary files and are removed on exit. Every digest-named tag and source-tag
alias must return the catalog's exact manifest bytes after a successful copy
workflow for the same
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

The repository configures public-mirror publisher bootstrap with
`/homelab/harbor/mirror-robot-push-password`. The repository-owned
`harbor-secrets` ExternalSecret and protected publisher reference that
credential; this initial publisher plan does not provision the later reader
prerequisite below.

The 2026-09-28 shared SSM plan also contained pending AI secret creation. For
the initial publisher bootstrap, plan only its parameter and declared
dependencies:

```sh
(cd IaC && terragrunt stack generate)
cd IaC/live/aws-ssm-parameters
terragrunt plan \
  -target='aws_ssm_parameter.generated["/homelab/harbor/mirror-robot-push-password"]' \
  -out /path/to/private/mirror-publisher-secret.plan
terragrunt --log-disable show -json /path/to/private/mirror-publisher-secret.plan \
  > /path/to/private/mirror-publisher-secret.json
conftest test --policy ../../../policy /path/to/private/mirror-publisher-secret.json
```

Keep both files private. Review the saved plan before applying that exact plan
from clean reviewed `main`. The inspected publisher plan creates the Harbor SSM
parameter with its independent password. Shared dependencies may also create 12
other pending random values in encrypted state and add 14 already-declared AI
secret paths to the reader policies; they do not create those SSM parameters,
rotate existing values, or delete resources. Those shared changes require
explicit operator approval; do not silently treat them as Harbor-only. Reject
any further change or replan/review if state advances. This is a one-time scope
limit, not the steady-state bootstrap command; normal full Terragrunt apply
still owns the whole declared stack.

## Mirror reader prerequisite

The `/homelab/harbor/mirror-robot-pull-password` catalog entry is a deliberate
first stage. It has a separate saved plan from the publisher bootstrap:

```sh
(cd IaC && terragrunt stack generate)
cd IaC/live/aws-ssm-parameters
terragrunt plan \
  -target='aws_ssm_parameter.generated["/homelab/harbor/mirror-robot-pull-password"]' \
  -out /path/to/private/mirror-reader-secret.plan
terragrunt --log-disable show -json /path/to/private/mirror-reader-secret.plan \
  > /path/to/private/mirror-reader-secret.json
conftest test --policy ../../../policy /path/to/private/mirror-reader-secret.json
```

Keep both reader-plan files private. The reviewed plan has been applied from
clean `main` and its SSM metadata verified without reading its value. It created
only the reader parameter and the exact-ARN External Secrets reader-policy
changes identified in the plan, including deterministic policy chunk rebalancing.
Its wider shared dependency closure remains outside approved scope; reject
unexpected grants, rotations, deletes, or other actions.

This later consumer revision advances `harbor-secrets`' `OnChange` revision to
`v4`, after the parameter exists, so External Secrets reconciles the new key.
Until that reconciliation and the PostSync bootstrap succeed, it does not create
the Harbor reader robot, enable publication receipt/readback, or change nodes.
Keep that Secret `OnChange`: periodic reconciliation would regenerate its salted
bcrypt registry password hash.

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
hash the exact manifest bytes. Pass direct `repo@sha256` addresses to Skopeo;
it rejects combined tag/digest addresses. Preserve historical pinned digests
when a mutable tag has moved. Each repository/tag has one catalog alias;
additional old digests use digest-only sources. Never import private artifacts
into the mirror project.

## Bootstrap and recovery

An in-cluster registry cannot cold-start from itself on empty nodes. Fresh
bootstrap uses upstream image names without the steady-state mirror patch.
Bring up networking, DNS, secret management, ingress, Harbor and its retained
storage, restore or republish the catalog, verify complete authenticated Harbor pulls, then enable
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

## Mastodon publication scope

Select `image_scope=mastodon` to publish the four reviewed runtime images in
`scripts/config/harbor-mastodon-images.json`: official web/Sidekiq, streaming,
PostgreSQL 18, and Redis 7.4. This is the entire new workload image set, including
migration/bootstrap/backup reuse. The fixed scope excludes unrelated Node and
other catalog aliases while retaining all-platform digest copies, source-tag
aliases, and complete anonymous destination pulls. No caller-supplied repository,
digest, manifest, or destination is accepted.

The inventory gate compares the scope with the rendered Mastodon overlay once
that consumer exists. Before onboarding, it compares all four fixed version tags
against the full reviewed catalog. Runtime version changes must update the
publication scope in the prerequisite change before the consumer reaches main.
Existing shared platform dependencies keep their own publication ownership.

## Publication queue boundaries

The public mirror workflow uses `harbor-mirror-production` with cancellation
disabled, serializing every mirror scope and its shared tag aliases. Private
custom-image publication retains `harbor-packages-production`. Public mirroring
writes only to `mirror`; custom publication writes to `homelab`, so a private
publication approval wait does not reserve the public mirror lane. Neither lane
bypasses production environment approval, reviewed-main checks, digest checks,
or complete destination pulls. Registry readiness remains a shared prerequisite.

## Publication failure diagnostics

The mirror workflow keeps transport and registry logs private. On failure it
prints only the publisher's fixed source, phase, exit status, and category fields
when the publisher matches the reviewed checksum pinned in the workflow. Update
that pin with publisher changes; the offline publication test checks this
contract. A stale pin suppresses the safe summary as well as private logs, leaving
only a generic failure. Never print the private log to recover missing context.

## Duplicate-index publication failure

On October 11, 2026 UTC, full-catalog runs `38108370598` and `38117127796`
failed on the pinned LiteLLM database index
`sha256:3305291fc9fa1b53196e21567a97f4c51e3a38bdc4e19704e38a551ee7712cd8`.
Its eight descriptors reference four child digests twice. The second failure
correlates with Harbor PostgreSQL's `unique_reference` violation at
`08:53:38.389Z`; registry child writes succeeded but the parent was unavailable.
This matches [upstream Harbor issue #16718](https://github.com/goharbor/harbor/issues/16718).

Keep the source index, attestations and pinned digest intact. Do not alter the
live database schema to bypass this failure. Compatible full-catalog publication
requires a separately reviewed repair. The fixed Traefik scope publishes the
native pause probe independently; its success authorizes only those artifacts.
Node hostname migration still requires successful native pulls from every node.
Cluster-wide `skipFallback` mirrors remain gated on successful full publication.
## Custom-image publication acceptance

The fixed custom-image publisher completely downloads each pushed private
Harbor digest into a fresh temporary directory using its project-scoped pull
permission, preserving all manifests and blobs. It verifies the downloaded root
manifest against the pushed digest before creating the signing Job or emitting
consumer references. A missing blob, failed download or digest mismatch stops
publication acceptance and withholds signing/output references. This verifies
transport completeness; private vulnerability review and original workload
behavior remain separate release gates.
