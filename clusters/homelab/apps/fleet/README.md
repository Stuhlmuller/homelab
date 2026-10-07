# Fleet family device management

Fleet Free runs at `https://fleet.stinkyboi.com` in namespace `fleet`, with
one Fleet server, dedicated MySQL 8.4 and Redis 7.2. Images are digest-pinned.
Registration inputs live in `IaC/stacks/fleet/stack.hcl`, indexed by
`IaC/terragrunt.stack.hcl`; Argo CD follows `main`.
No Fleet Premium license or subscription is provisioned.

The [Fleet Free and Entra runbook](FREE-ENTRA.md) owns native Microsoft Mac
Platform SSO, separate console SAML, Mac and iPhone/iPad passcode profiles,
platform reporting limits, and the interactive acceptance checklist. Profiles live in `profiles/`;
`scripts/fleet-free-setup.py` applies them through supported Free APIs. These
application/device settings are a repository operator step after protected merge,
not Kubernetes resources that Argo CD can apply itself.

The [WireGuard/AirVPN catalog and operator](WIREGUARD-AIRVPN.md) cover official
Mac and iPhone/iPad app downloads, a Mac installation policy, and private
per-device VPN profiles from owner-supplied configurations. Fleet Free requires
the App Store installation step; VPN profiles are provisioned separately.

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
  use **Hosts > Add hosts > macOS > Personal (BYOD)** for a family Mac.
  This Free flow opens `/enroll` and downloads its profile through
  `/api/v1/fleet/enrollment_profiles/ota`. The administrator endpoint
  `/api/v1/fleet/enrollment_profiles/manual` returns HTTP 402 without Premium;
  do not substitute it for personal enrollment. iOS/iPadOS enrollment still
  needs its own device acceptance check.
