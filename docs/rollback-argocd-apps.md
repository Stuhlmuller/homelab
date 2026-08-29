# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. AFFiNE
2. Policy Bot
3. OpenClaw
4. OctoBot
5. n8n
6. n8n-postgres
7. Radarr and Sonarr
8. Prowlarr
9. media-postgres
10. LiteLLM
11. Deluge
12. Kiali
13. Grafana
14. Descheduler
15. Prometheus
16. platform-storage
17. Tailscale
18. Istio
19. cert-manager
20. external-secrets
21. platform-dns

## cert-manager v1.20.3

The `v1.19.2` to `v1.20.3` update is one supported minor-version step. In the
aggregate `cert-manager-edit` role, it removes `create` access to Challenges
and Orders plus `patch` and `update` access to Orders. External tooling that
uses those operations needs its own reviewed RBAC before rollout.

The v1.20.3 values are staged in `values-v1.20.3.yaml`; the live v1.19.2
Application continues using `values.yaml` until the reviewed Terragrunt apply
changes its chart revision and values path together. Back up cert-manager API
resources before that apply. To roll back, restore both the v1.19.2 chart
revision and `values.yaml` path through the same Application apply. Do not
delete cert-manager CRDs, Certificate, CertificateRequest, Issuer,
ClusterIssuer, Order, Challenge, or generated TLS Secret resources. Verify all
Issuers report Ready and existing Certificates remain Ready after either
direction.

## Persistent Data

Never delete PVCs as part of rollback unless the operator explicitly chooses
data removal. For persistent apps, snapshot or verify NFS backup coverage before
removing Application registration.

For `media-postgres`, take PostgreSQL logical dumps before rollback whenever
Sonarr, Radarr, or Prowlarr have already written data to PostgreSQL. Preserve
the PostgreSQL PVC unless intentionally rebuilding the media apps from backups.

Preserve both `media-postgres-local` and `data-media-postgres-0`. The retained
NFS physical copy became stale when local writes began; use the repository-owned
`media-postgres-recovery` logical restore overlay instead of mounting that copy
directly. Never run the local and NFS PostgreSQL copies at the same time behind
the `media-postgres` Service. A normal Git revert to the read-only cutover
revision is not a post-write rollback. Follow
`clusters/homelab/apps/media-postgres/README.md#backup-and-restore`, require the
recovery Job to be `Complete`, and use a separate reviewed revision to return
the Application to the writable base overlay.

For `n8n-postgres`, take a PostgreSQL logical dump before rollback whenever n8n
has already written workflows, users, credentials metadata, or execution
history to PostgreSQL. Preserve both the PostgreSQL PVC and the n8n
`/home/node/.n8n` PVC unless intentionally rebuilding from exports.

For AFFiNE, take a PostgreSQL logical dump and coordinated NFS backup before
rollback. Preserve the PostgreSQL, Redis, blob-storage, and config claims, and
do not rotate `/homelab/affine/private-key`; changing that ECDSA key invalidates
sessions and can make encrypted application data unreadable. AFFiNE `0.27.0`
removes legacy permission and subscription database structures during
migration. Do not run `0.26.x` against a database migrated by `0.27`; restore
the pre-upgrade PostgreSQL dump and coordinated blob/config backup before
restoring the older image.

n8n public webhook exposure is independent of its stored workflow data. Remove
`n8n-webhook-octelium`, its `octelium-public` tunnel/DNS hostname, and the
public `WEBHOOK_URL` first, then roll back the app while preserving both n8n
PVCs unless intentionally rebuilding from exports.

Policy Bot is stateless. Roll back its public exposure by removing the
`policy-bot-webhook-octelium` route and its `octelium-public` tunnel/DNS
hostname first, then roll back the Deployment and ExternalSecret if the GitHub
App should stop evaluating pull requests.

Kiali is stateless. Remove the Kiali custom resource before removing the
operator chart so the operator can clean up its managed server resources.

## Break-Glass

Direct live mutation is break-glass only. Any live rollback action must be
backfilled into this repository before the incident is considered closed.
