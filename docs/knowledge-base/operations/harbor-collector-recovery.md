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

## Hook-safety and interrupted recovery correction

The [selective-stop addendum](../../harbor-hook-safe-stop-and-readback.md) supersedes
unrestricted sync of the replica-only overlay: full sync can run bootstrap and
backup retention hooks. The offline request validator selects only the exporter
Deployment with no prune/retry, after declared auto-sync pause and independent
writer exclusion. Source-level hook exclusion is conditional; no installed
controller or disposable runtime evidence exists. Never use ApplyOutOfSyncOnly
as a substitute or automatically restore full auto-sync.

The recovery planner retains UNKNOWN after process death, cancellation and lost
create/mutation responses. It accepts null unknown IDs without adoption, and
requires a later independent observer/audit/version/state correlation before
preparing another exact-ID approval. All execution/resume/revocation flags remain
false. HOME-62 custody and session termination remain unsupported prerequisites;
no reusable management credential enters the general runner. SRE owns integration
with its separate custody/reader/writer proposal and QA's unexecuted capability
cases. No real operation or runtime hook exclusion is claimed.
