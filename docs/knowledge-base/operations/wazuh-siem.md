# Wazuh SIEM (deferred)

Tags: #security #logging #wazuh #operations

Wazuh is deferred at the operator's request until a hardware upgrade provides
sufficient capacity. Its deployment, collectors, secret, access and storage
declarations are removed from active desired state. The runtime was never
deployed; no SIEM ingestion, backup or restore was accepted.

## Remove the staged control-plane records

The empty `argocd-application-retired` module keeps the original encrypted
`live/argocd-apps/wazuh` state address until cleanup completes. It cannot recreate
the Application. A targeted protected workflow removes only that Application,
the four generated `/homelab/wazuh/` credentials and their reader permissions:

```sh
gh workflow run terragrunt-apply.yml --ref main \
  -f expected_sha=<full-reviewed-main-sha> \
  -f argocd_app=wazuh -f retire_wazuh=true
```

Both saved plans must pass strict resource checks and policy before either is
applied. Only this path supplies the policy context permitting deletion of the
four exact generated SecureStrings. Normal full and targeted applies continue
to reject these deletions until retirement completes; other secret deletions
and replacements remain blocked.
Cleanup refuses an enabled Application, an active operation, finalizers
or any Wazuh namespace, volume or collector permissions. Unrelated state drift
also stops cleanup. Investigate failures through reviewed code changes; do not
delete resources manually or remove state records to bypass the checks.

Success verifies the Application and runtime resources are absent, the old
Application state is empty, and no Wazuh credential metadata remains in SSM.
The workflow uses a `Retire wazuh @` title so it cannot advance the full-stack
apply checkpoint. It is safe to rerun after partial completion. No Talos rollback
is needed: the staged logging and indexer patches were never applied.

## Restore after a hardware upgrade

Removal verification for [PR #1177](https://github.com/Stuhlmuller/homelab/pull/1177)
encountered node disk-pressure eviction of an existing source workload. Its
controller recovered it, but node disk pressure remained a capacity finding.
Resolve that pressure and verify healthy source workloads across a restart
before restoring collectors; a successful rollout alone does not prove headroom.

Historical implementation:

- [PR #1153](https://github.com/Stuhlmuller/homelab/pull/1153) introduced the
  staged Wazuh stack, full-log collection and protected deployment paths.
- [PR #1169](https://github.com/Stuhlmuller/homelab/pull/1169) strengthened
  capacity checks and aligned dashboard placement with the central-node budget.

Restore through a new reviewed change after the hardware upgrade. Recheck
memory, disk and inode headroom on every collector node, including image
downloads, unpacking and queue growth. Refresh image versions and secret,
storage, access and source contracts before applying the historical design.
Require verified image publication, private UI access, per-source ingestion,
backup and restore evidence before claiming the SIEM is operational.
Recreate credentials through the declared secret workflow; removed credentials
and any previously cached image layers are not a supported rollback mechanism.

Related: [[../architecture/gitops-flow]], [[../architecture/storage-and-state]],
[[../architecture/secrets-and-identity]], [[../workloads/inventory]].
