---
type: architecture
title: "Secrets And Identity"
description: "SSM and External Secrets ownership, credential boundaries, Entra and Cordium identities, and application recovery access."
tags: [architecture, secrets, identity]
sources:
  - id: openwiki-source-36db39acd9400bc022704939
    resource: repo://.github/workflows/cordium-runner-credentials.yml
  - id: openwiki-source-23ac5bc03d1cee79a72b06af
    resource: repo://.github/workflows/mastodon-smtp-credential.yml
  - id: openwiki-source-664c834cf8c51093d63fbef4
    resource: repo://.github/workflows/openclaw-enterprise-model-credential.yml
  - id: openwiki-source-02c6601e3ee1ac6a7a26e042
    resource: repo://.github/workflows/openclaw-enterprise-operations.yml
  - id: openwiki-source-f85a2f83ac2451fd051bfc74
    resource: repo://.github/workflows/platform-maintenance.yml
  - id: openwiki-source-50e1601d2f23b472521e5c0f
    resource: repo://builds/cordium-runner/README.md
  - id: openwiki-source-6155e2b0ac0be42ac6e4aa1d
    resource: repo://clusters/homelab/apps/cordium/nocturne-pull-secret.yaml
  - id: openwiki-source-3065a4fecdc69ba955866da5
    resource: repo://clusters/homelab/apps/cordium/runner-credentials.yaml
  - id: openwiki-source-62b4804f94bc9a36375f5db0
    resource: repo://clusters/homelab/apps/external-secrets/cluster-secret-store.yaml
  - id: openwiki-source-58caddf8069d72479935ea1e
    resource: repo://clusters/homelab/apps/fleet/FREE-ENTRA.md
  - id: openwiki-source-1e65bc7abd9e63d10fcb87dc
    resource: repo://clusters/homelab/apps/fleet/GOOGLE-LOGIN.md
  - id: openwiki-source-c9627a5536c3972ce48bf57a
    resource: repo://clusters/homelab/apps/harbor/bootstrap.py
  - id: openwiki-source-64bca48d4f10b0676e24742b
    resource: repo://clusters/homelab/apps/harbor/externalsecret.yaml
  - id: openwiki-source-caccd49b346c867666da5f50
    resource: repo://clusters/homelab/apps/harbor/harbor-pull-secret.yaml
  - id: openwiki-source-9749edd762a130f624e47007
    resource: repo://clusters/homelab/apps/harbor/kustomization.yaml
  - id: openwiki-source-6d89464fbd512a9fe7a09d90
    resource: repo://clusters/homelab/apps/harbor/vulnerability-exporter.yaml
  - id: openwiki-source-ffe9c2c54bc78625ce9efd78
    resource: repo://clusters/homelab/apps/mastodon/README.md
  - id: openwiki-source-8547ae9691c6849e109e322b
    resource: repo://clusters/homelab/apps/mastodon/runtime-externalsecret.yaml
  - id: openwiki-source-da9a8209d90a2a569457a808
    resource: repo://clusters/homelab/apps/multica/README.md
  - id: openwiki-source-846efb58b681f5ac619edfd7
    resource: repo://clusters/homelab/apps/multica/runtime/bootstrap.py
  - id: openwiki-source-584942349e9deaf323c58e09
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/externalsecret.yaml
  - id: openwiki-source-9cb199d7fd0a511b7c7d689f
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/namespace.yaml
  - id: openwiki-source-489371bb6baef577dc131a87
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/postgres-tls.yaml
  - id: openwiki-source-878d8aa0884abae2a8194701
    resource: repo://clusters/homelab/apps/openclaw-enterprise-foundation/README.md
  - id: openwiki-source-0937bc5dca6b0bf79ccdb46a
    resource: repo://clusters/homelab/apps/openclaw-enterprise-operator/rbac.yaml
  - id: openwiki-source-d2d8ff2161af78b658d004f0
    resource: repo://clusters/homelab/apps/openclaw-enterprise-operator/README.md
  - id: openwiki-source-500c19e4044fe1088cd60c0d
    resource: repo://clusters/homelab/apps/openclaw-enterprise/values.yaml
  - id: openwiki-source-c728e68797517895d00bd9f9
    resource: repo://clusters/homelab/apps/renovate/cronjob.yaml
  - id: openwiki-source-6680389f3ee90f86c4c9a782
    resource: repo://clusters/homelab/apps/renovate/externalsecret.yaml
  - id: openwiki-source-01fc0bedc522f2abd58d6698
    resource: repo://clusters/homelab/apps/renovate/README.md
  - id: openwiki-source-ce0cca7cf82efeb87c709d2b
    resource: repo://clusters/homelab/apps/tailscale/ci-rbac.yaml
  - id: openwiki-source-ae0b2b6cec91dbc3476c410b
    resource: repo://clusters/homelab/platform/tailnet-dns/README.md
  - id: openwiki-source-0a6020a0918a65bec7f9d758
    resource: repo://docs/entra-terraform-provider.md
  - id: openwiki-source-b3b14c71f8a81de8a3b71c02
    resource: repo://docs/examples/octelium/homelab-services.yaml
  - id: openwiki-source-f2b6230f4caf06e7eab9bc66
    resource: repo://docs/harbor-image-mirroring.md
  - id: openwiki-source-785c903805cb6f5a9ea9ae91
    resource: repo://docs/octelium.md
  - id: openwiki-source-8f8dab72ff0b7636d31aef4b
    resource: repo://docs/openclaw-enterprise-rollout.md
  - id: openwiki-source-f19aa740c5d820d4dd28114e
    resource: repo://docs/operator-infrastructure.md
  - id: openwiki-source-2170f836209310971c5e7b70
    resource: repo://docs/secrets-aws-ssm.md
  - id: openwiki-source-b1ffa4114052aa5dfacab93d
    resource: repo://docs/talos-control-plane-maintenance.md
  - id: openwiki-source-c2916697314c2405c38ebc73
    resource: repo://IaC/terragrunt-catalog/modules/entra-google-workspace-federation/main.tf
  - id: openwiki-source-f9b9c190e30dec01f9ffe9c9
    resource: repo://IaC/terragrunt-catalog/modules/entra-owner-mail/main.tf
  - id: openwiki-source-f6b60d0a5b2ad5df65f1b2ee
    resource: repo://IaC/terragrunt-catalog/modules/entra-owner-mail/README.md
  - id: openwiki-source-5edf712b7916c34ad7d2c410
    resource: repo://IaC/terragrunt-catalog/modules/tailscale-access/main.tf
  - id: openwiki-source-13b48922f1b929b52f4a0233
    resource: repo://IaC/terragrunt-catalog/modules/tailscale-access/README.md
  - id: openwiki-source-9d870d4d05777e4847356500
    resource: repo://IaC/terragrunt-catalog/modules/tailscale-access/variables.tf
  - id: openwiki-source-1f0ad12bbff1986d64be6620
    resource: repo://IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl
  - id: openwiki-source-96fd4f3e569f8bc04da5259d
    resource: repo://IaC/terragrunt-catalog/units/operator/entra-stuhlmuller-pilot-user/terragrunt.hcl
  - id: openwiki-source-856035e595a8b9b128dcb0a8
    resource: repo://scripts/ci/openclaw-enterprise-journal-operator.py
  - id: openwiki-source-cfb569f646f8b7c98a134fdf
    resource: repo://scripts/ci/platform-maintenance-credentials-test.py
  - id: openwiki-source-379810dcab1205ffb941d2cb
    resource: repo://scripts/ci/platform-maintenance-stage.sh
  - id: openwiki-source-d2206c7f78c1ec59c3551c13
    resource: repo://scripts/config/openclaw-enterprise.json
  - id: openwiki-source-13711977c9ca794932b4c8ee
    resource: repo://scripts/config/platform-maintenance.json
  - id: openwiki-source-87a43c568d1aa897dc611cdf
    resource: repo://scripts/config/tailscale-policy.json
  - id: openwiki-source-388dfb5b8078e3e9f29dbd62
    resource: repo://scripts/entra-owner-conversion.py
  - id: openwiki-source-45a27dbbec11da74be9f5497
    resource: repo://scripts/fleet-google-login.py
  - id: openwiki-source-1d91dece74882a3fae04c364
    resource: repo://scripts/network-policy-cleanup.py
  - id: openwiki-source-ba849f5dbd0942cee0b0087d
    resource: repo://scripts/network-policy-ownership.py
  - id: openwiki-source-7941d9a35910fdb69c63e9c1
    resource: repo://scripts/openclaw-enterprise-bind-installation.py
  - id: openwiki-source-fdfe98760ed73d2ac287a83c
    resource: repo://scripts/openclaw-enterprise-startup.py
  - id: openwiki-source-447d6bc69ac6883500089232
    resource: repo://scripts/platform-maintenance-credentials.sh
  - id: openwiki-source-6f8ea3753bc76b21d99fe402
    resource: repo://scripts/tailscale-ci-configure.py
  - id: openwiki-source-43db0977cfa60875fd0350f6
    resource: repo://scripts/talos-harbor-mirror-credential.py
  - id: openwiki-source-b4d9581a96236cc288a1836f
    resource: repo://scripts/talos-harbor-mirrors.py
  - id: openwiki-source-2031a4cf1c03de6b7fcceacb
    resource: repo://specs/004-run-renovate-in-cluster/dry-run-parity-receipt.md
  - id: openwiki-source-a44b67b396abfe9ddff04314
    resource: repo://specs/004-run-renovate-in-cluster/tasks.md
  - id: openwiki-source-111e7fc5206f50a28e4daf9c
    resource: repo://specs/005-retire-public-app-dns/contracts/cutover.md
