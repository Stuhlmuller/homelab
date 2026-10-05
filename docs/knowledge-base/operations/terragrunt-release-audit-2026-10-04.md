# Terragrunt Refactor Release Audit

Tags: #operations #terragrunt #gitops

## Scope

[PR #1181](https://github.com/Stuhlmuller/homelab/pull/1181) preserves all
42 generated Application-unit inputs, state paths, module sources, and ordered
dependencies relative to main `71f9424b`. All 41 Application manifests are
unchanged. This is a source refactor; applying identical desired state is not
needed to activate it. See [[operations/terragrunt-dry-refactor-2026-10-04]].

## Existing Live Findings

Read-only inspection on 2026-10-04 found 45 Healthy Applications, 44 Synced.
LiteLLM already reports OutOfSync for `ExternalSecret/litellm-app-keys`.
Investigate the ExternalSecret contract and controller status in a separate
change; do not patch its live object.

During final verification, Harbor changed from Healthy to Progressing while
remaining Synced. Its `harbor-vulnerability-exporter` pod was running with zero
restarts but failing readiness. Kubernetes events showed readiness HTTP 503s
since 01:55 UTC and metrics timeouts since 02:00 UTC on October 4, before this
refactor merged at 23:54 UTC. The pod was created at 01:54 UTC; no new Harbor
Argo operation accompanied this audit. Investigate exporter request latency,
Harbor API response time, and probe settings through its manifests and the
normal protected change workflow. Harbor recovered naturally: at the final
00:03:52 UTC read, all 45 Applications were Healthy, 44 Synced, and no operations
were active. LiteLLM retained its pre-existing OutOfSync status.

Actual encrypted-state refresh plans found these pre-existing differences:

- `istio`: the live ztunnel source lacks the committed issuer-cutover Pod label
  and rolling update settings (`maxSurge=0`, `maxUnavailable=1`). These settings
  came from [PR #951](https://github.com/Stuhlmuller/homelab/pull/951), commit
  `2711405f7d8dbb4be07b738f676c92f590afb8de`, on September 2 local time.
  Reconciling this Application would trigger a networking rollout. Review and
  validate that rollout separately through the protected exact-app apply path.
- `platform-dns`: only historical Application information text differs, from
  [PR #1002](https://github.com/Stuhlmuller/homelab/pull/1002), commit
  `667156f7`. Reconcile with the next intentional DNS registration change.
- `n8n-postgres`: provider output normalizes an omitted empty namespace
  annotations map. Its desired Application manifest is unchanged.

The last successful full Terragrunt Apply checkpoint is
[run 33680144179](https://github.com/Stuhlmuller/homelab/actions/runs/33680144179),
commit `82ebd734ad61357faa0f03212613ef15f593ff80`. A new full apply would include
unrelated bootstrap, shared cloud/secret declarations, and deleted-unit
reconciliation since that checkpoint. Review those plans separately before
advancing the full checkpoint. Targeted runs do not advance it.

## Release Verification

PR #1181 merged as `15fa3f1862e1f4fecb2331ff8c3bf41d1b0bb10d`. The verified
squash commit has sole parent `71f9424b`; its tree exactly matches the reviewed
and tested `ac0e77f4` tree. All required PR checks passed, including the
[protected live plan](https://github.com/Stuhlmuller/homelab/actions/runs/37244481974).

All 41 independent encrypted-state Application plans completed successfully:
38 no-op and the three historical in-place updates described above. All 2,296
Conftest plan checks passed; no creates, deletes, or replacements were proposed.
The plans excluded Wazuh retirement, cloud units, and secret units. Temporary
raw plans, cache, and logs were removed after retaining sanitized findings.

At 2026-10-05 00:00:20 UTC, all 41 repository-backed Applications observed the
merged revision at every relevant Git-source index. The four additional
Applications retain their separate lifecycle owners. No new runtime manifest,
chart version, image digest, or registration desired state was introduced, so
no infrastructure apply was necessary.

No live mutation, import, untaint, forced sync, or Application apply was used
for this audit. The superseded NOFX publication run `37191599441`, waiting on
production approval for an older commit, was canceled to unblock the current
commit's automatic test/build queue.

The post-merge NOFX test/build job in
[run 37245422470](https://github.com/Stuhlmuller/homelab/actions/runs/37245422470)
also passed. Its production publication wait was canceled because this refactor
changes no image inputs or consuming digests; no publication was needed. The
workflow's canceled overall status does not represent a failed test/build job.

The PR #1181 audit above was written after that merge and is included with the
subsequent IaC cleanup.

## Application Folder and Provider Lock Release

[PR #1186](https://github.com/Stuhlmuller/homelab/pull/1186) extracts 42 Application
input files and removes 63 committed provider locks. All 58 unit identities and
state paths, 100 generated HCL/value files, and selected provider versions are
preserved. The provider checksum tradeoff is recorded in
[[operations/terragrunt-dry-refactor-2026-10-04#Provider Lock Policy Update]].

The pre-release read at 2026-10-05 05:48:45 UTC found 45 Applications:
41 Healthy/Synced, LiteLLM and Multica Healthy/OutOfSync, and n8n and OpenClaw
Degraded/Synced. Multica had a Running operation. These findings predate this
source-only release; compare them again after merge rather than attributing
existing runtime failures to the stack split. The release acceptance check
requires all 41 repository-backed Applications to observe the merged revision.
