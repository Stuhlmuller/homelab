# Prometheus Storage Profile

Prometheus persists metrics and Alertmanager state on `nfs-default`.

- Backup: covered by the NFS backup gate in `docs/storage-nfs.md`.
- Restore: restore Prometheus and Alertmanager PVCs before relying on retained
  metrics.
- Rollback: preserve PVCs unless the operator accepts metrics loss.

## Ingress

Prometheus is intentionally not exposed through the tailnet ingress gateway.
Grafana remains the reviewed operator UI for metrics and reads Prometheus over
the in-cluster service URL configured in `clusters/homelab/apps/grafana`.

Do not add a Prometheus `VirtualService` until the access path has a reviewed
authentication story, an owner, and a rollback note. If temporary direct access
is required for an incident, prefer a short-lived operator port-forward after
read-only diagnosis and record the reason in the PR or incident notes.