generated: { by: "codex", at: "2026-10-23T18:25:34.713Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-24T03:50:35.181Z
---

# Secrets And Identity

## Boundary

This public repo may commit secret references, ExternalSecret names, SSM
parameter paths, non-secret defaults, encrypted material, and templates. It must
not commit secret values, kubeconfigs with private credentials, Talos secrets,
raw certificates, tokens, private SSH keys, or private keys.

Runtime app secrets are pulled from AWS SSM Parameter Store by External
Secrets. External Secrets itself uses a Kubernetes Secret created through the
`IaC/homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth` Terragrunt stack
after placeholder SSM parameters exist and real credential values are injected
outside git.

SSM SecureStrings now use AWS-managed `alias/aws/ssm` in `us-west-2`, selected
by `runtime_kms_key_id` in `IaC/root.hcl`. The OpenTofu client-side state key
remains `alias/homelab-opentofu` in `us-east-1`. See
[State Encryption](../operations/state-encryption.md) for state-bucket ownership and confidential
recovery archive retention.

## Tailscale provider foundation

The staged ingress migration uses `tailscale/tailscale` 0.29.2 in the operator-only
[`tailscale-access` module](../../IaC/terragrunt-catalog/modules/tailscale-access/README.md).
It adopts the complete existing policy before changing it; applying an additive
fragment would overwrite unrelated access. The committed policy preserves legacy
users, tags, SSH and route approvals while giving new CI tags only explicit grants.
Funnel permission is scoped to `tag:homelab-funnel` rather than every operator proxy.

The local provider reads a private administrator token file. The temporary
bootstrap token must be revoked after setup; it is never a CI secret. Encrypted
S3 state and private encrypted saved plans retain the existing KMS boundary.
Three reusable, ephemeral, preauthorized CI auth keys carry separate plan, apply
and Cordium tags and expire after 90 days. The committed generation drives
rotation every 60 days; an invalid key is not silently recreated. Tailnet Lock
requires signatures in addition to enrollment. The unused federated identities
remain protected until final migration retirement after signed-key acceptance.

The fixed publisher reads sensitive encrypted-state outputs privately, verifies
the trusted Mac's online homelab profile, signs via `file:/dev/stdin`, and
publishes `TAILSCALE_AUTH_KEY` to each protected plan/production environment plus
repository `TAILSCALE_CORDIUM_AUTH_KEY`. GitHub secret values are not readable;
metadata confirmation must be followed by protected CI acceptance. Only after
all three writes and metadata checks succeed does it delete the corresponding
three unused client-ID variables. Exact-main and trusted-PR workflow gates still
matter: these credentials do not encode GitHub OIDC subject claims. Raw signing
keys stay out of arguments and temporary files; stdin avoids the macOS app
sandbox refusing access to the private config directory.

Wrapped keys contain a delegated private node-signing key, separate from the
trusted credential authority's private voting key. The publisher requires exactly
one new authority with matching auth-key metadata after signing, with every prior
trust mapping unchanged. Before post-sign readback, it durably saves a private
pending receipt containing the validated wrapper. Bounded polling tolerates local
status lag; a timeout retains the receipt so retry verifies the same signature
before signing another key. File and directory fsync precede receipt retirement.
Its private `0600` cache records that separate public
authority identity with the wrapper; reuse and retirement require a unique
metadata match. Delegated node-signing capability exceeds normal tag enrollment
permissions. Auth-key expiry or revocation does not remove that authority;
after replacement CI acceptance, the explicit `--retire-previous` operation
removes only cached older-generation authorities while preserving unrelated
signers. Preview and execution validate every cached current signature and all
previous authority metadata before any removal. Execution rechecks each target;
an already-absent previous authority remains safe to retry. Preview never signs,
publishes or changes cache contents. Keep an encrypted private cache backup and use the
[module runbook](../../IaC/terragrunt-catalog/modules/tailscale-access/README.md) for rotation and
recovery. If an older publisher lost the wrapper before saving a receipt, the
separate orphan-recovery mode requires the exact current provider identity,
unique authority, this Mac's signer metadata and a timestamp within one day.
It refuses any pending receipt, matching cache entry or published fixed CI secret,
and requires the official read-only affected-signature query to return empty.
Only that authority can be removed, without re-signing; recovery never signs or
publishes. The query is a snapshot, so pause other signing/join activity through
recovery. The operator OAuth SSM contract remains separate and unchanged.

The Tailscale operator API proxy maps node tags to Kubernetes groups. Plan can
read resources, including Helm release Secrets, and submit Argo Application
dry-run writes. A fail-closed admission policy rejects its non-dry-run writes.
Apply retains cluster administration for existing bootstrap and RBAC ownership;
Cordium's mesh identity has no Kubernetes binding. Existing CI transport remains
until authenticated plan/apply and denial checks succeed over the new proxy.

Phase 2a removes the old public DNS writer and restoration workflow while
retaining Tunnel credentials, existing Octelium identities, and native carrier
recovery. The separate tailnet resolver watches approved Kubernetes Services
and needs no DNS write token. Only the later guarded retirement helper reads
the existing scoped cert-manager Cloudflare token. Feature 005 limits its
public A/AAAA/CNAME deletion to the 26 non-apex names from the fixed migration
set after owner tailnet DNS handoff and client acceptance. The private resolver
retains all 29 current approved names. Public apex, mail, DNS-01 validation,
and unrelated public names stay in the zone; see the
[cutover contract](../../specs/005-retire-public-app-dns/contracts/cutover.md).
The helper has no record-publication or restoration mode.
Credential retirement follows application, callback, CI, and Cordium acceptance;
changing DNS alone does not authorize deleting those credentials.

## AWS SSM Pattern

- Public parameter prefix: `/homelab/<app>/<name>`
- Region: `us-west-2`
- Runtime secret values live outside git.
- ExternalSecret namespace access is constrained by the `aws-ssm`
  ClusterSecretStore namespace allow-list.
- Add a namespace to that allow-list in the same change that adds its first
  ExternalSecret.
- The External Secrets IAM reader keeps exact parameter ARNs in sorted,
  deterministic customer-managed policy chunks of at most 25 names; it does
  not use a `/homelab/*` wildcard.
- Reader policy preconditions enforce AWS IAM's 6,144-character limit per
  customer-managed policy and 10 managed policies per group. The expanding
  parameter list is not split into group inline policies because their combined
  aggregate limit is 5,120 characters; the existing fixed-size inline policy
  retains only exact KMS-key permissions and is updated after the managed
  policies are attached.

The [Renovate runner](../../clusters/homelab/apps/renovate/README.md)
reuses its existing GitHub App. IaC declared two SecureString placeholders for
the App issuer and private key. The [2026-10-19 transfer receipt](../../docs/operator-infrastructure.md#renovate-app-credential-transfer-and-role-retirement)
records both parameters at version 2 and a later `Ready=True` refresh of the
`automation/renovate` ExternalSecret. It projects both credentials as files
every five minutes. Current IAM source removes the temporary exact-scope
companion writer role. After [#1390](https://github.com/Stuhlmuller/homelab/pull/1390)
merged, the operator applied the private, un-targeted saved plan with only the
role and inline-policy deletions. A read-only IAM lookup returned
`NoSuchEntity`, and a fresh full-unit plan had no changes. The CronJob is now
scheduled hourly in UTC and remains in full dry-run mode. Its earlier
19:00 and 20:00 UTC Jobs each finished all eight eligible repositories and
logged the same public release cache-key hit on separate Pods. After the
protected companion canary published `v0.0.2` at 20:20 UTC, the 21:00 scheduled
dry run hit that key and selected the new public canary branch proposal. The
durable aggregate receipt closes T022. Cache-fault recovery, full parity, and
writer cutover remain open. The legacy GitHub Action remains the only writer. The App
lacks repository Administration read, a recorded migration exception whose
first write-enabled outcome still needs policy review.
After dry-run parity and removal of the entire legacy workflow, a guarded
companion script retires the repository Actions private key only after checking
the SSM versions, later ExternalSecret projection, absence of same-name
organization or environment secrets, and drained old runs. Cluster writes then
require a separate reviewed GitOps change. Rollback first suspends and drains
cluster Jobs; the guarded companion restore script can restore the repository
Actions key from SSM before a reviewed PR restores the old workflow. This
writer cutover has not occurred.

The operator-owned External Secrets permissions boundary denies direct
temporary-session requests using `aws:TokenIssueTime` only when
`aws:ViaAWSService` is false. SSM must still forward the caller's authorization
to KMS for SecureString decryption; excluding this AWS service hop from the
deny does not grant any new action or resource. Exact reader policy ARNs and
the existing boundary Allow statements still apply. On 2026-08-30, the broader
deny caused `cordium-agent-auth` refreshes to fail at `kms:Decrypt`. The
administrator applied the reviewed single-update plan from
`IaC/homelab/us-west-2/operator/github-actions-role-policy`; Cordium's scheduled refresh succeeded
at `2026-08-30T16:56:48Z`. The native policy regression checks all four direct
and forwarded request contexts, retaining direct temporary-credential denial.
Only Cordium refreshes periodically (every five minutes); the other 23 live
ExternalSecrets use `OnChange`. Their existing Ready conditions and the global
store's Ready status do not prove that a new decryption works under the current
boundary. After repair, verify a controlled repository-driven refresh before
rotating dependent credentials.
See [AWS forward access sessions](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_forward_access_sessions.html)
and [ViaAWSService](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html#condition-keys-viaawsservice).

### Dormant OpenClaw Enterprise boundary

The declared but unapplied [Enterprise foundation](../../clusters/homelab/apps/openclaw-enterprise-foundation/README.md)
prepares restricted `openclaw-system` and external `openclaw-agents` namespaces.
The `aws-ssm` store allow-list includes both; eight `OnChange` ExternalSecrets
project only exact `/homelab/openclaw-enterprise/` parameters and retain target
Secrets on deletion. The model key remains a placeholder until the protected
workflow supplies a distinct OpenRouter key. These declarations do not prove
materialization or authorize activation.

`occ-database` templates separate `application-url` and `migration-url` keys
from generated app and migrator passwords. Both URLs name the private
`occ-postgres` Service and require `sslmode=verify-full` with the retained
`occ-postgres-root` CA at `/etc/openclaw/database-ca/tls.crt`; the admin
password is a separate target. cert-manager declares that CA and a server
certificate for the Service DNS name. PostgreSQL, chart consumers, backup,
and live TLS verification remain pending.

The separate dormant [application candidate](../../clusters/homelab/apps/openclaw-enterprise/README.md)
uses a versioned immutable `occ-installation-startup-*` Secret for reviewed,
non-secret `installation.yaml` bytes. Its exact SHA-256 is bound in Helm values.
A protected exact-`main` workflow can create and reread only that fixed Secret
after the foundation namespace exists; this PR does not run it. The initial
Secret has no installation ID. The source-only
[`bind-installation.py`](../../scripts/openclaw-enterprise-bind-installation.py)
attests both Ready controller Pods and the returned `GET /installation` ID,
then patches only the Secret annotation with UID/resource-version guards and
readback. A fixed [protected binding lane](../../.github/workflows/openclaw-enterprise-operations.yml)
rechecks exact current `main` and pins the reviewed binder, but the hosted runner
has no declared delivery for the owner-controlled 0600 bootstrap service-key file.
No binding run or live readback has occurred; activation remains blocked.
SSM-backed model, database, auth, and gateway credentials remain separate from
these startup bytes.

The staged [journal operator](../../clusters/homelab/apps/openclaw-enterprise-operator/README.md)
has a dedicated ServiceAccount with automatic token mounting disabled. Its
one-shot Job projects a short-lived token and CA for the fixed Kubernetes API;
read-only RBAC can GET only the exact reviewed Installation Secret and selected
workload proofs. Reconcile and stop require the chart's bootstrap service key
as a UID-10001-owned `0600` file on the retained bootstrap claim. The bundle
is not registered in Argo CD, that file ownership is unproved, and the operator
gate remains disabled; these permissions are source intent, not live access.

## Identity Notes

- Fleet uses five generated `/homelab/fleet/` SSM values: database user/root
  passwords, Redis password, a stable 32-byte server encryption key and initial
  administrator password. Namespace `fleet` has a scoped store/policy contract.
  Separate mounted Secrets keep the root password out of Fleet and the admin
  password exclusively in its one-time bootstrap Job. The initial account uses
  `rodman@stuhlmuller.net`; subsequent syncs preserve user changes. APNs and
  platform signing identities still require their provider setup. Preserve them
  with the database and server key. See the [Fleet runbook](../../clusters/homelab/apps/fleet/README.md).
  The repository-owned `scripts/fleet-download-apple-csr.py` prepares Apple's
  vendor-signed CSR using the initial administrator Secret without printing
  credentials. Its first request creates encrypted SCEP/APNs keys in MySQL;
  preserve that database with the server encryption key. The public CSR goes
  to Fleet's signing service; the operator must still issue the APNs certificate
  through their Apple account and upload it in Fleet before device enrollment.
  Its `--certificate` mode performs first activation through Fleet's APNs setup
  API, refuses to overwrite an enabled integration, verifies enabled state and
  certificate metadata, and revokes its session. Certificate renewal remains
  the documented Fleet UI flow using the same Apple account. APNs material
  stays encrypted in MySQL and outside git.

- Fleet-managed Mac Google login stages a separate operator-only
  `/homelab/fleet/google-oauth` SecureString. It is excluded from External
  Secrets: the [XCreds operator](../../scripts/fleet-google-login.py) reads the
  dedicated OAuth client privately and delivers a host-scoped MDM profile only
  after protected merge and deployment. The current Fleet administrator
  password comes from an owner-only file after bootstrap rotation. Email-claim
  username mapping, local login fallback, and FileVault acceptance are explicit
  pilot checks. Remote profile removal requires verified native login and an
  explicit operator attestation; see the
  [Google login runbook](../../clusters/homelab/apps/fleet/GOOGLE-LOGIN.md).

- Argo CD SSO uses the `argocd-oidc-sso` ExternalSecret for the upstream OIDC
  issuer compatibility copy, client ID, and client secret. Dex startup uses the
  literal Microsoft Entra issuer committed in
  `IaC/homelab/us-west-2/bootstrap/argocd/terragrunt.hcl` so a placeholder SSM value cannot stop
  provider discovery. Microsoft Entra group authorization is a token-claim
  behavior, not a requested OAuth scope: keep Dex scopes to `openid`,
  `profile`, and `email`, configure Entra to emit the `groups` claim for Argo
  CD RBAC, and keep `insecureSkipEmailVerified: true` because Entra may omit
  the `email_verified` claim. Dex maps the existing administrator's immutable
  Entra object ID using `userIDKey: oid`; Argo CD v3 binds that federated user
  ID directly to `role:admin`, then evaluates group claims. It does not use a
  mutable email value for authorization, so the exact-UPN Mac PSSO pilot cannot
  inherit Argo CD administration from a matching email address.
- Argo CD Image Updater is restored as a paused, zero-replica chart. The
  proposer/promoter GitHub App credential lane remains unprovisioned; no private
  key is committed and no runtime Secret is enabled. When provisioned, proposer
  access is limited to the proposal branch and promoter access is limited to the
  reviewed production workflow. Existing tombstone SSM paths remain separate
  until the fresh identities and reader grants are reviewed. See
  [Image Automation](../runbooks/image-automation.md) and
  [AWS SSM Secret References](../runbooks/secrets-aws-ssm.md).
- Grafana Microsoft Entra SSO is managed through
  `IaC/homelab/us-west-2/apps/grafana/azuread`. Grafana and Octelium passwords expire
  one year after creation, but their current resources have no rotation trigger;
  an unchanged apply does not rotate them. Coordinate a reviewed
  `rotate_when_changed` revision with the Grafana `OnChange` ExternalSecret and
  the Octelium native-secret sync before either expiry.
- Entra provider identities are operator-owned Terraform resources under
  `IaC/homelab/us-west-2/operator/azuread-ci-identities`. Separate plan/apply applications trust
  only their exact protected GitHub environments; no client secret, paid license
  or CI self-grant permission is configured. Stable application ownership
  preserves the human administrator when switching provider identities. GitHub
  environment protection remains owned by `Stuhlmuller/github-iac`. Follow the
  [provider runbook](../../docs/entra-terraform-provider.md) for the bootstrap,
  permission limits and independent CI OIDC acceptance gates.
- Alertmanager owns notification delivery credentials for Grafana-managed
  alerts. The Prometheus app materializes the
  `alertmanager-discord-webhook` ExternalSecret in `monitoring`, sourced from
  `/homelab/grafana/discord-webhook-url`. Grafana routes alerts to the
  in-cluster Alertmanager contact point. External Secrets renders the Discord
  URL into Alertmanager's runtime config Secret because the Operator schema has
  no Discord URL-file field. Both routing layers repeat unresolved alerts
  hourly before Alertmanager sends the resolved notification. Alertmanager
  groups by alert name and namespace so pod-level incident fan-out does not
  exhaust Discord's webhook rate limit. Its bounded Discord template reports
  only status, alert name, namespace, and counts, avoiding oversized grouped
  payloads. Grafana
  provisioning deletes
  the retired `homelab-discord` and `homelab-openclaw-alert-hook` receiver UIDs
  so persisted Grafana PVC state does not keep retrying removed integrations.
  OpenClaw separately receives its hook token through `openclaw-secrets` as
  `GRAFANA_ALERT_HOOK_TOKEN`; bootstrap
  expands and JSON-encodes that runtime value before writing `hooks.token`,
  because OpenClaw rejects SecretRef objects for that hook-token surface.
  Alertmanager does not call the hook because its standard webhook body lacks
  OpenClaw's required `message` field.
- Tailscale operator OAuth uses the `tailscale-oauth` ExternalSecret and the
  target Secret `operator-oauth`.
- Cordium uses the `cordium-agent-auth` ExternalSecret in `octelium`, sourced
  from `/homelab/cordium/agent-auth-token`, for the policy-bound
  `homelab-cordium-agent` Workload User. The PostSync configuration hook uses
  that token only to apply the repository-owned Cordium ClusterConfig. This
  ExternalSecret polls the current SSM version every five minutes so bootstrap
  can replace the declared placeholder without a follow-up git change. The
  production apply adopts a pre-populated Cordium parameter before planning.
- The retired GitHub Actions runner no longer consumes an SSM registration
  token. `/homelab/github-actions-runner/registration-token` remains declared
  and adoptable only as an OpenTofu state tombstone because the production
  policy rejects SSM parameter deletion. It is excluded from the External
  Secrets reader IAM policy. Remove it only with a reviewed
  repository-owned state and secret-retirement workflow.
- Bazarr reads Sonarr/Radarr API keys from their existing local `config.xml`
  files through read-only whole config-claim mounts in the configure init
  container. Whole mounts avoid Talos kubelet resolving file `subPath` mounts
  against empty directories in its isolated filesystem. The init container can
  read each source config volume, but its script reads only `config.xml`.
  It retains credentials only in
  its private config volume; no new SSM parameter or direct environment-variable
  secret injection is introduced. The main container never mounts either source
  config claim. The public `bazarr.default` Octelium WEB Service at
  `https://bazarr.stinkyboi.com` requires `homelab-human-web-access` and disables
  anonymous access. Cloudflare Tunnel forwards to the Octelium ingress dataplane;
  Bazarr's internal upstream remains unchanged. Config backups contain these
  credentials and must remain private.
- Dispatcharr's dedicated PostgreSQL password is generated at
  `/homelab/media-postgres/dispatcharr-app-password` and rendered by
  `dispatcharr-postgres-env`; IPTV provider credentials and playlist URLs
  remain operator-configured and must not be committed.
- Multica uses generated `/homelab/multica/jwt-secret`,
  `/homelab/multica/postgres-password`, and six-digit
  `/homelab/multica/dev-verification-code` values. ExternalSecrets in `ai`
  render the database credentials into `multica-secrets` and backend credentials
  plus the fixed code into `multica-backend-secrets`, both with
  `refreshPolicy: OnChange` and `deletionPolicy: Retain`. The new backend Secret
  prevents starting before the fixed code is present; PostgreSQL retains its
  original Secret. Rotate generated JWT and PostgreSQL values through
  the committed `IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl`
  catalog source and regenerated `IaC/homelab/us-west-2/shared/aws-ssm-parameters` OpenTofu stack;
  do not hand-edit
  `/homelab/multica/postgres-password`, because future applies restore the
  repository-owned generated value. PostgreSQL password rotation also requires
  the database-role procedure in [AWS SSM Secret References](../runbooks/secrets-aws-ssm.md) before rolling
  consumers, since changing SSM alone does not update the retained PostgreSQL
  role on an initialized PVC. Preserve the target Secret and PostgreSQL PVC
  during rollback unless intentionally rebuilding the instance. The backend
  uses `APP_ENV=development` to accept the private fixed code without email
  delivery; the code-entry screen remains. Octelium gates access, but code
  holders with access can impersonate existing Multica users. Keep this limited
  to trusted operators; restore production mode and a real email/OAuth provider
  before regular multi-user use. See the [Multica runbook](../../clusters/homelab/apps/multica/README.md).
  Native desktop access requires an authenticated Octelium CLIENT session;
  exposing Multica auth or API paths outside Octelium would make the shared code
  an unsafe public credential.
  The server runtime uses only the fixed-code key in an init container to
  bootstrap a 90-day Rodman PAT, then retains that PAT privately on its own
  local PVC. The pinned daemon asks the backend to renew that token in place
  when seven days or less remain; revoked or expired tokens fail startup rather
  than silently creating a replacement. The main container exposes only
  its own profile, including native ChatGPT OAuth state retained on the runtime
  PVC; it does not mount the backend JWT, database password, fixed code, or a
  model API key. This remains a trusted operator runtime because tasks can read
  that profile. Its dedicated ServiceAccount has no Kubernetes token and
  receives explicit Istio access only to the Multica backend. OAuth is created
  through an interactive Codex device login and must not be copied into SSM or
  a Kubernetes Secret.
- NOFX uses generated `/homelab/nofx/jwt-secret`,
  `/homelab/nofx/data-encryption-key`, and
  `/homelab/nofx/rsa-private-key` values. The RSA key is a 2048-bit PEM key
  generated through the shared SSM parameter module and enables browser-side
  transport encryption without committing key material.
  Its private maintained images use the read-only Harbor robot through the
  namespace-scoped `harbor-pull` Secret, referenced only by `imagePullSecrets`.
  The retained GHCR recovery path uses a separate, externally issued
  `/homelab/nofx/ghcr-read-token`. The protected `NOFX Registry Credential`
  workflow validates a dedicated classic PAT with only `read:packages` before
  updating that exact SecureString. `nofx-registry-auth` refreshes every five
  minutes and renders a kubelet-only Docker config Secret. A GHCR rollback must
  switch image references and pull Secret together after authenticated pulls
  and a fresh successful Secret refresh. Bootstrap
  PR #1031 retained upstream images while establishing this credential path;
  see the [private-image runbook](../../docs/nofx-private-images.md).
- Octelium client bridge auth uses the `octelium-client-auth` ExternalSecret in
  `octelium-client`, sourced from `/homelab/octelium/client-auth-token` and
  rendered to the versioned target Secret `octelium-client-auth-v5`. The token
  belongs to the Octelium workload User `homelab-octelium-client` and is
  created outside git with `octeliumctl`.
  Public Octelium control-plane access uses the
  `octelium-public-cloudflared-credentials` ExternalSecret in
  `octelium-public`, sourced from
  `/homelab/octelium/cloudflare-tunnel-credentials-json` and
  `/homelab/octelium/cloudflare-tunnel-id`. The Cloudflare Tunnel credential
  JSON and UUID are created outside git with `cloudflared tunnel create
homelab-octelium-public`. This retained tunnel supports legacy callers only
  until the staged replacement gates pass. Its public DNS writer and restoration
  workflow are removed. The canonical mesh DNS helper reuses the scoped
  cert-manager token; n8n and Policy Bot external registrations move to Funnel
  through their fixed helpers, preserving credentials and requiring fresh signed
  delivery receipts. Native carrier and CI secrets remain until separate
  acceptance. Token values never enter git or workflow output.
  Octelium portal login uses Microsoft Entra OIDC. The Entra application is
  managed by `IaC/homelab/us-west-2/apps/octelium/azuread` and writes generated
  client material to `/homelab/octelium/entra/*`; these values are copied into
  the Octelium native Secret `entra-oidc-client-secret` and IdentityProvider
  `entra` by `scripts/octelium-entra-oidc.sh`. HUMAN user Entra identifiers are
  runtime mappings and must not be committed to the public repo.
  GitHub Actions uses a separate Octelium workload credential for User
  `homelab-ci`, Policy `homelab-ci-kubernetes-api-access`, and Service
  `kubernetes-api-ci`. Store the credential only as GitHub environment
  secret `OCTELIUM_CI_AUTH_TOKEN` for `homelab-plan` and
  `homelab-production`. Only `homelab-plan` requires reviewer approval.
  The production environment
  permits only `main` and releases credentials without another approval;
  main-only diagnostics also use production. Approve a pull request plan only
  after reviewing its exact code because that job also assumes the environment-bound AWS OIDC
  identity. Repository Actions policy rejects mutable action tags, and the
  `main` ruleset requires signed, squash-only pull requests with strict
  always-on checks and no force pushes. The CI connector does not pass Octelium
  `--scope` flags on v0.35. Its Session policy requires the exact WORKLOAD User,
  CLIENTLESS Session, `kubernetes-api-ci.default` Service, and KUBERNETES mode;
  it must not grant the bearer access to other public Services. The User owns
  matching 30-day clientless-session and access-token lifetimes. Rotate it every
  21 days with
  `scripts/octelium-ci-credential.sh`; the helper deletes the dedicated User's
  Sessions first so Octelium cannot retain an older Session expiry, then retries
  GitHub environment writes until both store the replacement token.
  Octelium Secret `homelab-ci-kubeconfig` stores the upstream credential shared
  by `kubernetes-api-ci` and private Service `kubernetes-api.homelab`; clients
  receive only Octelium-generated kubeconfigs. Recreating the Secret briefly
  affects CI, operator, and Cordium Kubernetes access, so validate both Services
  after rotation.
  The protected Talos maintenance lane has a separate CLIENT authentication
  token, `OCE_OCTELIUM_CLIENT_AUTH_TOKEN`, limited by
  `homelab-platform-talos-ci-access` to the private TCP
  `talos-api-ci.homelab` Service. Its repository helper
  [`platform-maintenance-credentials.sh`](../../scripts/platform-maintenance-credentials.sh)
  runs only from an exact, clean `main` checkout; it verifies the reviewed
  Octelium WORKLOAD User, policy, and Service before creating or rotating the
  dedicated Credential. It does not delete the User's CLIENTLESS Kubernetes
  sessions. The same helper issues a separate 30-day Talos `os:admin` client
  from a valid operator identity, proves its certificate and key differ from
  the operator's, tests read-only direct access, and publishes only the encoded
  client as `OCE_TALOSCONFIG_B64` in `homelab-production`. It never uploads the
  operator's client config. Protected inspect run `39362087271` stopped at the
  Talos connection setup with both inputs empty. The helper has only local
  tests; Octelium admin authentication, CI issuance, tunnel access, and a
  complete protected inspection receipt remain outstanding. See the
  [Talos maintenance runbook](../../docs/talos-control-plane-maintenance.md).
  The fixed upgrade stages also read private role-specific control-plane and
  worker configs from protected workflow secrets. This path remains inactive
  while `activationEnabled` is false and its placement, recovery, and image
  publication receipts are missing.
  The dormant firewall cleanup lane keeps capture, approval, attempt, and
  completion evidence in the private versioned maintenance bucket. The owner
  reviews the full capture outside public logs and supplies its exact digest
  to a fresh protected approval run. That run verifies the owner actor, live
  snapshot, absent fixture namespace and workloads, exact reviewed canary Pod
  inventory, and current `main` before writing an
  immutable receipt under the capture run ID. Partial deletion needs a new
  capture and approval, including when no owned objects remain.
- Focused reconciliation of `homelab-private-kubernetes-access` and
  `kubernetes-api.homelab` uses the separate `homelab-catalog-ci` workload User
  and `homelab-private-kubernetes-ci` AUTH_TOKEN Credential. The Credential is
  limited to one authentication, expires after 30 minutes, auto-deletes on
  login, and copies a highest-priority, fail-closed six-method Policy/Service
  API policy into a 15-minute client Session. Its helper-only template is kept
  outside the general Octelium catalog with an already-expired timestamp; only
  the lifecycle helper replaces that timestamp and applies it. The
  protected `homelab-production` secret
  `OCTELIUM_CATALOG_AUTH_TOKEN` exists only between provisioning and the
  mandatory revoke step. Octelium v0.35 cannot scope these methods by object
  name; the fixed helper, reviewed hashes, exact `main` SHA, and production
  approval provide that boundary. See `docs/ci-cd.md`.
  The self-hosted Octelium Cluster storage layer uses generated
  `/homelab/octelium/postgres-password` and
  `/homelab/octelium/redis-password` values materialized by
  `octelium-storage-auth`; `scripts/octelium-cluster-bootstrap.sh` reads those
  Kubernetes Secret values into a temporary `octops init` bootstrap file that is
  never committed.
  Octelium Enterprise license material, if required for commercial or
  production use, also stays outside git; add only a safe SSM or
  ExternalSecret contract in a future change if the package needs one.
- The GitHub Actions AWS OIDC apply role is an operator-owned bootstrap
  identity. `IaC/homelab/us-west-2/operator/github-actions-role-policy` owns the existing
  `Github-TF-State` role's trust policy and additive SSM reader-policy lifecycle
  grant. Trust is limited to `homelab-plan`, `homelab-production`,
  `github-iac-plan`, and `github-iac-production`. Apply trust changes only with
  a reviewed administrator session and the single-role saved-plan gate in
  `docs/operator-infrastructure.md`; the first rollout must import the existing role
  before planning. CI must not traverse `IaC/homelab/us-west-2/operator` or gain permission to
  replace its own attachment. The
  grant is bounded to policy slots `00` through `09` and the exact
  `homelab-ssm-parameter-readers` group, plus metadata-only `kms:DescribeKey`
  on the resolved current runtime-secret key. The September 29, 2026 Langfuse
  apply reached SSM refresh but its identity policy still covered only the old
  runtime key. The correction reuses the operator-owned policy and attachment;
  it adds no cryptographic or key-administration permission. Apply only the
  reviewed single-policy saved-plan update through
  [the operator runbook](../../docs/operator-infrastructure.md#full-unit-reconciliation),
  never CI self-administration; stop on unrelated drift. On September 30, 2026
  PDT (October 1 UTC), the saved plan applied and a fresh full-unit plan was a
  no-op; CI simulation allows only `kms:DescribeKey` on the current SSM key,
  with `kms:Decrypt` and `kms:ScheduleKeyDeletion` implicitly denied. The unit also adopts
  `external-secrets_aws-ssm-auth`, removes direct user policies, and caps it
  with an operator-owned boundary that allows only homelab SSM reads and
  runtime-secret KMS decrypt/describe access. The boundary denies direct
  temporary STS requests while preserving SSM's AWS-managed KMS calls, and the
  reader policy excludes the two parameters that hold
  this user's own key so a compromised key cannot copy its replacement. The
  pending administrator rollout remains tracked in
  [Continuous Improvement](../operations/continuous-improvement.md).
- cert-manager DNS-01 uses the `cert-manager-cloudflare-api-token`
  ExternalSecret and target Secret `cloudflare-api-token`.
- AFFiNE uses generated `/homelab/affine/postgres-password`,
  `/homelab/affine/redis-password`, and `/homelab/affine/private-key` values.
  The private key is a P-256 ECDSA PEM generated by OpenTofu, encrypted in SSM,
  and materialized by `affine-secrets`; it must remain stable because AFFiNE
  uses it for token signing and application-data encryption.
- Langfuse keeps application, datastore, project and headless-init credentials
  under `/homelab/langfuse/`; its namespace consumes `langfuse-secrets`.
  `IaC/homelab/us-west-2/apps/langfuse/blob-storage` owns the distinct S3 runtime credential pair.
  On September 30, 2026 PDT (October 1 UTC), an administrator applied its
  reviewed 12-resource bootstrap through the normal remote state; a fresh plan
  was a no-op and live checks confirmed public-access blocks, versioning, and
  both exact S3 SSM parameters as current SecureStrings under `alias/aws/ssm`.
  After a reviewed operator apply adds the pending grant, CI can use only
  `iam:GetUser`, `iam:ListAccessKeys`, and
  `iam:GetUserPolicy` on
  `arn:aws:iam::716182248480:user/homelab/homelab-langfuse-s3` for Langfuse-user
  refresh. This additional grant has no IAM write, tag, wildcard, or other-user
  permission. Future Langfuse IAM lifecycle or credential-rotation changes
  remain operator-owned through the same saved-plan path.
- LiteLLM caller keys are generated separately for NOFX, Multica and n8n at
  dedicated SSM paths. The prepared database-key migration adds separate
  `/homelab/litellm/postgres-{admin,app}-password` parameters: admin is database
  only; the client Secret exposes just the nonsuperuser database-owner password.
  The native cutover imports existing caller values once in a locked database
  transaction, with a durable `homelab-native-key-import-v1` marker. Native
  authentication replaces the file-only bypass; startup does not recreate
  deleted keys or undo UI blocks. Subsequent rotation must coordinate the
  database value and the caller's SSM refresh. Live UI/revocation acceptance
  remains pending until deployed and exercised.
  Existing caller paths remain
  `/homelab/<app>/litellm-token`; OpenClaw uses
  `/homelab/openclaw/litellm-app-token`. The prior OpenClaw `litellm-token`
  remains a retired master-key alias with no workload consumer. LiteLLM alone
  receives the existing `/homelab/litellm/openai-api-key` provider credential
  and Langfuse project keys. Its pre-auth guard prevents callers from choosing
  a provider, collector, or identity. See [AI observability](ai-observability.md) for acceptance
  evidence and accounting scope. External OpenRouter key injection uses
  `.github/workflows/litellm-provider-credential.yml`: a temporary production
  GitHub secret, scoped AWS OIDC write, then a separate GitOps `OnChange`
  revision bump. See the [SSM runbook](../../docs/secrets-aws-ssm.md#ai-gateway-contract).
- Deluge uses the `deluge-vpn` ExternalSecret for AirVPN WireGuard profile
  material. It reads the full profile from
  `/homelab/deluge/vpn/wireguard-config` and publishes it as `wg0.conf`. It
  is the only Deluge VPN parameter readable by External Secrets; the six
  retired split-profile parameters remain non-readable state tombstones. It
  refreshes on ExternalSecret changes; after replacing the SSM profile value,
  bump `homelab.rst.io/wireguard-profile-ssm-version` on both the
  ExternalSecret and Deluge pod template so the Secret is rerendered and
  Gluetun starts with the new profile. Its startup wrapper extracts the private
  key, preshared key, and first IPv4 interface address, while Gluetun's native
  AirVPN provider selects the server. The profile's endpoint and server key are
  not used, avoiding custom-provider DNS resolution during sidecar recovery.
- n8n uses `/homelab/n8n/encryption-key` as a first-boot bootstrap key only;
  existing PVCs keep using their persisted `/home/node/.n8n/config` key.
  Its dedicated `/homelab/n8n/litellm-token` is rendered only as an OpenAI
  credential overwrite for the internal LiteLLM endpoint; it is never stored
  in workflow JSON or the n8n credential database.
  `n8n-postgres` uses generated `/homelab/n8n/postgres-admin-password` and
  `/homelab/n8n/postgres-app-password` values; n8n receives only the app
  password through `n8n-postgres-client` and
  `DB_POSTGRESDB_PASSWORD_FILE`.
- The stopped legacy OpenClaw retains `/homelab/openclaw/app-secret` as
  `OPENCLAW_GATEWAY_TOKEN`; bootstrap configures gateway auth with an OpenClaw
  SecretRef to that environment value instead of a generated file under the
  container user's home directory. OpenClaw uses
  `/homelab/openclaw/discord-bot-token` as `DISCORD_BOT_TOKEN`; bootstrap
  installs the exact image-version official external Discord package from npm
  into pod-local storage before config validation without a floating fallback,
  then configures Discord with an OpenClaw SecretRef to that environment value
  instead of storing the token in config. The bootstrap and proxy containers
  do not receive the app-only LiteLLM, Grafana-login, or GitHub App credentials,
  and the proxy does not mount persistent OpenClaw state. The deployed assistant
  does not configure ChatGPT Pro or Codex OAuth inference. OpenClaw GitHub App credentials use
  `/homelab/openclaw/github-app/id`,
  `/homelab/openclaw/github-app/installation-id`, and
  `/homelab/openclaw/github-app/private-key`; the ID values are env vars and
  the private key is mounted into the app as a file referenced by
  `GITHUB_APP_PRIVATE_KEY_PATH`. The managed `assistant/gh` wrapper exchanges
  that key for a homelab-only installation token on each CLI/Git invocation.
  Tokens use private temporary CLI config files, never the PVC or child process
  environment; requests omit administration and secret-management permissions.
- Fresh OpenClaw Enterprise has a separate `/homelab/openclaw-enterprise/*`
  contract. OpenTofu generates five internal values; the model key stays a
  placeholder until the owner supplies a distinct OpenRouter inference key to
  the protected [fixed-target workflow](../../.github/workflows/openclaw-enterprise-model-credential.yml).
  It verifies the key and writes only the new SSM path. The selected
  `openrouter/free` model uses OCE's OpenAI-compatible provider configuration.
  Activation remains disabled until the key, consumer refresh, and real model
  probe pass. No legacy OpenClaw or LiteLLM credential is an alias for this
  agent. See the [SSM contract](../../docs/secrets-aws-ssm.md#openclaw-enterprise-credential-contract).
- Policy Bot runs one replica after its GitHub-App-owned SSM placeholders are
  replaced. Its SSM contract is summarized in
  [AWS SSM Secret References](../runbooks/secrets-aws-ssm.md) and [Application Notes](../workloads/application-notes.md). Configure
  the GitHub App webhook URL to
  `https://policy-bot-hook.tail67beb.ts.net/api/github/hook` through the guarded
  callback helper after Funnel routing and negative-path preflights pass;
  require a fresh signed delivery before retiring the legacy route. Keep the webhook secret in
  `/homelab/policy-bot/github-app/webhook-secret`.

## Source Files

- `docs/secrets-aws-ssm.md`
- `IaC/homelab/us-west-2/shared/aws-ssm-parameters`
- `IaC/homelab/us-west-2/shared/kubernetes-secrets/external-secrets-aws-ssm-auth`
- `clusters/homelab/apps/external-secrets`

## Dedicated Cordium CI assertion

The staged runner controller uses a separate `cordium-runners` namespace and
ExternalSecret for its GitHub App private key and Cordium auth token. Protected
exact-main intake writes only the two fixed SSM references. The controller
copies projected values into private files before each queue cycle; the App
key never enters a runner Workspace. Namespace RBAC can manage per-runner
NetworkPolicies and inspect named enforcer and workload state, but cannot read
Kubernetes Secrets or mutate workloads. Registration and the controller
Deployment remain disabled pending identity, isolation, publication, and
cold-pull acceptance. See the [runner contract](../../builds/cordium-runner/README.md).

`homelab-cordium-ci-oidc` accepts GitHub assertions only for the exact repository,
owner, main workflow, audience, and dispatch event. `homelab-cordium-ci` is a
separate workload identity with bounded sessions and workspace lifecycle/exec
permissions; bootstrap management credentials are not shared. A catch-all
post-authentication denial and priority -4 method denial close upstream
default allowances. The fixed `scripts/cordium-ci-reconcile.py` path previews
only these three resources by default. Execution requires clean, exact reviewed
main, applies Policy before IdentityProvider and User, proves repeated-apply
convergence, and verifies the declared specifications. It never applies the
full catalog or creates credentials. A 2026-09-12 authenticated read-only
preview found all three resources absent; native installation and live OIDC
acceptance remain pending. See
[the contract and pending live gates](../../docs/cordium-ci.md).

## NOFX native reconciliation boundary

NOFX anonymous-access removal is applied by the fixed repository operator
command, independently from Kubernetes Argo CD. It requires an exact reviewed
main commit, selects only `nofx.default`, proves a second apply is empty, and
verifies the human-access policy. Existing operator credentials stay private;
the temporary native transport changes no saved host or client settings.
See [NOFX reconciliation](../../docs/octelium-nofx-reconciliation.md).

## Fleet Free identity boundaries

The Fleet-only Company Portal/Platform SSO pilot is retired. Its registration
and owner-address details below are dated history, not a procedure to repeat
or authorization for ad hoc identity changes. The separate owner conversion
is currently blocked because `stuhlmuller.net` is federated with Google;
Microsoft requires a nonfederated target UPN domain for cloud-only conversion.
Its reviewed preparation, recovery administrator and attestation require a
separate federation or target-domain change first. See the current
[retirement boundary](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#retired-platform-sso-pilot).

The [WireGuard/AirVPN operator](../../clusters/homelab/apps/fleet/WIREGUARD-AIRVPN.md)
accepts private owner-supplied client exports from outside git, separately per
device. It builds the credential-bearing Apple profile in memory and sends it
only to the selected device. Fleet command data, database backups, and device
profiles/keychain can contain the VPN material and require credential-level
protection. The public catalog contains only app links and a reporting policy;
there is no global private-profile upload, Deluge secret reuse, or new SSM
contract. Removing a device profile does not revoke its AirVPN client key.

Its optional `--password-file` supplies the existing Fleet administrator's
current password after rotation, replacing the bootstrap-secret source without
fallback, login retries, or credential rotation. The owner-only `0600` UTF-8
file must be outside the repository and at most 4096 bytes, with one password
line; one final LF/CRLF is ignored and spaces are preserved. Dry runs read
neither credential source. Omitting the option uses the initial administrator
secret and works only while that password remains current.

See the [Free Entra runbook](../../clusters/homelab/apps/fleet/FREE-ENTRA.md).
Fleet-only Company Portal/Platform SSO is retired after the live pilot required
licensed Intune enrollment. The repository retains its profile only for scoped
removal. Mac and iPhone/iPad passcode baselines remain host-scoped Free MDM
operations; neither synchronizes a local password with Entra.

Console SAML is a separate `azuread-applications/fleet` Terragrunt unit. Its
single-tenant enterprise application requires individual assignment, selects a
Microsoft-generated signing certificate declaratively, and exposes only sensitive
runtime metadata outputs. The initial Fleet administrator remains a recovery
account; only the authorized Entra identity is precreated as an SSO administrator.
JIT/SCIM provisioning stays disabled. The public native-client route continues
without Octelium redirects; Fleet authenticates administrative requests.

Read-only inspection found Entra Free and enabled Security Defaults. The
owner remains the existing external Microsoft-account member until a separately
authorized admin-center conversion. Fleet, Grafana and Octelium now bind its
immutable object ID so the supported transition can preserve ownership.
`scripts/entra-owner-conversion.py` prepares a private read-only receipt and
attests the converted target identity after the operator action; it never writes
Graph. It rejects the current federated `stuhlmuller.net` target; do not run
the conversion until a separately reviewed change reconciles the protected
federation or selects a managed target and updates its dependent mappings. Its
independent cloud-only recovery Global Administrator prerequisite
is disabled by default and requires a separately reviewed saved plan and sign-in.
After any later conversion, clear the recovery Azure CLI session and sign in as
the converted owner before attesting; the helper checks Graph `/me` against
the immutable owner ID and target UPN.
The Fleet console SAML target is `rodman@stuhlmuller.net`; the existing
`rodman@stinkyboi.com` local administrator remains recovery-only. API topology
readback does not prove the browser SAML callback or recovery login.
The separate `rodman.mac@stuhlmuller.net` pilot remains without a role, group,
license, mailbox or Fleet console assignment and is not a Platform SSO route.

The separate `operator/entra-stuhlmuller-domain` unit reads the existing
`stuhlmuller.net` Entra domain as a non-default managed domain. It reads the
Microsoft Graph TXT verification record, does not configure email, federation,
or Google Workspace, and keeps verification disabled until the DNS owner has
applied that record through its own reviewed declarative path. Once both
authoritative servers return it, the reviewed phase-two catalog change enables
the sole Graph verification action. That action intentionally uses the
standard bodyless Graph request, retaining the service default of no domain
takeover; its private saved plan must confirm the domain remains managed and
non-default. The companion
`operator/entra-stuhlmuller-pilot-user` unit could then create only
`rodman.mac@stuhlmuller.net`. Its domain guard requires verified managed,
non-default state, so it cannot plan against the current federation. The
account receives no role, group, license, mailbox or
Fleet-console assignment. Existing Google/Entra users stay untouched; a Google
email address alone is not an Entra password identity. Its guarded module is
separate from the legacy AzureAD user module, and the AzureAD workflow selects
that collection only when its own source or plan inputs change; an operator-only
pilot change cannot trigger legacy-user reconciliation.

## Google Workspace federation boundary

The Fleet-only Company Portal/Platform SSO pilot is retired. Its registration
and owner-address details below are dated history, not a procedure to repeat
or authorization for ad hoc identity changes. The separate owner conversion
is blocked by the current Google federation until a reviewed federation or
target-domain change; preparation, recovery administrator and attestation
remain required. See the current
[retirement boundary](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#retired-platform-sso-pilot).

`operator/entra-google-workspace-federation` owns the Entra Graph federation
configuration for `stuhlmuller.net`. Its Google SAML metadata is an
operator-only SSM SecureString and never appears in Git. Google Workspace
auto-provisioning creates the matching Entra users; the Entra federation only
authenticates those users. CI provider identities do not receive domain-write
permissions, so the unit remains an independently reviewed operator apply.

The [October 6 registration incident](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#registration-failure-and-historical-alias-release-evidence)
found a deployed pilot UPN mismatch: the Mac attempted personal-account device
registration while the cloud pilot still used `rodman.mac@stuhlmuller.net`.
Merged PR #1202 already declared `rodman@stuhlmuller.net`; that operator-only
change required a focused apply. The approved apply failed with
`DirectoryUniquenessException`; the pilot retained its old UPN, nickname and
password-change timestamp. The owner's existing mail/SMTP proxy uses the
requested address, making it the leading conflict candidate, but Entra's audit
did not name the conflicting property. The pilot-rename approval does not cover
clearing owner aliases or converting that administrator; a separate owner-address
migration was subsequently approved. The former registration failure and token-endpoint warning remain historical;
Fleet-only PSSO must not be retried. The separate pilot UPN remains unchanged.

The [owner-address migration](../../clusters/homelab/apps/fleet/FREE-ENTRA.md#owner-address-migration-alias-release-blocked)
applied on October 7, 2026 UTC, preserving the owner UPN, object ID and external
authentication. The owner was the only active Global Administrator found.
Octelium's previous email-based HUMAN mapping was affected by address reuse;
application assignment is not required and the OIDC scopes have tenant-wide consent.
The [bootstrap](../../scripts/octelium-entra-oidc.sh) now uses immutable Entra
`oid` with `disableEmailAsIdentity: true`, checks the complete live inventory
including implicit email-fallback users, and permits a guarded transition of
the sole selected legacy HUMAN mapping. Changing the claim alone does not
prevent fallback through the separate OIDC email claim. Existing user fields,
contact email, policies and other identity-provider bindings remain intact,
including partial retries. Complete-inventory preflight and the live migration
passed. New owner Octelium sessions through Entra callbacks matched the original
`oid` and rendered the Services page before and after the mail change; these
checks did not exercise a new password or MFA challenge. Test actual pilot login
denial after its initial password change and MFA setup; an interrupted
authentication flow is not proof of denial. Keep actual HUMAN identifiers private.

The [`operator/entra-owner-mail` unit](../../IaC/terragrunt-catalog/modules/entra-owner-mail/README.md)
retires the historical mail-only Graph PATCH. Its `removed` block forgets only
the retired Terraform state address after a separately reviewed plan; it does
not write Graph or release the old SMTP alias. The supported replacement is an
in-place Entra admin-center conversion of the existing owner, bounded by the
private prepare/attest receipt and independent recovery administrator. Neither
this source declaration nor the older successful mail plan proves that
conversion or any new Fleet login has occurred.

## Harbor registry identities

[Harbor](../operations/harbor-oci.md) uses generated SSM secrets under
`/homelab/harbor/`, file-mounted bootstrap credentials, a private project, and
separate project robots for pull and publication. NOFX receives only the pull
credential through `/homelab/nofx/harbor-pull-password`. Octelium passes native
Authorization headers; Harbor authenticates OCI clients. Registration is
disabled and project creation is admin-only. Public upstream copies remain in
the public-read `mirror` project until node authentication succeeds. Its
`robot$mirror+publisher` is scoped to writes and its separate
`robot$mirror+pull` to authenticated publication receipts and the later Talos
registry-auth candidate; workloads do not receive either credential. Bootstrap
and Harbor recovery use the reviewed upstream transport rollback; see [the image
mirror runbook](../../docs/harbor-image-mirroring.md).

The reviewed Stage A saved plan created and metadata-verified the generated
`/homelab/harbor/mirror-robot-pull-password` without reading its value. The
Stage B desired-state consumer advances `harbor-secrets`' `OnChange` annotation
to `v4` and mounts the reader key in the Harbor bootstrap Job. After External
Secrets materializes the target Secret, that Job can reconcile the separate
read-only robot during execution; require successful PostSync completion before
accepting reader-robot, authenticated-receipt, or Talos behavior. Parameter
creation alone does not create a Harbor robot, grant workload registry access,
enable receipt reads, or change a node. Do not substitute periodic refresh: it
would regenerate Harbor's salted bcrypt registry password hash. Shared Terraform
dependency changes remain separately reviewed and approved. The project stays
public until the separate reviewed Talos path has validated every node; the
later privacy flip must prove uncached authenticated pulls continue to work.

The operator materializer checks the reviewed `main` revision before and after
reading that one SSM value, then writes the fixed reader-auth JSON outside the
checkout in an owner-only `0700` directory with mode `0600`. An ordinary executable
Talos mirror rollout requires that file unless the captured configuration already
has valid `robot$mirror+pull` registry auth; otherwise it stops before it creates
a candidate or applies a machine configuration. Rollback and `--registry-host-only`
execution intentionally do not use reader auth. This rollout gate does not make
the `mirror` project private.

The active Harbor Kustomization stages `harbor/harbor-pull` from the existing
`/homelab/harbor/robot-pull-password`. The vulnerability exporter references
it only for kubelet image pulls, without an app-container mount. The held
[private-core candidate](../../clusters/homelab/apps/harbor/private-core-candidate/README.md)
uses the same prerequisite. That pull-secret path adds no SSM parameter or IAM grant.
Native-image activation waits for publication/scans, recovery clearance and
ExternalSecret readiness. An `OnChange` annotation advance is required after
credential rotation; upstream cold recovery remains.

The native receipt scan robot separately needs
`/homelab/harbor/robot-scan-password` and its exact-ARN reader grant. The
parameter is present as a version 1 `SecureString`; read-only IAM inspection
verified the grant, and a targeted plan from `main` at `f6506136` found no
changes on 2026-10-18. The parameter alone creates no Harbor robot or receipt.
See the
[SSM contract](../../docs/secrets-aws-ssm.md).

The staged Cordium Nocturne controller declares a generated copy of the
existing Harbor pull-robot password at
`/homelab/cordium/nocturne-harbor-pull-password`. Its exact reader grant and
copy require a reviewed private saved plan. The namespace-local
`octelium/cordium-nocturne-pull` ExternalSecret remains excluded from Kustomize
until then; eventual Pods use it only through `imagePullSecrets`. This stage
does not publish or deploy the controller. See the
[Nocturne pull contract](../../docs/secrets-aws-ssm.md#cordium-nocturne-custom-controller-pull).

Harbor OCI signing uses a separate cert-manager-generated P-256 key in the
`harbor-image-signing` Kubernetes Secret, with key rotation disabled during
certificate renewal. The protected in-cluster signing Job mounts that key;
CI receives only its public half through Pod status and verifies signatures.
No AWS signing resource or public transparency log is used. Namespace Pod
creators and cluster administrators can access the key: keep those permissions
restricted, back up etcd to encrypted off-node storage, and retain trusted public
keys independently. See [Harbor Private OCI Registry](../operations/harbor-oci.md) for rollout acceptance.

## Independent application recovery credentials

The staged [application recovery contract](../../docs/application-recovery.md) keeps
publication and read-only verification profiles outside the cluster/NAS. Proposed
IAM policies in `recovery/application-backups` are unattached and scoped to a
dedicated bucket; delete/versioning/lifecycle mutations are denied. No new secret
values, identities or permissions were created. Preserve app encryption/signing
keys and password-free-dump role credentials through the existing private vault.
Archive restore has no cloud credentials or production access and remains gated
on enforced containment.

## Mastodon credential boundary

The [Mastodon declaration](../../IaC/terragrunt-catalog/units/live/aws-ssm-parameters/terragrunt.hcl)
adds ten exact `/homelab/mastodon/` parameters and namespace-scoped External
Secrets access. PostgreSQL, Redis, Rails, encryption, VAPID and the initial
owner password are generated in encrypted state. The external SMTP slot starts
with a rejected placeholder; the protected
[SMTP workflow](../../.github/workflows/mastodon-smtp-credential.yml) injects
only that fixed SecureString from `MASTODON_SMTP_PASSWORD`.

PostgreSQL's protected bootstrap administrator stays separate from the limited
`mastodon_app` role. A local-socket hook provisions that role from the generated
`postgres-app-password`; the application template never receives the bootstrap
password. Redis projects only its own datastore Secret key.

The [runtime template](../../clusters/homelab/apps/mastodon/runtime-externalsecret.yaml)
mounts configuration, VAPID and SMTP as files. Only the owner-bootstrap Job
mounts the generated administrator password; repeat bootstrap preserves the
existing account. `OnChange` and subPath consumers need declared secret/runtime
revisions after rotation. Preserve stable keys with the database. Source
registration and credential storage do not prove deployment, owner login or
email delivery; see the [workload runbook](../../clusters/homelab/apps/mastodon/README.md).
