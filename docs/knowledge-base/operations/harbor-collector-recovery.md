# Harbor collector recovery proposal

Tags: #harbor #recovery #proposal

The [recovery proposal](../../harbor-vulnerability-recovery-proposal.md) is a
separate HOME-57 artifact for SRE integration alongside
[[operations/harbor-oci]]. It preserves HOME-59's all-hop verified TLS decision
and HOME-3's independent isolation gate. Merge and activation remain held.

An unregistered `clusters/homelab/apps/harbor-recovery-candidate` overlay renders
only the exporter replica count to zero. Promote only that reviewed delta into
current-main desired state after approval; never apply the whole candidate or
restore the original admin-over-HTTP collector. First cutover has no previously
accepted robot/TLS rollback. Prove all old collector Pods gone before activation.

Proposed staffed interruption budgets are 20 minutes for cutover and 15 minutes
for renewal, with unchanged Grafana → Alertmanager → existing Discord routing,
no alert silences and an independent deadline observer. These are approval
requests, not measured guarantees. Expiry watch and route delivery remain gates.

Availability rollback retains only valid uncompromised scoped credentials.
Compromise needs separately authorized exact-ID server disable and replay/session
rejection evidence; zero replicas cannot revoke a token. Protected standalone
disable and partial-state recovery operations are missing from the current
lifecycle helper. Disabled/expired or unknown states must not be retried as normal
renewal or repaired by restoring old SSM versions.

Collector stop touches no retained data. Wider TLS changes require client-impact
and backup readiness evidence: a database dump plus same-NAS blobs is not proven
disaster recovery. See [[architecture/storage-and-state]]. No real-data restore,
provisioning, credential mutation, live test or operational acceptance is claimed.
