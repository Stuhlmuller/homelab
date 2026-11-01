# NetworkPolicy enforcement source

`daemonset.yaml` pins kube-router 2.11.1 to the Harbor mirror and enables only
its iptables firewall. Flannel remains the Pod network, and kube-proxy remains
the service proxy. The host-network privileged exception is necessary to
program node firewall rules; the Pod mounts only the shared xtables lock.
Its health endpoint listens on loopback on the selected node.

The Argo Application registration is staged with automatic sync disabled. Its
selector currently matches no node. Admit only a reviewed, isolated canary
before live qualification. Keep enforcement off other nodes until the legacy
assistant archive, supported platform upgrades, full policy-owner/render review,
capacity admission, owned-rule cleanup, and live canary traffic/lifecycle
qualification pass the [platform contract](../../../../specs/003-replace-openclaw-enterprise/contracts/platform.md).
The separate `platform-network-policy-canary` Application tracks `canary/` at
`main`, with automatic sync disabled and an empty Kustomization. Its excluded
`fixtures.yaml` keeps the taint-bound client on `zimaboard-2` and pins the
allowed and denied TCP/UDP servers to `zimaboard-1` by hostname. Only the
client tolerates the canary taint. The policy grants the client exact CoreDNS
TCP/UDP 53 access. Registration
alone creates no namespace, Pods, or policy. The `homelab` AppProject admits
the fixture namespace as an explicit destination.

The protected `canary-admit` stage changes only the reviewed Node's dedicated
`NoSchedule` taint, then its selector label. It can run with
`activationEnabled: false` after the reviewed baseline, fresh placement, and
live admission checks pass. Admission does not enable the enforcer or fixtures.
A protected `firewall-baseline` stage can run before activation on that worker.
It first confirms the worker UID, boot ID, hostname selector, Ready state,
and only eligible system DaemonSet Pods. It creates the fixed, digest-pinned
`preflight/pod.json` Pod through the protected workflow, reads both IPv4 and
IPv6 iptables backends plus ipset with the existing cleanup snapshot parser,
and requires zero kube-router-owned chains, jumps, and sets.
The short-lived host-network Pod has `NET_ADMIN` to read the host firewall;
it has no service account token or host mount. `NET_ADMIN` can also alter
firewall state, so running this stage is a protected live Pod change, not a
read-only API query.
The stage deletes it and observes its absence
before writing a verified, full private snapshot to the KMS-encrypted,
versioned backup bucket. If deletion, Node identity, Pod inventory, source
SHA, or any snapshot command is uncertain, the attempt is unverified. Its
private `baseline-attempt.json` retains a random Pod ownership token before
creation. If the Pod remains, dispatch protected `firewall-baseline-recover`
with that attempt's `baseline_source_sha` and `baseline_run_id`; the stage
checks the token, uses a UID-precondition Kubernetes DELETE through a private
Unix socket, and confirms absence. Recovery never certifies the firewall.
`canary-admit` separately refuses any remaining preflight Pod before changing
the Node. Review the private capture before dispatching protected `placement`
with the same current-main SHA and the baseline run ID. Placement requires the
capture to be less than one hour old, verifies its single KMS-encrypted S3
version, checksum, empty IPv4/IPv6/ipset snapshot, Node UID/boot ID and exact
system Pod UIDs, then checks live Pod requests, metrics younger than two minutes,
and kubelet node filesystem space on both nodes. On `zimaboard-2`, the pinned
enforcer and client need 282 MiB/260m in requests and 576 MiB at their memory
limits. The two server fixtures need 64 MiB/20m in requests and 128 MiB at
their memory limits on `zimaboard-1`. Each node needs another 128 MiB/100m
and 5 GiB node filesystem free. The server Node must be Ready, schedulable,
free of the canary label and NoSchedule/NoExecute taints, and retain its UID
and boot ID through admission. Its image-cache observation is recorded but
is not an admission requirement; the fixture-first GitOps stage below must
prove the pull before enforcer activation. Placement writes one
immutable receipt per placement run at
`receipts/<current-main-sha>/placement/<placement-run-id>.json`. Another run
can publish a fresh receipt on unchanged `main` after evidence expires, using a
fresh reviewed baseline when the old capture is past its one-hour limit;
earlier receipts remain immutable. Dispatch `canary-admit` with the selected
`placement_run_id`. It verifies the single exact S3 version and binds that
version to the admission result. `canary-admit` accepts it only within 30 minutes
of measurement and one hour of the baseline
capture, then repeats the read-only Pod, metrics, node filesystem, and headroom
checks immediately before changing the Node. A new main commit,
changed Node identity, changed canary system Pod identity, insufficient headroom
on either node, or a failed read blocks the
stage. The earlier host firewall snapshot can drift after capture; admission
does not rerun the privileged probe.

