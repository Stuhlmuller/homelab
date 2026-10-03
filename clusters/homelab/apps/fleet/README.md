# Fleet family device management

Fleet Free runs at `https://fleet.stinkyboi.com` in namespace `fleet`, with
one Fleet server, dedicated MySQL 8.4 and Redis 7.2. Images are digest-pinned.
The source is registered in `IaC/terragrunt.stack.hcl`; Argo CD follows `main`.
No Fleet Premium license or subscription is provisioned.

## Scope and enrollment

Fleet's [Free/Premium matrix](https://fleetdm.com/pricing) distinguishes basic
inventory, manual enrollment, configuration profiles and scripts from paid
app deployment, remote lock/wipe, update enforcement and automated Apple
Business Manager enrollment. Verify the matrix before promising a device
control: self-hosting does not unlock Premium features.

The initial administrator is `rodman@stuhlmuller.net`. The password is generated
in `/homelab/fleet/admin-password` in AWS SSM (`us-west-2`), never in git or
Job logs. Retrieve it privately through the approved secret access path and
change it in Fleet after first login. Repeated bootstrap Jobs preserve existing
users and passwords. SMTP is not configured; password-reset email is therefore
not an available recovery path yet.

- Apple: follow Fleet's [Apple MDM setup](https://fleetdm.com/guides/apple-mdm-setup).
  An Apple account must sign in to Apple's Push Certificates Portal to obtain
  the APNs certificate. Upload it through Fleet's setup flow, retain the same
  Apple account, and renew the same certificate annually. Manual family/BYOD
  enrollment does not require Apple Business Manager. Enable MDM first, then
  use Fleet's **Add hosts** flow for macOS, iOS and iPadOS.
