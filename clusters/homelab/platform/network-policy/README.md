# NetworkPolicy enforcement source

`daemonset.yaml` pins kube-router 2.11.1 to the Harbor mirror and enables only
its iptables firewall. Flannel remains the Pod network, and kube-proxy remains
the service proxy. The host-network privileged exception is necessary to
program node firewall rules; the Pod mounts only the shared xtables lock.
Its health endpoint listens on loopback on the selected node.

The Argo Application registration is staged with automatic sync disabled. Its
selector currently matches no node. Do not sync or label a node until the legacy
assistant archive, supported platform upgrades, full policy-owner/render review,
capacity admission, owned-rule cleanup, and live canary traffic/lifecycle
qualification pass the [platform contract](../../../../specs/003-replace-openclaw-enterprise/contracts/platform.md).
The separate `platform-network-policy-canary` Application tracks `canary/` at
`main`, with automatic sync disabled and an empty Kustomization. Its excluded
`fixtures.yaml` contains taint-bound TCP/UDP allow and deny probes. Registration
alone creates no namespace, Pods, or policy. The `homelab` AppProject admits
the fixture namespace as an explicit destination.

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
selector, host mounts, service account, and read/watch RBAC before probing the
fixed TCP/UDP allow/deny matrix. It rejects extra or unsafe fixture Pods, including
changed commands, arguments, or container security overrides, and
requires each remote probe's outcome marker as well as its exit code, so a
transport error cannot count as a denied connection. It stores a
private receipt listing each still-unverified lifecycle scenario. A successful
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