The protected placement stage names this worker and stores a KMS-encrypted,
versioned receipt under
`openclaw-enterprise/platform/receipts/<current-main-sha>/placement/<placement-run-id>.json`.
The receipt must
have `format: 1`, `verified: true`, the exact `sourceSha`, `node` and
`canaryNode`, `nodeUid`, `bootID`, `fixtureNode`, `fixtureNodeUid`,
`fixtureBootID`, `placementRunId`, a timestamp younger than
30 minutes,
`measured: true`, the configured `isolatedTaint`, and
`firewallBaselineEmpty: true` from an independently reviewed pre-enable
snapshot. It must also list every permitted system DaemonSet Pod under
`systemDaemonSetPods` as exact `{namespace, name, uid}` identities; an empty
list is valid only when the node has no assigned Pods. Only `kube-system`
(including Flannel and Multus) and `istio-system` (only the `ztunnel` and
`istio-cni-node` DaemonSets) are eligible. The guard checks namespace,
DaemonSet controller ownership, and exact reviewed Pod UID; it cannot identify
arbitrary `kube-system` applications, so review each listed identity. The stage rejects
existing enforcer/cleanup DaemonSets and fixture namespace, adds the dedicated
taint and admission-run annotation in one Node patch, then checks the live
assigned Pod list before adding the selector label.
It requires a complete cluster-wide Node label inventory with no other canary
selected before mutation and immediately before labeling; a post-label check
removes this Node's label if another selected Node appears. It checks the Pod
list again after labeling. Each Node patch tests
`resourceVersion` and UID and touches only the owned taint, label, or admission
annotation. The annotation binds the selected admission SHA and run ID for the
whole taint lifetime, so an older receipt cannot remove a later attempt's
taint. A taint-only interrupted attempt requires protected
`canary-admit-recover` with its original receipt before a new admission;
a labeled Node needs direct review before another admission attempt.
If the Node patch succeeded but the final `canary-admit.json` upload failed,
dispatch owner-only protected `canary-admit-recover` on current `main` with the
original admission SHA as `evidence_source_sha` and its `admission_run_id`.
The original SHA must be an ancestor of current `main`. The stage loads that
SHA's immutable pre-mutation attempt and exact placement version, refuses an
existing final admission receipt, then runs a short-lived privileged host
firewall probe. It
confirms empty kube-router rules, absent enforcer and fixtures, and no foreign
Pod on the same UID/boot Node before removing only the owned label and taint
with resource-version/UID tests using the current-main code. It works after
placement expires or `main` advances because it retracts admission rather than
accepting a new one. A changed canary node or taint blocks recovery for review.
The probe's attempt is
stored before Pod creation; if the probe remains, use protected
`firewall-baseline-recover` with its recovery run ID as `baseline_run_id`, the
same main SHA as `baseline_source_sha`, and the original `admission_run_id` to
delete only that token/UID-matched Pod before retrying.

If `canary-admit.json` was verified but activation is abandoned before the
enforcer or fixtures exist, dispatch owner-only `canary-abort` on exact current
`main` with the admission SHA as `evidence_source_sha` and its
`admission_run_id`. It loads the immutable verified admission and placement,
requires activation still disabled and the reviewed runtime manifests unchanged,
then proves the host firewall empty with the same UID-owned probe. It requires
the enforcer, cleanup DaemonSet and fixture namespace absent before removing
the matching admission label, then the annotation and taint atomically. A
retry after an interrupted unlabel or completed abort is safe; a changed Node,
source manifest, or new admission marker blocks it. Restore the reviewed
source contract in a protected PR or add a reviewed recovery path; never
hand-remove the taint.
If the abort probe is
orphaned, run `firewall-baseline-recover` with the abort run ID as
`baseline_run_id`, its main SHA as `baseline_source_sha`, and the original
`admission_run_id` before retrying.

