<!-- markdownlint-disable MD013 -->

# Talos security upgrade proposal — integrated HOME-55/60 revision

2026-10-04. **Repository preparation only; operational HOLD.** This replaces
SRE's initial HOME-55 attachment dated 2026-10-04, incorporating its completed
Recovery and adversarial reviews. The original attachment remains historical
evidence, not current operating guidance. No live evidence was collected.

The historical baseline is Talos 1.11.3 / Kubernetes 1.34.11; current versions,
compromise status and recovery readiness are unknown. The selected preparation
candidate is Talos 1.14.2 / Kubernetes 1.35.9, not an accepted deployment.
The [consolidated packet](home-60-supported-platform-preparation.md) owns support
comparison, expiry, four independent gates and the restricted receipt request.

## Conditional sequence and stop boundaries

1. Separately accept the 1.34.11 → 1.34.12 Kubernetes checkpoint on Talos 1.11.3
   before any OS hop. Reuse the ordered #1162 path, never apply bootstrap image
   patches live or treat `upgrade-k8s --dry-run` as read-only. This preference
   does not approve a bridge. If its gates cannot clear, return sequencing to
   Decision Review; do not silently retain the vulnerable controller through OS
   maintenance. Retain the pre-checkpoint 1.11.3/1.34.11 recovery set.
2. Platform/HOME-56 must resolve the mesh stages and compatibility with HOME-3
   before operational acceptance. Istio 1.27.3 is not an accepted supported
   dependency. No mesh or policy activation may overlap OS/Kubernetes work.
3. Prepare Talos 1.11.3 → 1.11.6 → 1.12.12 → 1.13.11 → 1.14.2 while explicitly
   holding Kubernetes at 1.34.12. Retain worker-first/Acer-last, one node at a
   time and whole-cluster acceptance per hop. Select workers from fresh capacity
   evidence; no historical node readiness is a current preflight. Budget four
   Acer outages and sixteen node upgrades, plus the Kubernetes interruptions.
4. After OS and mesh acceptance, separately approve 1.34.12 → 1.35.9 using
   ordered API server/controller/scheduler/proxy and serial kubelet transitions.
   Retain the post-OS 1.14.2/1.34.12 source set before this minor change.

A worker canary does not exercise Acer's etcd migration. Platform must establish
when Talos-managed Flannel reconciliation changes the entire network and prove
mixed-version Flannel/Multus, fresh CNI ADD/DEL, secondary attachments, ambient
capture, allow/deny paths, DNS, registry and storage behavior. One OS operation
at a time does not imply one-node network impact. Preserve Multus concurrency,
mounts, priorities and resources; no silent isolation-default migration.

Multica is pinned to Acer. OpenClaw's Acer exclusion is not fleet isolation;
preserving placement preserves the control-plane dependency. Require an operator
and observer outside this cluster. Mitigation, relocation or workload suspension
needs separate approval. RuntimeDefault/non-root is not kernel-fix evidence.

## Source-stack recovery replaces the former rollback allowance

API health never authorizes `talosctl rollback`. Talos A/B retains an OS image,
not reversible etcd/configuration/application state. No in-place downgrade has
been demonstrated. Use the packet's per-hop matrix: upstream etcd defaults are
3.6.5 → 3.6.5 → 3.6.14 → 3.6.14 → 3.7.1; actual overrides invalidate it.
Never feed target 3.7 data to source 3.6. Unknown migration state means stop.

Every transition requires a source-version-bound set: exact Talos/Kubernetes/etcd
and config revision, image identities, snapshot digest/capture time and the SAME
set's independent retrieval, integrity check and matching-tool restore receipts.
Keep source artifacts outside cluster/Harbor and routine pruning until recovery
acceptance. September's separate retrieval and restore sets do not qualify.
After a successful checkpoint/hop, require a fresh target-version set before
advancing; old snapshots must not be relabelled.

Prepare a separately approved fenced source-stack rebuild when an in-place
route is unproven. Fence original control plane, application writers, GitOps
and external integrations; retain original disks, keys and application-consistent
sets. Identify exact volumes before any reset. No generic EPHEMERAL wipe or
reuse of the historical corrupt-object procedure. Etcd state alone does not
restore NFS, local PostgreSQL or Wazuh data. Rehearse watch/informer recovery
through the chosen Talos bootstrap; an offline etcdutl parse is insufficient.

[Client profiles](home-60-client-profiles.json) are preparation data only.
Active backup scheduling stays on 1.11.3 and restore validation on 3.6.5.
Versioned runtime profiles, 3.6.14/3.7.1 archives, metadata fixtures and actual
RPC/format compatibility are still required. Do not loosen checks to bypass
these gaps. Source and target tools must be available independently of Kubernetes.

Recovery must approve numeric per-hop outage, maximum snapshot age, observation
interval and workload RPO/RTO. The earlier 30-minute worker-pressure soak remains
a proposed minimum for previously unstable workers, not an accepted universal
outage or recovery budget. Exceeded limits or failed gates stop all new changes;
no extra reboot, force drain, power cycle, deletion or restore is thereby allowed.

## Evidence and authorization boundaries

The earlier six synthetic v1.11-contract Talos renders and 94 helper tests remain
attributed historical evidence. They do not cover native 1.14 defaults, actual
private four-node configs, extensions, RPC, boot recovery or live state.
Installers remain blocked on actual schematics/extensions/architecture/boot mode;
never substitute an empty schematic. Preserve issuer/SANs, GitOps CoreDNS, storage,
agent placement and Harbor fallback settings. Recheck multipath migration and
conflicting old/new config fields with complete private renders when authorized.

Use only HOME-60's separately approvable existing-receipt request, maximum two
hours, with the HOME-61 custodian/context/revision/window fields completed first.
No live commands, probes, new snapshots, object downloads, decryption, exports,
permission changes, deletion or restore. Missing evidence stays unknown.

Authenticated signing, QA/provenance/CI, Recovery and exact operational approval
are independent. Re-review by October 6, 18:00 UTC; expiry retains HOLD. Any bridge
requires its own owner, benefit, scope and expiry no later than October 26,
23:59 UTC. Decision Review handles cross-domain risk and CEO-threshold screening;
Decision Desk handles the completed bounded request. No execution is approved.
