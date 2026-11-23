# Home Assistant

Home Assistant Container runs one instance on Talos. Its ClusterIP
service listens on port 8123. Access requires permission to port-forward
in the `home-assistant` Kubernetes namespace.

```sh
kubectl -n home-assistant port-forward svc/home-assistant 8123:8123
```

Open <http://localhost:8123> and complete Home Assistant onboarding.
To verify the frontend before onboarding, request `/` using the same tunnel.

The workload uses standard pod networking. Integrations that require
LAN multicast discovery, a local Bluetooth adapter, or USB radios need
additional networking or hardware configuration. Integrations that
support direct device addresses can be configured in Home Assistant.

The retained `home-assistant-config` claim stores `/config`, including
the SQLite recorder and authentication state, on `zimaboard-0`. A single
replica and Recreate updates keep one writer on the local filesystem.
The claim survives application pruning or deletion. In Home Assistant,
create and download backups under **Settings → System → Backups**. Store
the backup and its emergency kit away from the node. Restore a downloaded
backup during onboarding on a replacement installation if the disk is lost.

Roll back application changes with a reviewed Git revert. Check compatibility
before starting an older version against upgraded configuration or recorder
state. Use a pre-upgrade backup if a downgrade needs older data.

Publish the pinned image through Harbor before activating the Application.
The registration uses the targeted Terragrunt apply workflow.
Verify that Argo CD has reconciled the new namespace in the live
`homelab` AppProject before registering the workload.