- Windows: inventory uses fleetd; Windows MDM additionally needs Fleet's
  [Windows MDM setup](https://fleetdm.com/guides/windows-mdm-setup) and WSTEP
  signing identity. Add its secret references and file paths through GitOps
  before enabling that platform. No signing certificate is fabricated here.
- Android: complete Fleet's [Android MDM setup](https://fleetdm.com/guides/android-mdm-setup)
  with a work-domain Google account (personal `@gmail.com` is not supported by
  the documented registration) before creating work profiles. Enrollment and managed
  app availability follow Fleet's current Free/Premium capabilities.
- Linux: fleetd inventory, queries and supported scripts; no Apple-style MDM.

Deploying the server does not automatically enroll, reset, wipe, or change a
family device.
Enroll one consenting test device and verify inventory plus a reversible
configuration profile before rolling out family-wide. Platform certificates,
provider account setup and an actual enrolled-device check are separate from
server readiness.

Vulnerability-feed scanning is initially disabled to keep this small MDM
deployment within the cluster's memory and disk budget. Enabling it requires
reviewed capacity for its downloaded databases. Fleet enables optional analytics
by default; its administrator controls that setting in Fleet. Bootstrap does not
overwrite application settings on subsequent syncs.

### Prepare Apple enrollment

The repository-owned helper downloads Fleet's vendor-signed APNs certificate
request without requiring an Apple login:

```sh
python3 -I scripts/fleet-download-apple-csr.py \
  --output /tmp/fleet-mdm-apple.csr
```

It authenticates using the initial administrator Secret, keeps credentials in
memory and revokes its session. It refuses to overwrite an existing output.
After changing the initial password, use Fleet's **Settings > Integrations >
MDM > Turn on > Download CSR** flow instead.

Generating the CSR creates encrypted SCEP/APNs keys in Fleet's database on the
first request; subsequent requests reuse the keys. Fleet sends the public CSR,
including the configured organization and administrator email, to its vendor
signing service. No private key is downloaded or emailed. Preserve the database
and server encryption key throughout this setup.

Sign in to [Apple Push Certificates Portal](https://identity.apple.com/pushcert/),
create a certificate using `fleet-mdm-apple.csr`, then upload the downloaded
APNs `.pem` in Fleet's Apple MDM setup flow. Keep both files outside git. This
provider-account step cannot be replaced by a self-signed certificate.

For first activation, the same repository-owned helper can upload the issued
certificate through Fleet's setup API:

```sh
python3 -I scripts/fleet-download-apple-csr.py \
  --certificate '/absolute/private/path/Certificate.pem'
```

The command validates the PEM input, requires Apple MDM to be disabled, uploads
only the certificate, verifies the enabled flag and APNs metadata, and revokes
its session. Fleet checks that the certificate matches its stored private key.
The key and certificate remain encrypted application data in MySQL; this step
does not change Kubernetes Secrets or put certificate material in git. If MDM
is already enabled, use Fleet's **Renew certificate** flow with the same Apple
account instead of replacing the integration. A failed verification after
upload may still mean activation succeeded; inspect Fleet before retrying.

After activation, enroll one selected device, require MDM **On**, refresh its
inventory through the public endpoint, and verify installation and removal of
an agreed harmless configuration profile. CSR generation alone neither enables
MDM nor enrolls a device.

On macOS, read `profiles status -type enrollment` outside the agent sandbox
through an approved local read-only session. Sandboxed execution can falsely
report **No** despite active enrollment. Correlate the local serial and hardware
UUID with the exact Fleet host privately; hostname or another online Mac is not
sufficient evidence. Keep those identifiers out of git. A Fleet profile status
of **verifying** records installation acknowledgement while independent profile
verification remains incomplete.

### Verify reversible profile delivery on this Mac

Run the repository-owned verifier on the selected enrolled Mac, outside the
agent sandbox when necessary for accurate local hardware identity:

```sh
# Preview only: no credential reads or API requests.
python3 -I scripts/fleet-verify-apple-mdm.py
# Send commands to this exact Mac only.
python3 -I scripts/fleet-verify-apple-mdm.py --execute
```

Execution privately matches both local serial and hardware UUID to exactly one
Fleet Mac. It installs a unique removable profile setting only `SmokeTest=true`
in an unused preference domain, verifies presence, then attempts removal in
`finally`. Acceptance requires its absence, retention of every pre-existing
profile and API session revocation. If cleanup fails or is unconfirmed, inspect
this Mac's **Fleet temporary MDM verification** profile; do not claim success or
blindly rerun the test.

The verifier shares the CSR helper's initial administrator Secret contract.
After that password changes, a reviewed authentication path is required before
using this verifier again; it does not reset credentials. Adding or previewing
the helper does not complete the live acceptance gate recorded below.

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

For first installation, publish the new image digests before registering the
application. Talos uses Harbor with upstream fallback disabled.
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

## Deployment acceptance: 2026-10-03

The [scoped mirror](https://github.com/Stuhlmuller/homelab/actions/runs/37157590653),
[targeted apply](https://github.com/Stuhlmuller/homelab/actions/runs/37158855174)
and [DNS reconciliation](https://github.com/Stuhlmuller/homelab/actions/runs/37159252098)
succeeded at reviewed main `df9dc622`. Fleet 4.92.2, MySQL 8.4.11 and Redis
started with zero restarts. All five ExternalSecrets were Ready and all three
PVCs Bound. The live MySQL packet limit is 536870912 bytes.

Public TLS, health/version, administrator login, configured server URL and
authenticated host listing passed; the verification session was revoked.
The browser rendered the login form. All public setup aliases returned 404.
The initial backup Job completed and published the checksum-verified set
`fleet-20261003T224520Z`. That initial server check found one administrator and
zero devices; the later device evidence follows below. Nightly recurrence,
offsite recovery and restore testing remain separate acceptance gates.

External Secrets defaults are explicit because omitted remote-reference,
refresh-interval and template-merge defaults caused Argo to repeat self-healing
despite healthy workloads. Declaring the defaults preserves secret semantics.

### Apple activation and device acceptance: 2026-10-03

[PR #1148](https://github.com/Stuhlmuller/homelab/pull/1148) merged as
`19c34578`; the repository-owned helper activated Apple MDM and verified its
APNs certificate renewal date as `2027-10-03T23:22:43Z`. Certificate and secret
material remain outside git.

The selected Mac completed the Free personal enrollment flow. An approved
local read outside the sandbox confirmed **MDM enrollment: Yes (User Approved)**
and the public Fleet enrollment URL with `byod=1`. Its serial and hardware UUID
matched the online Fleet host; inventory reported macOS 26.6.2 and osquery
5.23.1. The acceptance below applies only to that exact Mac.

A `DeviceInformation` query for `OSVersion` targeted only the matched Mac through
Fleet's `/api/v1/fleet/commands/run` API. Its fresh command moved from **Pending**
to **Acknowledged** within three seconds. Host identity, request type and command
UUID matched the response, which reported `OSVersion: 26.6.2`. This verifies a
live APNs/MDM query round trip.

The repository-owned reversible profile test then passed with exit status 0 in
about 14 seconds. Its five commands read the baseline profile inventory,
acknowledged installation, confirmed the temporary profile was present,
acknowledged removal, and confirmed absence while retaining every baseline
profile. API session revocation also succeeded. This completes profile
install/remove acceptance for the selected Mac.

One earlier baseline `ProfileList` remained pending beyond the helper's
90-second timeout; that attempt installed nothing. Queued at `00:33:15 UTC`,
the read and a fresh `DeviceInformation` query were both acknowledged at
`00:41:20 UTC`, without routing, service or device changes. The one-time push
delay's cause is unconfirmed. Compare agent heartbeat with MDM last check-in
and command acknowledgements when diagnosing delays; do not duplicate writes
while a command remains pending.

The iOS record now reports manual MDM **On** and a verified Fleet root CA,
but its inventory remains blank. iOS inventory and command acceptance remain
pending; the selected Mac's passing test does not establish iOS readiness.

Upstream references: [hosting](https://fleetdm.com/docs/deploy/deploy-fleet),
[configuration](https://fleetdm.com/docs/configuration/fleet-server-configuration),
[v4.92.2 source](https://github.com/fleetdm/fleet/tree/fleet-v4.92.2).
