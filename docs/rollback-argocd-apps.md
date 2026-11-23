# Argo CD App Rollback

Rollback dependent services before shared foundations. For Terragrunt-driven
registration rollback, remove or disable the downstream Application first, run
`terragrunt run --all plan -no-color`, then apply only after persistent data
handling is clear.

## Order

1. AFFiNE
2. Policy Bot
3. OpenClaw
4. n8n
5. n8n-postgres
6. Radarr and Sonarr
7. Prowlarr
8. media-postgres
9. LiteLLM
10. Langfuse
11. Deluge
12. Grafana
13. Descheduler
14. Prometheus
15. platform-storage
16. Tailscale
17. Istio
18. cert-manager
19. external-secrets
20. platform-dns

## cert-manager v1.20.3

The `v1.19.2` to `v1.20.3` update is one supported minor-version step. In the
aggregate `cert-manager-edit` role, it removes `create` access to Challenges
and Orders plus `patch` and `update` access to Orders. External tooling that
uses those operations needs its own reviewed RBAC before rollout.

The Application uses `v1.20.3` with `values-v1.20.3.yaml`. The unused
v1.19.2 `values.yaml` has been removed. Back up cert-manager API resources before
a rollback. Restore the v1.19.2 chart revision and its matching `values.yaml`
from the pre-upgrade revision `1cbea323^` in a reviewed change, then apply through
the same Terragrunt workflow.
Do not reuse the v1.20.3 image digests with the older chart. Do not
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
directly. Follow
[archived runbook](https://github.com/Stuhlmuller/homelab/blob/3b2256219bcc0cb70596a94fc17e66491e284a9f/clusters/homelab/apps/media-postgres/README.md#backup-and-restore), require the
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

For Langfuse, stop LiteLLM callbacks first, preserve the PostgreSQL, Valkey,
and ClickHouse claims, and retain the S3 bucket. Reverting the chart does not
roll back database migrations or recover raw event bodies already expired by
the 30-day lifecycle; restore the three stores from a coordinated NAS backup
before returning to an older Langfuse release.

n8n public webhook exposure is independent of its stored workflow data. Remove
`n8n-webhook-octelium`, its `octelium-public` tunnel/DNS hostname, and the
public `WEBHOOK_URL` first, then roll back the app while preserving both n8n
PVCs unless intentionally rebuilding from exports.

Policy Bot is stateless. Roll back its public exposure by removing the
`policy-bot-webhook-octelium` route and its `octelium-public` tunnel/DNS
hostname first, then roll back the Deployment and ExternalSecret if the GitHub
App should stop evaluating pull requests.

Kiali is stateless. Disabling `cr.create` lets Argo CD prune the Kiali custom
resource while the operator is still running. Apply the Application
registration through targeted Terragrunt Apply to install the Argo CD
cascading-deletion finalizer. Confirm that the Kiali custom resource and the
server Deployment and Service are absent before removing the Terragrunt unit.
Dispatch Terragrunt Apply with `retire_argocd_app=kiali` to delete the
Application and let Argo CD prune the remaining operator resources.

## Emergency Recovery

Keep rollback code-first during incidents: revert or correct repository-owned
desired state, validate it, then apply through the documented Terragrunt or
GitOps path. Do not mutate live resources and backfill afterward. Add and review
a missing recovery code path before using it.
