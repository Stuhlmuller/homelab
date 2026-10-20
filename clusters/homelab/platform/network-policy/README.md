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
It checks the Pod list again after labeling. Each Node patch tests
`resourceVersion` and UID and touches only the owned taint or label. A
taint-only interrupted attempt can retry with a fresh matching placement
receipt; a labeled Node needs direct review before another admission attempt.

After a tainted node passes capacity admission and the fixture image is mirrored,
merge a reviewed change that lists `fixtures.yaml` in `canary/kustomization.yaml`
and sets `IaC/platform-network-policy-canary/stack.hcl` automated
`enabled = true` and `prune = true`. Dispatch the protected Terragrunt Apply
workflow on the exact current `main` SHA with
`argocd_app=platform-network-policy-canary`; it applies the reviewed Application
through a saved, policy-checked plan. Argo CD then syncs the fixtures. Verify
the Application is Synced/Healthy and the three Pods are Ready on the admitted
node before dispatching the read-only `qualify` stage. An unrelated merge that
stales the dispatch requires a retry against current `main`.

To remove the fixtures, first merge a reviewed change restoring `resources: []`
while leaving automatic sync and pruning enabled and setting `allowEmpty = true`.
Run the same protected targeted Terragrunt Apply and verify Argo CD reports
Synced with no tracked resources and `network-policy-canary` is absent. Only
then merge a final change disabling automatic sync and pruning and resetting
`allowEmpty = false`. Do not remove the node taint or firewall while any fixture
remains. This GitOps sequence uses Argo CD ownership; `qualify` never creates
or removes Kubernetes resources. T019/T027 still require an admitted isolated
canary and live lifecycle evidence.
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
That ownership receipt must contain `format: 1`, `verified: true`, the exact
`sourceSha`, `node`, `nodeUid`, `bootID`, `snapshotSha256`, and `reviewedAt`.
No repository workflow produces or approves it yet; keep cleanup blocked until
the ownership review and private receipt path are implemented.
The helper runs only in the protected exact-main workflow and checks live node
identity and that exact snapshot before deleting
the pinned controller's filter chains and ipsets. It refuses unknown prefixes,
foreign references, snapshot drift, and active tenants; never run
kube-router's all-controller cleanup against this Flannel/kube-proxy cluster.
After the `owned-cleanup` receipt is verified and the fixture namespace is
absent, dispatch protected `canary-release` on the same current `main` SHA with
`cleanup_run_id` set to the verified cleanup run. Keep the cleanup DaemonSet
present until release: the stage rechecks that its node-local firewall has no
owned objects, removes the selector label, waits for every cleanup DaemonSet Pod
across the cluster to be deleted, then removes the dedicated taint. If Pod
deletion stalls, the taint remains
and recovery requires direct review. It checks Node UID, boot ID, and
`resourceVersion` before each patch and retains private attempt, interrupted,
and final receipts. A newer `main` requires a
fresh source-bound placement and cleanup receipt; no stage infers clearance
from a missing DaemonSet.
