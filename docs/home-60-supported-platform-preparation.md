<!-- markdownlint-disable MD013 -->

# HOME-60 supported-platform preparation packet

2026-10-04. **Integrated repository candidate; release and operational HOLD.** This consolidates
HOME-54/58's preparation decision with HOME-55's existing SRE proposal,
Recovery corrections and completed adversarial review. It is not a second
upgrade implementation. No merge, publication, installation, live read/probe,
permission change, snapshot, real-data processing or restore is authorized.

## Evidence identity and ownership

- Entry baseline: `33f2277e50f34d69091bfbb6472eef0bf6486699`.
  Main advanced during preparation to `99deec007bf82f197960f87e9c31bbc51f0c7157`
  (Wazuh #1153). Its 71-file diff was rechecked: chart-source catalog, Multica
  placement and backup client pin are unchanged. New Wazuh manifests, collector
  RBAC, local storage, Harbor images and Talos logging/sysctl patches expand
  generated-grant, application-recovery and strict-render coverage. Include them
  in final integration; earlier #1162 evidence does not cover these additions.
- [Draft #1162](https://github.com/Stuhlmuller/homelab/pull/1162):
  `1d1caad4305c256201c521442dc98507b0f29b52`, resolved through GitHub and
  `git ls-remote`, fetched into an isolated detached review worktree before tests.
  Verified tree: `2d008b857e92da5fc111a18c595580d21f81eab9`.
  Its source changes are reused on an isolated integration branch; the original
  branch remains untouched. Candidate patches do not change active selectors.
- HOME-54 QA `be6e1963-510b-4557-9b08-2bf14576ae13`: source fix and public
  1.34.12 content verified; unsigned revision, incomplete CI, generated RBAC,
  full chart and private-render gates remain. These findings are reused only
  for that revision, not transferred to 1.35.9.
- HOME-54 Recovery `afbcc3f4-336c-475d-a556-071d6121d850`: current linked
  recovery set, independent access and numeric limits missing.
- HOME-55 SRE `070be108-7849-48f6-8ac8-f878a048df4f`, Recovery
  `fdb884d5-5e40-4b4c-8e68-cfd2e777646e`, adversarial
  `d3b2c353-6563-46cc-803c-e2ec60373a75`: supplied attachments read together.
  The adversarial review is complete; do not commission a duplicate.
- HOME-56 QA `19005c28-aacb-40eb-948b-aabe4c3c3ba9` and Recovery
  `6ffa71d9-1e96-476d-8a07-8a84f526d0fd`: mesh chart/schema, artifact,
  staging and independent-access blockers apply to this route too.

Security owns integration. Existing SRE author owns proposal consolidation;
Platform Operations owns chart/catalog/GitOps sequencing; QA and Recovery retain
their independent gates. HOME-3 owns network enforcement, HOME-56 mesh changes.
Neither review author nor Git commit author establishes an authorized operator.

## Destination comparison and expiry

Fresh [Talos matrix](https://docs.siderolabs.com/talos/v1.14/getting-started/support-matrix)
lists all three candidate Kubernetes minors. [Kubernetes releases](https://kubernetes.io/releases/)
lists 1.35–1.37 maintained and the dates below. All three patches are listed
fixed by the [advisory](https://github.com/kubernetes/kubernetes/issues/142097).

| Destination on Talos 1.14.2 | Kubernetes minor transitions from 1.34 | Listed Kubernetes EOL | Preparation disposition |
| --- | --- | --- | --- |
| 1.35.9 | One | 2027-02-28 | Selected minimum-change candidate; compatibility gates open |
| 1.36.5 | Two, through 1.35 | 2027-06-28 | More runway, no demonstrated compatibility benefit justifying added transition |
| 1.37.1 | Three, through 1.35 and 1.36 | 2027-10-28 | Additional blocker: current Istio 1.31 matrix does not list 1.37 |

[Istio support](https://istio.io/latest/docs/releases/supported-releases/)
lists 1.31 support for Kubernetes 1.35/1.36, but existing 1.27.3 is EOL and
does not list even 1.34 as supported. HOME-56's 1.31.1 is a candidate, not
an accepted migration. Do not treat the OS/Kubernetes matrix as whole-stack support.
Talos 1.14 community support ends with 1.15; reconfirm release/support status at
final selection and before any later execution.

Re-review by **2026-10-06 18:00 UTC**, sooner on credible exploitation, increased
exposure or incompatibility. Expiry preserves HOLD. Any bridge needs a named
owner, exact stack, evidenced faster safe remediation than the supported route,
all four gates and an end time no later than **2026-10-26 23:59 UTC**. Serious
security-risk acceptance returns through Decision Review for CEO-threshold
screening after domain and Operations attempts. No routine CEO escalation.

## Proposed checkpoint placement — conditional, not authorized

Prefer a separately reviewed **1.34.11 → 1.34.12 checkpoint before the first
Talos hop**, using #1162's ordered upgrade path after its gates clear. This is
the smallest existing controller-fix proposal and avoids deliberately carrying
the controller defect through sixteen node upgrades. Evidence does not yet prove
it can be delivered safely faster; this preference is not bridge acceptance.
If that checkpoint cannot clear its gates, stop and return sequencing to Decision
Review; do not silently execute the original vulnerable-controller OS sequence.

Conditional preparation sequence:

1. Approve and accept the Kubernetes patch checkpoint independently, retaining
   Talos 1.11.3. No bootstrap patch is applied live; no `upgrade-k8s --dry-run`
   is treated as read-only. Refresh source-stack recovery after this checkpoint.
2. Resolve HOME-56's supported mesh route and stage barriers separately. Its
   operation cannot overlap OS/Kubernetes changes. Exact placement relative to
   each OS hop remains a compatibility decision; unresolved mesh support blocks
   the operational packet, not permission to run unsupported combinations.
3. Prepare adjacent Talos hops **1.11.3 → 1.11.6 → 1.12.12 → 1.13.11 → 1.14.2**
   with Kubernetes explicitly held at 1.34.12. One worker at a time, Acer last,
   whole-cluster acceptance between hops; select the canary from fresh capacity
   evidence. Four Acer outages plus patch/minor-upgrade interruptions need budgets.
4. Only after OS and mesh acceptance, propose **1.34.12 → 1.35.9** through
   ordered API server, controller, scheduler, proxy and serial kubelet updates.
   Observe [Kubernetes skew](https://kubernetes.io/releases/version-skew-policy/);
   no skipped minors and no kubelet newer than its API server.

Each intermediate exception requires separate justification and explicit duration:
1.11.3 patch checkpoint reduces the controller defect but leaves unsupported,
potentially vulnerable OS; 1.11.6 follows latest-source-patch migration guidance
but still does not fix the kernel issue; 1.12.12 introduces the reported kernel
fix but is not the community-supported endpoint; 1.13.11 is the adjacent migration
step to 1.14, also not the endpoint. 1.34.12 throughout those hops remains the
unaccepted Kubernetes bridge. No enterprise entitlement or aggregate waiver is
assumed. [Adjacent Talos guidance](https://docs.siderolabs.com/talos/v1.14/configure-your-talos-cluster/lifecycle-management/upgrading-talos)
does not establish validation of these actual four-node configurations.

## Integrated recovery corrections

This packet rejects the original proposal's generic healthy-API rollback
allowance. API health, A/B boot fallback and Git revert never authorize database
or application rollback. Defaults below are Recovery's tagged-source findings,
not live versions; actual overrides invalidate the matrix.

| Talos source → target | Default etcd source → target | Required source recovery branch |
| --- | --- | --- |
| 1.11.3 → 1.11.6 | 3.6.5 → 3.6.5 | Retained 1.11.3/1.34.12 source set and 3.6.5 tool |
| 1.11.6 → 1.12.12 | 3.6.5 → 3.6.14 | Retained 1.11.6/1.34.12 set; separate source/target validators |
| 1.12.12 → 1.13.11 | 3.6.14 → 3.6.14 | Retained 1.12.12/1.34.12 set and 3.6.14 tool |
| 1.13.11 → 1.14.2 | 3.6.14 → 3.7.1 | Retained 1.13.11/1.34.12 set; never give 3.7 data to 3.6 |

The pre-patch recovery set remains 1.11.3/1.34.11. The post-OS/pre-minor set is
1.14.2/1.34.12. Never relabel old snapshots as the new source stack.
Every transition needs an explicitly bound capture → independent exact-version
retrieval → integrity check → matching-tool restore chain for the SAME set,
plus source configuration revision, software/image identities and application
consistency receipts. September retrieval and restore used different sets.

Plan a separately approved fenced source-stack rebuild if no demonstrated
in-place recovery exists. Fence original control plane, application writers,
GitOps and external integrations; preserve original disks, recovery keys and
application sets. Test Kubernetes watch/informer recovery through the selected
Talos bootstrap path; offline etcdutl parsing is insufficient. No reset, bootstrap,
restore or downgrade command is approved here. Unknown migration state means stop.

Current scheduler pins talosctl 1.11.3; restore helper only accepts etcdutl 3.6.5.
SRE/Recovery must add reviewed version profiles and source-version-bound receipts,
not relax existing checksum/version checks. Stage source and target tools outside
Harbor/Kubernetes; establish RPC and actual format compatibility independently.
Require numeric per-hop outage, maximum snapshot age, observation interval and
per-workload RPO/RTO approved by the appropriate owner. The 36-hour alert threshold
and historical 2.68-second offline check are not accepted RPO/RTO values.

## Artifact reconciliation and compatibility gaps

[Artifact evidence](home-60-artifact-evidence.json) pins all five 1.35.9 public
image indexes and records verified amd64 manifest/config hashes. Hash identity
is not signed build provenance. It also records public checksum-list pins for
five talosctl versions; client binaries were not verified or executed this run.
No images were published. The isolated integration reuses #1162, adds the five
1.35.9 indexes to the Harbor catalog and adds control-plane/worker candidate
patches using its existing shape. All baseline, Wazuh and 1.34.12 catalog entries
are retained. Active bootstrap selectors remain unchanged. Component tags must
be matched to the evidence indexes again before separately approved publication
and execution; no mutable tag alone establishes artifact identity.

[Client preparation profiles](home-60-client-profiles.json) reconcile all five
advertised linux-amd64 talosctl checksums with the source-stack etcd defaults.
They are documentation data, not runtime helper inputs or validated profiles.
The 3.6.5 archive hash is retained from the existing helper; 3.6.14/3.7.1 archive
hashes, RPC compatibility and boot/watch recovery stay explicitly unresolved.
The active schedule remains v1.11.3 and the restore helper remains 3.6.5-only.
Changing those guards without the missing migration evidence is unsafe.

Per-node installer digests are **blocked**: actual schematics, extension sets,
architecture/boot mode are unknown. Talos 1.14 uses Image Factory metal installers;
do not substitute an empty schematic or generic installer. Review extension
compatibility including multipath configuration; retain source images outside
the cluster. Harbor `skipFallback=true` makes publication and cold-node retrieval
separate later gates, not consequences of an entry in JSON.

[Chart gate inventory](home-60-chart-gates.json) lists all 23 catalog chart sources
at the baseline. Every entry requires repository-values rendering at each chosen
Kubernetes version, served CRD/API and conversion/admission webhook review,
rendered SA/RBAC aggregation, chart digest/provenance and image-catalog coverage.
This is a complete catalog inventory, not proof of complete generated resources.
Also inspect operators, literal manifests (including newly merged Wazuh) and cluster-default roles. Unknown
group/wildcard/aggregation/impersonation/bind/escalate grants are not denial.

| Area | Current result / required evidence |
| --- | --- |
| All charts and admission | Full supported-target renders unavailable this run. Helm, Nix, kubectl/Kustomize, Terragrunt and yq absent. No API/schema/admission pass claimed. |
| Istio | HOME-56 rendered 24 baseline/bridge chart instances, but strict ingress schema fails shared values, gateway images remain injection-dependent, and 1.31 charts plus 1.30/1.31 image digests remain unresolved in that review. No transfer of partial success to this stack. |
| Flannel | Establish exact reconciliation point and cluster-wide blast radius of 1.14 nftables transition; a worker canary cannot validate Acer etcd or imply one-node network impact. |
| Multus 4.3.0 | Preserve concurrency 4, priority/resources, host/netns mounts and secondary attachments. Validate mixed versions, fresh CNI ADD/DEL and workload restarts, not only existing pods. |
| Mesh / HOME-3 | Separate mesh changes and policy activation. Require identity-specific allowed and denied paths on primary/secondary interfaces, DNS, cross-node, registry and storage paths. |
| Agent placement | Multica runtime is pinned to Acer; OpenClaw exclusion is not fleet isolation. Preserve placement pending a separately approved change; require independent external operator. RuntimeDefault/non-root do not prove kernel mitigation. |
| Talos config | Strict complete private renders for Acer and all three workers remain unavailable. Prior six synthetic v1.11-contract fixtures omit actual per-worker addresses/extensions and native 1.14 defaults. |
| Isolation/config migration | Upgrade and newly generated 1.14 isolation defaults differ; do not silently enable workloadIsolation. Preserve CNI/storage mounts, CoreDNS GitOps ownership, issuer/SANs, explicit Kubernetes pins; reject conflicting old/new config fields. |
| etcd/tools | 3.7 migration, source-stack rebuild/watch behavior, checksum-pinned version profiles and matching RPC compatibility unvalidated. |

## Four independent gates

1. **Authenticated signed revision:** verify every introduced commit and final
   reviewed head. Prior #1162 QA found unsigned history. No signing identity is
   configured locally; publication of documentation does not waive this gate.
2. **QA technical/provenance/CI:** exact immutable artifacts, complete renders,
   generated RBAC, compatibility and CI for the final candidate. Prior successful
   static jobs coexist with waiting/pending checks; no fresh all-green claim.
3. **Recovery:** linked same-set evidence, source-stack branches, independent
   access, application consistency and approved numeric RPO/RTO/outage limits.
4. **Exact operational approval:** named operator outside the cluster, reviewed
   revision, contexts/nodes/images, start/end window, allowed actions, stop criteria
   and separately approved recovery. No preceding gate supplies this approval.

## Recovery metadata request — incomplete, no collection authority

Route to Homelab Operations Decision Lead through Homelab Decision Desk. The
actual authorized operator, existing receipt/context aliases, exact final reviewed
request revision, output destination/retention and UTC window are **not established**.
Do not assume SRE, Recovery, the commit author or this agent is the operator.
Decision Desk must identify the already-authorized custodian and complete those
fields or return a precise access blocker; no new credentials or routine CEO ask.

Proposed first-stage allowlist: review only an enumerated set of existing private
receipt summaries with an existing document viewer. **No live CLI commands are
requested in this stage.** Do not run backup/scheduler helpers, object-store calls,
talosctl, kubectl, checksum scans, reachability tests or inspect private configs.
Exact receipt identifiers stay with the custodian. The completed request must
enumerate aliases before approval; generic access to a directory is insufficient.

Allowed sanitized fields: receipt alias/origin and observation timestamp;
source Talos/Kubernetes/etcd version and reviewed config revision; recorded capture,
retrieval and restore timestamps; prior same-digest/checksum attestations; retention,
failure-domain and independent-copy class; tool version; prior startup/watch/app
test outcomes; recorded availability of original config, keys, tools, physical
contact and direct access; per-workload coverage/consistency, measured and approved
RPO/RTO, snapshot age, outage limit and missing evidence. Return `unknown` for
missing evidence. Future-hop receipts cannot exist yet. Sanitization does not
authorize producing evidence by accessing backups, keys or systems.

One session, **maximum two hours**, starting only at the separately approved UTC
time; stop at its end or first access/scope gap, unexpected sensitive content,
missing authorization or mismatch of reviewed revision. Sanitized summaries only;
no identifiers, raw logs, task contents, credentials, certificates or values.
Retain exclusions: no snapshots, object-body downloads, decryption, secret/config
exports, probes, installation, permission/credential changes, deletion or restore.
Approval remains pending until the complete request is separately decided.

## Initial packet validation and integration handoff

On isolated #1162: eight focused Kubernetes patch/RBAC fixture tests pass; Harbor
coverage regression passes. Public 1.35.9 index/manifest/config hashes verified.
The full static runner passes bootstrap and focused checks, then stops at missing
Terragrunt (exit 127). Inventory equality, JSON/digest shape and whitespace pass.
These are repository/content results, not live version, containment or recovery
evidence. The earlier 94 recovery tests and six synthetic Talos validations remain
attributed prior results, not rerun results. No current cluster facts collected.

The bounded SRE integration now combines the packet, reviewed #1162 changes and
main at `99deec007bf82f197960f87e9c31bbc51f0c7157` on an isolated branch.
See [integration disposition](home-60-integration-disposition.md) for corrected
proposal precedence, artifact reconciliation, validation and remaining blockers. Platform must resolve mesh/chart stage ownership,
installer identity inputs and mixed-CNI prerequisites. Recovery/Decision Desk must
complete the receipt-only request; private renders and real recovery remain outside
this run. Re-review the integrated exact revision through QA/Recovery, then route
remaining cross-domain risk to Decision Review. Until those blockers close, this
is a reviewable initial packet, not an executable supported-platform proposal.