If `canary-release` removes the label but stops before removing the taint,
dispatch owner-only protected `canary-release-recover` with the original
`release_source_sha`, `release_run_id`, and `cleanup_run_id`. It requires that
release's immutable attempt, cleanup, ownership, and placement receipts. The
attempt must name the selected cleanup run and Pod UID; older attempts without
that binding fail closed. The original release source must be on current
first-parent `main`, with its reviewed runtime manifests, canary settings,
and activation state unchanged. Recovery requires the matching admission
marker on the same unlabeled, tainted Node, a reviewed cleanup DaemonSet with
no Pods anywhere,
and absent enforcer and fixtures. Before untaint, it requires the original
system Pod UIDs. A same-run
UID-owned probe must prove the host firewall empty and be deleted before the
stage atomically removes the marker and taint. A newer admission marker or
changed Node, Pod, runtime source, or firewall blocks recovery. Do not remove
the taint manually. If the probe is orphaned, dispatch
`firewall-baseline-recover` with the recovery run ID as `baseline_run_id`, its
main SHA as `baseline_source_sha`, and the original `release_run_id` before
retrying. If the marker and taint were removed but the verified receipt was
not retained, rerun with the same selected receipts. A fresh empty firewall
probe and complete, unchanged current Pod inventory produce a read-only
`observedClean` receipt with `mutationPerformed: false`. It reports the
clean state without attributing the earlier patch. This check permits ordinary
workloads that scheduled after untaint but rejects firewall and cleanup Pods.

