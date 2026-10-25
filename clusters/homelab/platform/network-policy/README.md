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
`fixtures.yaml` contains taint-bound TCP/UDP allow and deny probes plus an
exact CoreDNS TCP/UDP 53 grant. Registration
alone creates no namespace, Pods, or policy. The `homelab` AppProject admits
the fixture namespace as an explicit destination.

The protected `canary-admit` stage changes only the reviewed Node's dedicated
`NoSchedule` taint, then its selector label. It remains blocked while
`scripts/config/platform-maintenance.json` has `canary.node: null`. A later
reviewed placement must name one worker and place a single KMS-encrypted,
versioned `placement.json` under
`openclaw-enterprise/platform/receipts/<current-main-sha>/`. The receipt must
have `format: 1`, `verified: true`, the exact `sourceSha`, `node` and
`canaryNode`, `nodeUid`, `bootID`, a timestamp younger than six hours,
`measured: true`, the configured `isolatedTaint`, and
`firewallBaselineEmpty: true` from an independently reviewed pre-enable
snapshot. It must also list every permitted system DaemonSet Pod under
`systemDaemonSetPods` as exact `{namespace, name, uid}` identities; an empty
list is valid only when the node has no assigned Pods. Only `kube-system`
(including Flannel and Multus) and `istio-system` (only the `ztunnel`
DaemonSet) are eligible. The guard checks namespace, DaemonSet controller
ownership, and exact reviewed Pod UID; it cannot identify arbitrary
`kube-system` applications, so review each listed identity. The stage rejects
existing enforcer/cleanup DaemonSets and fixture namespace, adds the dedicated
taint, then checks the live assigned Pod list before adding the selector label.
It requires a complete cluster-wide Node label inventory with no other canary
selected before mutation and immediately before labeling; a post-label check
removes this Node's label if another selected Node appears. It checks the Pod
list again after labeling. Each Node patch tests
`resourceVersion` and UID and touches only the owned taint or label. A
taint-only interrupted attempt can retry with a fresh matching placement
receipt; a labeled Node needs direct review before another admission attempt.

After a tainted node passes capacity admission and the fixture image is mirrored,
merge one reviewed change that enables automated sync and pruning in both
`IaC/homelab/us-west-2/apps/platform-network-policy/stack.hcl` and
`IaC/homelab/us-west-2/apps/platform-network-policy-canary/stack.hcl`, and lists `fixtures.yaml` in
`canary/kustomization.yaml`. Dispatch the protected Terragrunt Apply workflow
on the exact current `main` SHA for `argocd_app=platform-network-policy` first;
verify its DaemonSet is Ready on the admitted node. Then dispatch it for
`argocd_app=platform-network-policy-canary`. Argo CD syncs the fixtures. Verify
both Applications are Synced/Healthy and the three fixture Pods are Ready on
the admitted node before dispatching the read-only `qualify` stage. An
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
The static registration gate accepts only the five exact source phases in this
sequence. It does not authorize a live stage: the protected stage still
requires exact-current-`main`, private qualification and ownership receipts,
and live resource and Node identity checks.
`scripts/network-policy-qualification.py` runs only from the protected exact-main
workflow. It checks the live firewall DaemonSet's firewall-only flags, node
selector, host mounts, service account, and read/watch RBAC. It probes the
fixed TCP/UDP allow/deny matrix and resolves the Kubernetes Service name over
both DNS transports, requiring an A record matching the live Kubernetes Service.
It rejects extra or unsafe fixture Pods, including changed
commands, arguments, or container security overrides. It requires each traffic
probe's outcome marker as well as its exit code, so a transport error cannot
count as a traffic result. It stores a private receipt listing each
still-unverified lifecycle scenario. A successful
fixture probe is not Talos qualification: cold bootstrap, first packets,
enforcer stop/restart, API loss, policy/conntrack changes, Pod reschedule/IP
reuse, node reboot, IPv6 absence, and real workload paths remain T027/T028
acceptance gates.
Removing the DaemonSet alone can leave firewall rules behind. The separately
registered `platform-network-policy-cleanup` Application has automatic sync
disabled and schedules only on the admitted tainted canary. After Enterprise
tenants are quiesced and the enforcer Pod is gone, sync that reviewed cleanup
source through Argo CD. The protected `owned-cleanup` stage requires a private
`placement.json` proving that the node had no kube-router firewall objects
before enforcement, plus a separately reviewed `firewall-ownership.json`
pinning the full current firewall snapshot to the same node UID and boot ID.
The stage also checks the privileged DaemonSet template and live Pod against
the reviewed host-access allowlist. Added init or ephemeral containers, host
namespaces or mounts, environment sources, and container hooks block cleanup;
ordinary Kubernetes Pod defaults do not.
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
exact current `main` with the qualify SHA as `evidence_source_sha` and
the qualify run ID. It verifies both exact commit transitions and reads the
pre-removal placement and traffic receipts,
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
`sourceSha`, `evidenceSourceSha`, `captureRunId`, `node`, `nodeUid`, `bootID`,
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
then removes the dedicated taint. If Pod
deletion stalls, the taint remains
and recovery requires direct review. It checks Node UID, boot ID, and
`resourceVersion` before each patch and retains private attempt, interrupted,
and final receipts. A newer `main` invalidates the SHA-bound capture and cleanup
receipts; recapture, approve, and verify cleanup again on current `main` before
release. No stage infers clearance from a missing DaemonSet.
