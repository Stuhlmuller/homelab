# October 2026 synthetic recovery exercise

HOME-21, 2026-10-01. **Synthetic checks passed within the scope below;
operational Octelium recovery remains unproven.** No production archives,
credentials, PVCs, cluster APIs or AWS APIs were accessed. No rollout occurred.

## Evidence boundaries

- Current `main`: `855c9300f1348fddfbe6673747cd0087bbf0a408`, matched against
  `git ls-remote origin refs/heads/main` before and after the exercise.
- Proposed independent publication: [HOME-2 PR #1113](https://github.com/Stuhlmuller/homelab/pull/1113)
  at `66de4860068adb0c60a348c2e598e08dde415f65`, tested in a separate detached
  worktree without merging its changes. GitHub reported open, unmerged and
  `mergeable: false`; integration with current main needs separate resolution.
- [HOME-3 PR #1116](https://github.com/Stuhlmuller/homelab/pull/1116) remains
  open at `7eaf44c2fa6b6cb7eb2b20e084ba3ed1d70d9a98`;
  [HOME-4 PR #1120](https://github.com/Stuhlmuller/homelab/pull/1120) remains
  draft at `2e0b020cd5113124445a8d95a478e13c2aaaa984`. Their issue evidence
  still leaves real restore containment and independent monitoring incomplete.
- HOME-1's original review and HOME-2/3/4 handoffs were read. HOME-2 previously
  reported a PostgreSQL 15.19 synthetic round trip on September 29; this run
  reproduced that proposal's checks and exercised current-main SQL invariants.
  Historical etcd/offsite receipts in [[architecture/storage-and-state]] do
  not prove application-data recovery or present backup freshness.

## Checks executed

| Revision | Check | Result and limitation |
| --- | --- | --- |
| Main | `python3 -I scripts/ci/etcd-offsite-backup-check.py` | 16 tests passed; mocked publication, not an etcd or PVC restore |
| Main | Database cases from `scripts/ci/octelium-restore-drill-test.py` | 10 passed in 10.468s on PostgreSQL 15.19; the manifest/render case was excluded because kubectl and yq were unavailable |
| HOME-2 head | `python3 -I scripts/ci/application-backup-test.py` | 14 tests passed: interrupted upload, lost acknowledgement, corrupt download, completion-marker retry, wrong version, incomplete/checksum/path/symlink rejection, altered preparation, stale/future capture, paired fence attestation, six-media-set contract, retention plan and failure metrics |
| HOME-2 head | `python3 -I scripts/ci/application-backup-restore-test.py --pg-bin /absolute/test-postgresql/bin` | Passed in 2.33s: real disposable PostgreSQL dump/restore, synthetic records/key bytes and paired upload hash; S3 mocked |
| HOME-2 head | `python3 -I scripts/ci/application-backup-rules-test.py --rules-json /absolute/test-rules.json --promtool /absolute/promtool` | Five scenarios passed with Prometheus 2.42.0: absent, healthy, failed, stale capture, stopped checker |

The current-main database cases verify source preservation, empty public output,
private diagnostics, archive-created client/server console-output attempts,
non-C database locale/encoding/owner preservation, corrupt newest-set rejection
without fallback, checksum path confinement, stale/previous-day rejection,
missing wrapped-key rejection and empty required-table rejection. They execute
repository-authored synthetic SQL only. The fixture key bytes are not evidence
that Octelium can decrypt real encrypted resources.

Test tools were extracted locally from Debian packages, without system install:
PostgreSQL/client/libpq `15.19-0+deb12u1`, Prometheus
`2.42.0+ds-5+deb12u1`, locales/libc-l10n `2.36-9+deb12u14`, and
libnss-wrapper `1.1.12-1`. This runtime's UID 1000 lacks a passwd entry;
the test processes used a synthetic NSS entry through libnss-wrapper.
`en_US.UTF-8` was generated in private test tooling with `localedef`.
PATH/LOCPATH and NSS settings affected test processes only, not desired state.
The alert JSON was a PyYAML parse/JSON serialization of the unchanged candidate
`recovery/application-backups/prometheusrule.yaml`.

To reproduce the exact 10-case selection with those test dependencies available:

```python
import importlib.util
import unittest

spec = importlib.util.spec_from_file_location(
    "drill", "scripts/ci/octelium-restore-drill-test.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
names = unittest.defaultTestLoader.getTestCaseNames(module.RestoreDrillTest)
names.remove("test_manifest_declares_storage_credential_and_network_policy_contracts")
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.TestSuite(module.RestoreDrillTest(name) for name in names))
raise SystemExit(not result.wasSuccessful())
```

Run the full production-matched suite later with
`nix develop --command python3 scripts/ci/octelium-restore-drill-test.py`.
Nix, PostgreSQL 14.23, kubectl/yq rendering, full repository validation,
application startup, real S3/IAM checks and live enforcement were not run.
Socket-only PostgreSQL disables listening TCP; it does not prove outbound
containment. The test servers stopped before this exercise finished.

## Recovery-readiness assessment

| Concern | Source or synthetic evidence | Remaining acceptance gate |
| --- | --- | --- |
| Capture and failure domain | Main `clusters/homelab/apps/octelium-storage/backup-cronjob.yaml` declares daily 02:30 UTC password-free globals and custom dump, archive listing and SHA-256 checks before/after atomic rename. Both database and backup use QNAP-backed `nfs-default`. | Confirm any existing operator-managed independent copy before provisioning another destination; retrieve a specific independent version. NAS-loss recovery is not established. |
| Freshness | HOME-2 preserves capture time, rejects stale/future input, verifies exact downloaded versions before completion. Candidate alert fires on missing/failed checks, capture age over 30h, or checker age over 2h, with a 15m hold. | Source timestamps and mocks do not show today's backup age. Deploy/scrape/deliver alerts only after approval; HOME-4 owns independent monitoring-loss detection. A 30h alert threshold does not enforce a 24h RPO. |
| Integrity | Real fixture restore and corruption/path/wrong-version tests pass. | Checksums cannot establish archive authenticity against an actor able to replace both data and manifest. Validate destination controls and private version provenance. |
| Retention | Main prunes completed timestamp directories older than 13 days and partials older than one day only after successful publication checks. HOME-2's plan protects newest seven sets; its proposed bucket retains completed versions indefinitely and publication policy denies deletion. | Main's pruning was source-reviewed, not executed in this exercise; it has no seven-copy floor or independent-copy prerequisite. No deletion is authorized. Review capacity and retention separately; do not mistake a plan for deletion approval. |
| Secrets | Main `externalsecret.yaml` references `/homelab/octelium/postgres-password` and `/homelab/octelium/redis-password`. Dumps omit role password hashes; SQL checks require wrapped keys. | Independently recover matching DB/Redis auth, external root/encryption material, operator/AWS/KMS access and Entra/Octelium identity bootstrap. Verify private custody/version records without publishing values or rotating keys during restore. |
| Whole application | SQL resources, wrapped-key linkage, metadata and indexes tested; proposal round trip also checks synthetic blob linkage. | Octelium startup, encrypted-resource decryption and representative identity/resource behavior remain untested. PostgreSQL excludes Redis AOF and Enterprise package stores; no loss budget for these was approved. |
| Isolation | Main candidate is outside live kustomization and suspended. It copies only the selected recovery files to scratch and never mounts the production DB. | HOME-3's verified no-network process boundary must cover archive-triggered children, node/LAN/public IPv4/IPv6 and DNS paths with reachable controls. Deny-all YAML is insufficient. A real independent-copy drill needs a reviewed selected-set entry point instead of mounting the normal backup PVC. |

Nominal database RPO is 24h; HOME-2 proposes a 4h Octelium RTO. These remain
unratified/unmeasured targets, not achieved service levels. RPO uses the recovered
capture timestamp; RTO starts at incident declaration and includes approval,
retrieval, infrastructure, secrets and application behavior. The 2.33s synthetic
round trip is only local test timing.

## Exact next approval and acceptance

This documentation change has no runtime rollout. Review HOME-2's current-main
integration, selected destination and operator-managed-copy inventory first.
Before any implementation activation, Rodman must approve the concrete reviewed
bucket/cost and scoped publisher/reader grants, operator host and read-only
source mounts, scheduler and monitoring changes. HOME-3 must supply verified
containment; HOME-4 must supply scraping and independent outage detection.
Existing proposal ownership is retained; this exercise creates no duplicate
backup, network or monitoring implementation.

A later sensitive-data drill requires a separate approval naming the immutable
code/image/tool revisions, exact source set/object versions in a private record,
authorized recovery identity, verified isolated host/launcher, bounded scratch
capacity and duration, private secret-custody procedure and diagnostic handling.
The reviewed entry point must accept only that selected set, use no production
PVC, withhold outbound callbacks and fail closed on any integrity or containment
failure. No unspecified real-data restore is authorized by HOME-21.

Acceptance must record capture/retrieval/start/end times, exact versions and
hash checks privately, production-matched PostgreSQL restore, preserved globals
and SQL invariants, actual Octelium startup/decryption/identity behavior, and
measured RPO/RTO. Redis/packages need restored data or an explicit accepted loss.
Any production cutover needs its own writer-fencing and rollback approval.

For a failed future drill, stop through the reviewed launcher, retain source
versions and protected private evidence, and leave production writers untouched.
For publisher rollback, disable future timer executions through reviewed host
configuration and revert only new scrape/rule references; preserve local partials,
completed remote versions, bucket, old NFS jobs and claims. Do not destroy the
bucket, prune retained data or remove it from state as rollback.

Sources: [Octelium storage runbook](../../../clusters/homelab/apps/octelium-storage/README.md),
[[architecture/storage-and-state]], [[architecture/secrets-and-identity]],
[[operations/validation-gates]], and `docs/application-recovery.md` at the
HOME-2 revision above (not yet on main).