Admission only gates the Node taint and label. The protected
`network-policy-activation-capacity.py` gate checks the selected immutable
admission and placement versions, exact current `main`, Node identities and
fresh capacity on both nodes before each targeted GitOps apply. Its `fixtures`
phase requires absent runtime and reserves the full two-node budgets without
creating a host firewall probe. A reviewed rollout first syncs `fixtures.yaml`
through the canary GitOps
Application while the enforcer is absent. Verify the two server Pods are Ready
on `zimaboard-1`, the client is Ready on `zimaboard-2`, and each pulled image
has the exact pinned source reference, a SHA-256 runtime image ID, a container
ID, and zero restarts. All fixtures set `imagePullPolicy: Always`, so the
container runtime resolves the pinned digest at the registry for each start
even when layers are cached ([Kubernetes image-pull behavior](https://kubernetes.io/docs/concepts/containers/images/)).
This proves the kubelet started the pinned image before enforcer activation;
runtime IDs can differ from the Harbor source digest.
The `enforcer` phase requires the canary Application Synced/Healthy at exact
current `main`. It checks those exact Pods, policy, image IDs, container IDs,
Pod IPs, Node UID/boot IDs, and the sole admitted client on `zimaboard-2` before and
after a fresh, UID-owned host firewall baseline probe. The probe attempt is
stored before Pod creation; a verified capture requires an empty firewall and
observed Pod deletion. The phase then remeasures both nodes, crediting only
the reviewed running client on `zimaboard-2` while reserving the full 576 MiB
peak plus 128 MiB margin. The `zimaboard-1` check remains conservative: it
reserves the full 128 MiB server peak plus margin even with both servers
running. Either Pod drift, foreign Pod, Node identity change, or failed
capacity check withholds the apply receipt. The gate inspects Pod fields
directly because `Node.status.images` is capped and can omit a cached image.
This sequence
provides an authored first-pull path when the server image is not already
cached on `zimaboard-1`. Once the fixture
image mirror are ready, merge a reviewed first change that sets
`activationEnabled` to `true` in
`scripts/config/platform-maintenance.json` and selects the exact verified
admission `{sourceSha, runId, versionId}`, sets the enforcer Kustomization to
`resources: []` while its Application stays dormant, enables automated sync and
pruning only in
`IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl`,
and lists `fixtures.yaml` in `canary/kustomization.yaml`. Dispatch protected
Terragrunt Apply for `argocd_app=platform-network-policy-canary` on exact
current `main`; verify the split fixture placement and protected first-pull
digest proof.
After the protected activation gate passes, merge a second reviewed change
restoring `daemonset.yaml` to the enforcer Kustomization and enabling automated
sync and pruning in
`IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl`, then dispatch
its protected Apply on exact current `main`. Verify its DaemonSet is Ready
only on `zimaboard-2` and both Applications are Synced/Healthy before dispatching
the read-only `qualify` stage. An
unrelated merge that stales either dispatch requires a retry against current
`main`.

To remove the fixtures, first merge a reviewed change restoring `resources: []`
while leaving automatic sync and pruning enabled and setting `allowEmpty = true`.
Run the same protected targeted Terragrunt Apply and verify Argo CD reports
Synced with no tracked resources and `network-policy-canary` is absent. Keep
that empty Application automated through firewall removal and owned cleanup.
After cleanup is verified and release checks pass, merge a separate change
disabling automatic sync and pruning and resetting `allowEmpty = false`. Do
not remove the node taint or firewall while any fixture remains. This GitOps
sequence uses Argo CD ownership; `qualify` never creates or removes Kubernetes
resources. T019/T027 still require an admitted isolated canary and live
lifecycle evidence.
The static registration gate accepts only the six exact source phases in this
sequence. It does not authorize a live stage: the protected stage still
requires exact-current-`main`, private qualification and ownership receipts,
and live resource and Node identity checks.
`scripts/network-policy-qualification.py` runs only from the protected exact-main
workflow. It checks the live firewall DaemonSet's firewall-only flags, node
selector, host mounts, service account, and read/watch RBAC. It probes the
fixed TCP/UDP allow/deny matrix and resolves the Kubernetes Service name over
both DNS transports, requiring an A record matching the live Kubernetes Service.
It rejects extra or unsafe fixture Pods and placement drift, including changed
commands, arguments, or container security overrides. It compares fixture UID,
node, Pod IP, container ID, and image ID before and after the traffic matrix
and records those identities in its private receipt. It requires each traffic
probe's outcome marker as well as its exit code, so a transport error cannot
count as a traffic result. It stores a private receipt listing each
still-unverified lifecycle scenario. A successful
fixture probe is not Talos qualification: cold bootstrap, first packets,
enforcer stop/restart, API loss, policy/conntrack changes, Pod reschedule/IP
reuse, node reboot, IPv6 absence, and real workload paths remain T027/T028
acceptance gates. This isolated canary does not protect Traefik on its current
`zimaboard-1` node. A later reviewed rollout must relocate Traefik onto the
isolated `zimaboard-2` enforcer node, prove denial from an unauthorized cluster
Pod, and verify private ingress, callback, Harbor, and Octelium user paths.
That relocation needs a new release/cleanup guard that retains the taint and
enforcer while any desired or live Traefik endpoint remains on `zimaboard-2`;
the guard is not implemented here. Before relocation, prove cold-node reboot
and image-GC startup ordering: the enforcer image is Harbor-hosted while
Harbor's private registry path depends on Traefik. Use an independent image
availability path or measured fail-closed startup ordering so Traefik cannot
serve before enforcement after a cache miss. This remains unverified. The live
`tailnet-gateway` to
`istio-ingressgateway` ClusterIP 443 path is a separate private-ingress bypass.
Protected migration or retirement of Octelium private services with caller
acceptance, legacy private-route retirement or restriction, narrowed gateway
access, and negative traffic proof through both ingress paths remain gates.
Removing the DaemonSet alone can leave firewall rules behind. The separately
registered `platform-network-policy-cleanup` Application has automatic sync
disabled and schedules only on the admitted tainted canary. After Enterprise
tenants are quiesced and the enforcer Pod is gone, sync that reviewed cleanup
source through Argo CD. The protected `owned-cleanup` stage requires the selected
private placement receipt proving that the node had no kube-router firewall
objects
before enforcement, plus a separately reviewed `firewall-ownership.json`
pinning the full current firewall snapshot to the same node UID and boot ID.
The protected Platform Maintenance workflow has separate `ownership-capture`
and `ownership-approve` stages. After a successful `qualify` run, merge two
dedicated reviewed GitOps commits in order. Unrelated `main` commits may land
before, between, or after them; the protected stage checks complete first-parent
history and rejects every intervening source change except Markdown under
`docs/`, JSON under `docs/evidence/`, OpenWiki, specs, and named root prose
files. This fail-closed allowlist keeps runtime manifests, the private receipt
bucket, hidden Argo inputs, and validation configuration fixed while allowing
documentation and inventory evidence merges. The first
removes the canary fixtures from `canary/kustomization.yaml` and enables
`allowEmpty` in `IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl`; apply it and
verify the fixture namespace is absent. The second changes only
`kustomization.yaml` here from the enforcer DaemonSet to `resources: []` and
adds `allowEmpty = true` to the already automated
`IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl`. Apply it and verify the enforcer is
gone.
Each commit may also include native updates to the affected OpenWiki pages,
Claims, and run metadata; no other source changes are accepted.
Quiesce tenants and sync the cleanup Pod. Capture, approval, cleanup, and
release require a complete live inventory of Pods assigned to the canary:
exactly the reviewed `systemDaemonSetPods` identities plus the validated
cleanup Pod while it runs. Release rechecks that only the reviewed system Pods
remain after cleanup Pod deletion, immediately before removing the taint. An
incomplete inventory or foreign, terminating, replaced, or extra Pod blocks the
stage. A normal
system DaemonSet Pod restart changes its UID and blocks this flow; the
immutable qualify-SHA placement cannot be refreshed after removal through
the current workflow. Stop for a separately reviewed recovery path; do not
substitute an unreviewed Pod identity. Dispatch `ownership-capture` on the new
exact current `main` with the qualify SHA as `evidence_source_sha`, the
qualify run ID, and the successful admission run ID as `admission_run_id`.
It verifies both exact commit transitions and reads that admission receipt,
its selected placement version, and the traffic receipt,
checks that the fixture namespace and any lingering fixture workload are absent,
then reviews the cleanup Pod and owned-rule plan without deleting anything.
It stores the full IPv4/IPv6/ipset
snapshot privately under
`openclaw-enterprise/platform/<source-sha>/<capture-run-id>/firewall-capture.json`.
The capture is write-once, KMS-encrypted, checksummed, and version-pinned.

The repository owner reviews that private snapshot against the expected
kube-router filter chains, top-level jumps, and ipsets, plus the captured node
UID, boot ID, and qualify receipt. Do not paste the snapshot into a PR or
workflow log. The owner dispatches `ownership-approve` with the capture run ID
and the canonical snapshot's SHA-256 (`snapshotSha256` in the reviewed capture).
The protected job rechecks the private evidence, exact GitOps transition,
current node identity, cleanup Pod, full live snapshot, and exact current
`main` before writing the immutable
`firewall-ownership/<capture-run-id>.json` receipt. Dispatch `owned-cleanup`
with that capture run ID. A mismatch, deleted or duplicate S3 version, or later
rule change blocks cleanup. If deletion stops partway, review a new capture of
the remaining rules, approve its new run ID, and retry cleanup with that ID.
An empty remaining snapshot still needs fresh approval so cleanup can record a
verified no-op receipt. Never reuse the old snapshot approval. Removing an
approved receipt is not a rollback path; leave cleanup blocked and investigate
privately. Approval requires a fresh dispatch by GitHub actor ID `57728706`
(`rstuhlmuller`);
reruns and other actors cannot attest ownership. The production environment's
branch policy does not supply a second reviewer.
Inventory checks and firewall deletion are separate operations. A Pod that
tolerates the isolation taint could arrive during deletion before the next
inventory check. Keep live activation blocked until isolated placement proves
that cannot happen, or add a reviewed repository-owned isolation path.

Each ownership receipt contains `format: 1`, `verified: true`, the exact
`sourceSha`, `evidenceSourceSha`, `captureRunId`, `admissionRunId`,
`placementRunId`, `placementVersionId`, `node`, `nodeUid`, `bootID`,
`snapshotSha256`, and `reviewedAt`.
Approval attests snapshot ownership only. The `qualify` traffic receipt still
lists unverified lifecycle scenarios; it does not authorize enforcement
expansion or replace live worker qualification.
The helper runs only in the protected exact-main workflow and checks live node
identity and that exact snapshot before deleting
the pinned controller's filter chains and ipsets. It refuses unknown prefixes,
foreign references, snapshot drift, and active tenants; never run
kube-router's all-controller cleanup against this Flannel/kube-proxy cluster.
After the `owned-cleanup` receipt is verified and the fixture namespace is
absent, dispatch protected `canary-release` on the same current `main` SHA with
`cleanup_run_id` set to the verified cleanup run. Release reads that immutable
cleanup receipt, its reviewed ownership receipt, and the original placement
at the qualify SHA. It accepts that placement only when the two exact GitOps
prune commits still lead through operational-source-invariant history to current
`main` and the cleanup snapshot,
capture run, and node identity all match. Keep the cleanup DaemonSet present
until release: the stage rechecks that its node-local firewall has no
owned objects, removes the selector label, waits for every cleanup DaemonSet Pod
across the cluster to be deleted, rechecks the complete node Pod inventory,
then removes the dedicated taint. If Pod deletion stalls, the taint remains;
use the protected release-recovery path above after every cleanup Pod is gone
and the selected receipts and live state are verified. It checks Node UID,
boot ID, and
`resourceVersion` before each patch and retains private attempt, interrupted,
and final receipts. A newer `main` invalidates the SHA-bound capture and cleanup
receipts; recapture, approve, and verify cleanup again on current `main` before
release. No stage infers clearance from a missing DaemonSet.