- Windows: inventory uses fleetd; Windows MDM additionally needs Fleet's
  [Windows MDM setup](https://fleetdm.com/guides/windows-mdm-setup) and WSTEP
  signing identity. Add its secret references and file paths through GitOps
  before enabling that platform. No signing certificate is fabricated here.
- Android: complete Fleet's [Android MDM setup](https://fleetdm.com/guides/android-mdm-setup)
  with a work-domain Google account (personal `@gmail.com` is not supported by
  the documented registration) before creating work profiles. Enrollment and managed
  app availability follow Fleet's current Free/Premium capabilities.
- Linux: fleetd inventory, queries and supported scripts; no Apple-style MDM.

This deployment does not enroll, reset, wipe, or change any family device.
Enroll one consenting test device and verify inventory plus a reversible
configuration profile before rolling out family-wide. Platform certificates,
provider account setup and an actual enrolled-device check are separate from
server readiness.

Vulnerability-feed scanning is initially disabled to keep this small MDM
deployment within the cluster's memory and disk budget. Enabling it requires
reviewed capacity for its downloaded databases. Fleet enables optional analytics
by default; its administrator controls that setting in Fleet. Bootstrap does not
overwrite application settings on subsequent syncs.

## Public access and authentication

```text
family device/browser -> Cloudflare Tunnel (octelium-public)
                      -> Istio TLS gateway -> Fleet:8080
                      -> Fleet user/device authentication
```

This is an explicit native-client ingress exception. MDM check-ins and fleetd
cannot follow an Octelium browser-login redirect. A single stable hostname
serves the UI, enrollment and management protocols through the existing
outbound tunnel. There is no router port forwarding or Tailscale Funnel.
Cloudflare sees the HTTPS request content at its edge; database and cache ports
remain private. Fleet user login, enrollment secrets, enrolled-device identity
and MDM protocol authentication protect application operations.

Istio permanently returns 404 for `/setup`, `/setup/`, `/api/setup` and
`/api/v1/setup` prefixes. Both upstream API aliases must remain blocked even
after setup or a database restore. A separate `fleet-bootstrap` ServiceAccount
may reach Fleet internally to create the first administrator. Its PostSync Job
reads only the administrator Secret, verifies authentication and revokes its
temporary session. It never resets an existing account. Default-deny mesh and
network policies constrain Fleet, datastore and bootstrap access.

## Secrets and storage

OpenTofu generates these SSM SecureStrings through the shared
`IaC/live/aws-ssm-parameters` unit:

| Parameter under `/homelab/fleet/` | Purpose |
| --- | --- |
| `mysql-password` | Application database user and logical backup |
| `mysql-root-password` | MySQL initialization; not mounted in Fleet |
| `redis-password` | Dedicated cache authentication |
| `server-private-key` | Stable 32-byte Fleet encryption key |
| `admin-password` | Initial human administrator only |

External Secrets templates a mounted Fleet YAML configuration and separate
database, cache, backup and bootstrap secrets. Fleet's MySQL password uses
`password_path`. No plaintext credential is placed in an argument or environment
variable. The official MySQL image's `MYSQL_ROOT_PASSWORD_FILE` contains only
a mounted-file path, its supported file-backed secret initialization contract.

MySQL and Redis use retained `nfs-default` PVCs. MySQL owns accounts, device
inventory, enrollment identity and MDM configuration; Redis retains coordination
and queued state. Preserve the database together with the server encryption
key, SSM values, APNs certificate/key and any later Windows/Android identities.
Changing only an SSM database password does not rotate an existing MySQL user.
MySQL and the dump client both allow 512 MiB packets for stored MDM packages.

A nightly CronJob at 03:45 America/Los_Angeles writes a transaction-consistent
MySQL dump plus SHA-256 checksum to a separate retained NFS backup claim and
retains 14 days. Each verified set is published atomically as
`fleet-YYYYMMDDTHHMMSSZ/fleet.sql` and `fleet.sql.sha256`. Failed, empty or
incomplete dumps are never published; pruning runs only after success. A
PostSync Job runs the same backup after administrator bootstrap on each sync;
its completion and retained logs verify the first backup during rollout.
This protects against logical mistakes; it
shares the QNAP failure domain and is not an offsite backup. NAS durability,
an independent encrypted copy and an isolated restore drill remain acceptance
gaps. Redis AOF is retained but has no independent backup; recovery may lose
queued work, so verify MDM command state before resubmitting commands. Never
delete a claim to retry a failed rollout.

Before restore, commit Fleet and backup suspension and fence the old database
writer. Restore the selected dump into a separate empty MySQL claim through a
reviewed one-shot recovery Job, using the same secret/key set and database
version. Verify users, device identity and a test-device check-in before
declaring cutover. No automatic restore is enabled. Retain the original claim
until recovery has been verified. Do not downgrade Fleet against a database
already migrated by a newer server; restore the matching pre-upgrade backup.

## Rollout and validation

The initial application is absent from the cluster, so publish its new image
digests before registering it. Talos uses Harbor with upstream fallback disabled.
After signed protected merge of the reviewed change:

```sh
gh workflow run harbor-mirror.yml --ref main \
  -f expected_sha='<current-main-sha>' -f image_scope=fleet
# Require successful digest publication before continuing.
gh workflow run terragrunt-apply.yml --ref main \
  -f expected_sha='<current-main-sha>' -f argocd_app=fleet
# The Fleet target applies shared SSM/IAM before registering only Fleet.
gh workflow run octelium-public-tunnel.yml --ref main -f expected_sha='<current-main-sha>'
```

Review shared SSM/IAM plans for unrelated changes. Registration dependencies
order work; they do not establish upstream readiness. Require Healthy/Synced
External Secrets, Istio, storage and public-tunnel applications, a Ready
`aws-ssm` store permitting namespace `fleet`, and the `homelab` AppProject's
Fleet destination before dispatch. The scoped path avoids unrelated AzureAD
changes that currently block a full apply when Azure credentials are absent.
No manual Kubernetes or cloud mutation is needed.

The fixed Fleet mirror scope contains exactly the four images rendered by this
application. It verifies each manifest digest and a complete anonymous pull,
without processing the full homelab image history. CI rejects scope drift or
sources absent from the reviewed full inventory.

Local gates:

```sh
nix develop --command bash scripts/ci/static-checks.sh
nix develop --command bash scripts/ci/conftest-policies.sh
kubectl kustomize clusters/homelab/apps/fleet
```

Live checks after reconciliation:

```sh
kubectl -n argocd get application fleet
kubectl -n fleet get externalsecret,pvc,deploy,statefulset,pod,cronjob
kubectl -n fleet rollout status deployment/fleet --timeout=300s
kubectl -n fleet wait --for=condition=complete job/fleet-mysql-backup-initial --timeout=600s
kubectl -n fleet logs job/fleet-mysql-backup-initial
curl -fsS https://fleet.stinkyboi.com/healthz
curl -fsS https://fleet.stinkyboi.com/version
curl -sS -o /dev/null -w '%{http_code}\n' https://fleet.stinkyboi.com/api/v1/setup
curl -sS -o /dev/null -w '%{http_code}\n' https://fleet.stinkyboi.com/api/setup
```

Require ready workloads and ExternalSecrets, Bound claims, HTTP 200 health and
the pinned version, HTTP 404 for both setup aliases, and successful private
administrator login. Require the initial backup Job's successful completion and
verified-publication log. Verify the first scheduled run separately to establish
nightly recurrence. Then verify a real device enrolls and checks in from outside
the LAN.
A rendered configuration or healthy server alone does not prove MDM enrollment.

Rollback public access by reverting the Fleet tunnel/DNS/VirtualService changes
through a reviewed PR. Preserve the Fleet Application and PVCs while investigating.
For an app-version rollback, consult the release's migration notes and retain a
database backup from before the upgrade.

Upstream references: [hosting](https://fleetdm.com/docs/deploy/deploy-fleet),
[configuration](https://fleetdm.com/docs/configuration/fleet-server-configuration),
[v4.92.2 source](https://github.com/fleetdm/fleet/tree/fleet-v4.92.2).
