# HOME-57 replacement custody and reader/writer boundaries


The [fixed-proposal integration and finite blocker table](harbor-integration-blockers.md)
records the #1172/#1173 integration, current-main revalidation and HOME-64's
preparation-only decision. All execution and authority gates remain false.

**Repository-only proposal; HOLD.** Based on integration
`d141fa44a7f5992faf9904afa7f1441d2606f470`. HOME-62's rejected issuer remains
hard-disabled in both workflow and helper. This document does not authorize a
new account, credential, permission, environment, execution session or live read.
QA owns the fixture correction/capability extension; Recovery owns hook-safe
stop and executable recovery preparation. Their files are unchanged in this pass.

## What authentication is supported, and what is missing

The repository pins Harbor 2.15.2 with `auth_mode=db_auth`, self-registration
disabled and administrative project creation. Native database users and the
system-administrator role are supported software mechanisms, not an established
operator custody deployment. See [Harbor user administration](https://goharbor.io/docs/2.15.0/administration/managing-users/).

Recommended fallback **for review**: a named, accountable human operator uses an
individually attributable native Harbor system-administrator account through
the existing private access path, on an approved isolated ephemeral operator
workstation. A separately signed repository procedure specifies the one robot
operation. Harbor authentication stays in that operator session; neither its
password nor session material enters Actions, the lifecycle helper, Multica,
issue attachments or general-purpose runner storage. No custom broker/service
is proposed and no issuer robot is recreated.

This has **broad Harbor administration authority**, not server-enforced exact-ID
confinement. The procedure's ID checks constrain compliant execution only.
The operator can affect unrelated robots and other Harbor state. A human
account does not gain a short absolute password lifetime from a short job or
approval window. Browser logout is not proof that previously issued API/bearer
sessions are unusable. Those are residual risks for HOME-62/Decision Review,
not accepted by this proposal.

Unsupported/unverified prerequisites are explicit:

- No named person, person-bound Harbor account, account custody system or
  approved endpoint/workstation has been established. The shared bootstrap
  admin password in `harbor-secrets` is **not** a fallback to fetch.
- No tested native-UI/API operation receipt, protected capture of a newly
  created/refreshed robot secret, or isolated transfer to SSM exists. The
  one-version JSON envelope must move directly from the operator's private
  volatile session to an approved SSM publication path; no chat, clipboard sync,
  downloads, command arguments, shell history, logs or CI artifact handoff.
  The existing helper must not be adapted by injecting admin credentials.
- No approved person-bound AWS authentication path, one-parameter session,
  custody workstation, session termination procedure or sole-writer evidence
  exists. Account creation, role grants and credential delivery require separate
  concrete repository proposals and delegated approval.
- A cryptographically bounded management-credential lifetime, exact session
  revocation semantics and independent bearer-survival evidence are absent.
  If the selected native mechanism cannot meet the approved custody boundary,
  retain HOLD; a requested five/ten-minute operation is not an expiry control.

Before implementation, a session record must name the human custodian and an
independent verifier, exact signed revision, Harbor version, operation, target
ID/name/scopes, expected SSM version, absolute approval start/end, credential
expiry and maximum residual-session duration. First issuance has no ID yet:
record the authorized creation intent and returned ID; a lost response means
UNKNOWN, never permission to adopt a name match. Independent audit/readback
must resolve it under Recovery's separate contract. Finish with sanitized
identity/version/expiry/audit references and termination evidence, never secrets.
SRE owns day-20 renewal readiness; no unattended schedule or standing grant.

## Shared reader inventory and constrained candidate

Reproduce the literal declaration inventory with:

```sh
python3 -I scripts/harbor-credential-boundary-inventory.py
```

[Committed reference inventory](evidence/harbor-credential-boundaries.json)
records source paths and names only. It is not a chart render, registration
inventory, live RBAC/admission result or effective IAM evaluation. After this
correction there are **37** declarations referencing shared `aws-ssm` across
the following **17** allowed namespaces:

| Namespace | Shared-store ExternalSecrets |
| --- | ---: |
| affine | 1 |
| ai | 6 |
| argocd | 1 |
| automation | 4 |
| cert-manager | 1 |
| fleet | 5 |
| harbor | 1 |
| langfuse | 1 |
| media | 4 |
| monitoring | 3 |
| nofx | 4 |
| octelium | 1 |
| octelium-client | 1 |
| octelium-public | 1 |
| octelium-storage | 1 |
| tailscale | 1 |
| wazuh | 1 |

Previously the collector candidate was an additional shared-store consumer.
The shared ClusterSecretStore reads credentials from
`external-secrets/aws-ssm-auth` and the catalog grants reader-group membership to
IAM user `external-secrets_aws-ssm-auth`. The module normally grants exact GetParameter/
GetParameters ARNs for each `reader_access=true` entry plus additional names,
and broader KMS decrypt/describe for the configured keys. An ExternalSecret
author in any allowed namespace could select another authorized parameter;
password-property projection in one manifest does not constrain that author.

Corrections prepared in this branch:

1. Catalog entry `/homelab/harbor/vulnerability-robot-password` now explicitly
   has `reader_access=false` and is absent from the additional-reader list.
   This prevents the module from adding it to the shared reader policy. It is
   not an explicit AWS Deny and does not remove unknown policy grants.
2. The unregistered collector ExternalSecret uses a **namespaced SecretStore**
   `harbor/harbor-vulnerability-reader`, referencing separate
   `harbor/harbor-vulnerability-reader-auth` access-key fields. No such Secret,
   principal or key is created. The existing shared ClusterSecretStore and its
   other consumers are unchanged.
3. `scripts/config/harbor-vulnerability-reader-policy.json` proposes only
   `ssm:GetParameter` on the exact ARN and context/service/account/alias-limited
   `kms:Decrypt`. No path reads, history, enumeration, writes, delete, AssumeRole
   or IAM changes. Missing rights fail closed rather than broadening the policy.
   GetParameter authority permits the whole envelope, including historical
   version selectors; the `secret` property and latest-version polling are
   projection behavior, not IAM field/version restrictions.
   [ESO documents this namespace-scoped SecretStore authentication form](https://external-secrets.io/latest/provider/aws-parameter-store/).

The conservative supported credential form is a dedicated IAM reader's static
access key delivered by a separately approved repository-owned custody process.
It is **not provisioned or accepted**. Static keys lack native expiry; custody,
rotation, loss response and effective-policy inventory remain blockers. Do not
put this key in shared SSM or reuse the shared reader credentials. Federated
workload identity could avoid static custody only after a concrete supported
Talos/OIDC design; EKS IRSA/Pod Identity cannot be assumed here.

A SecretStore prevents cross-namespace references to *that object*. It does not
isolate the cluster-wide ESO controller, cluster admins, Harbor Secret readers,
Pod creators able to mount credentials, or actors able to edit stores/ESO RBAC.
The controller can already handle both shared and dedicated credentials; this
is not controller-compromise isolation. Required evidence: effective RBAC and
admission for those principals, controller chart grants, reader user/group/
attached/inline policy inventory, and direct denied access via shared reader,
other namespaces and other parameters. An IAM policy file is not that evidence.

## Writer authority and OIDC enforcement

The historical role's trust policy binds issuer `token.actions.githubusercontent.com`,
audience `sts.amazonaws.com` and environment-form subject
`repo:Stuhlmuller/homelab:environment:homelab-harbor-vulnerability-credential`.
It does **not** bind workflow filename, branch or SHA. Another job able to enter
that environment and request an ID token can request this role, then call AWS
directly. Helper checks, workflow concurrency and a session policy supplied by
one job do not constrain such a job. Attached role policy must itself limit the
parameter; additional grants could widen it. [GitHub's AWS OIDC contract](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
requires environment protections when using environment subjects. Verify actual
subject format/settings, including any immutable-ID/custom subject opt-in;
never loosen trust to a wildcard just to make authentication succeed.

Before any replacement AWS path, require reviewable source and independently
observed configuration for:

- Existing protected environment, exact main-only deployment rules, required
  delegated reviewers, prevent-self-review and administrator/bypass settings;
  environment name alone does not prove protection. Unknown bypass is HOLD.
- Repository rules enforcing reviews/signatures and workflow/IaC ownership;
  eligible workflow paths, reusable workflows, `id-token:write` jobs, trigger
  types, fork/PR behavior, runner trust, token permissions and permitted Actions.
- Exact provider/thumbprint/audience/subject, role trust and all inline/attached
  policies, permission boundaries, organization controls, KMS grants/key policy,
  role-assumption alternatives, prior STS sessions and policy-modification actors.
- Source/receipt for GitHub administration (the earlier proposal named the
  separate `Stuhlmuller/github-iac` control path; it was not inspected here).
  No verified environment or external role state is claimed in this repository.

The disabled role is historical; it is not automatically the replacement
operator's role. An operator AWS session needs its own approved person-bound
authentication/trust design and exact Get/Put envelope authority. Changing its
trust policy or enabling GitHub's old job is not part of this proposal.

## Potential writers and serialization evidence

| Potential authority | Source evidence / required exclusion |
| --- | --- |
| Historical dedicated Actions job/role | Hard-disabled; trust admits other eligible environment jobs. Enumerate them and all extant sessions; do not infer sole writer from this YAML. |
| General homelab AWS role | Eight workflows reference `AWS_ROLE_TO_ASSUME_HOMELAB`: terragrunt-apply/plan, harbor-migrate/mirror, nofx-images/registry-credential, entra-oidc-verify and octelium-public-tunnel. Resolved identity/policies are unknown, so treat as potential writers until effective exclusion is proved. |
| IaC parameter manager | `aws_ssm_parameter.this` creates sentinel and ignores value updates, but replacement/import/state operations and its execution principal can still affect the parameter. Quiesce approved apply/state operations; ignore_changes is not IAM denial. |
| Other workflows/repositories/direct AWS calls | Organization OIDC trusts, operator SSO/CLI/console, administrator/root/break-glass roles, inherited groups, session credentials and policy editors are not fully inventoried here. Obtain control-plane evidence before claiming exclusion. |
| Recovery/operator publication | Future separate custody paths must participate in the same exclusive session record; none is implemented/approved. No normal-renew retry repairs partial state. |
| ESO | Current literal inventory has no PushSecret/ClusterPushSecret. Reader policy omits writes; live/new objects, alternate store credentials and controller privileges still require inventory. |

**There is no compare-and-swap or transactional publication.**
[PutParameter has no expected-version input](https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_PutParameter.html).
Read-before/write/read-after and version+1 are observations, not a lock. Another
writer can race between them. ESO's one-minute poll can project that conflicting
value before the later check notices it; detecting drift does not undo disclosure
or prove what the Pod consumed.

Proposed serialization is one named, independently supervised operator session
per exact parameter, after effective writer exclusion/quiescence and outstanding
session expiry are demonstrated. Record approval/operation/ID/expected version,
start/end and independent observer; all routine, recovery and IaC paths honor
that same reservation. The record is procedural, not an AWS enforcement
primitive. If any writer or active session cannot be excluded, **do not start**.
No new lock service is proposed, and a GitHub concurrency group only coordinates
cooperating runs in that repository/group.

During authorized future publication retain exporter containment, reconcile
exact ID and SSM version independently, publish once, then prove exact version,
ESO refresh and mounted identity without exposing contents before separately
authorizing enable/start. UNKNOWN, process death, cancellation, unexpected
version or lost response freezes forward work and invokes Recovery's independent
readback procedure. Do not run full Harbor sync: hooks can bootstrap robots,
submit scans and prune backups. Hook-safe operations remain Recovery-owned.

## Separate lifetimes

| Clock | Proposed/declared value | What it does not bound |
| --- | --- | --- |
| Historical Actions credential job | 10-minute timeout; job disabled | Does not revoke AWS credentials, Harbor credentials or minted sessions; abrupt death may skip cleanup. |
| Historical AWS STS request | Explicit 900 seconds, changed from implicit default; job still disabled | Request is not a trust-policy ceiling. A different eligible caller can request up to role maximum. |
| AWS role maximum | 3,600 seconds (minimum configurable role maximum) | May outlast job/approval; changing trust or disabling workflow does not establish issued-session termination. |
| GitHub OIDC token | Actual token expiry must be verified privately; no numeric assumption here | OIDC expiry does not expire a previously issued STS session. |
| Operator Harbor management credential | No enforced absolute lifetime established | Approval window/workstation destruction/logout cannot substitute for server revocation and bearer-survival tests. |
| Proposed dedicated ESO access key | No native expiry; unprovisioned | Requires separately approved rotation/revocation/custody; not bounded by collector lifetime. |
| Collector robot | Requested maximum remaining lifetime 30 days, renew readiness day 20 | Does not bound management credentials or previously minted bearer sessions. Persisted expiry must be read back. |
| API/registry/browser sessions | Observed expiry/revocation semantics still unknown | Stopping Pods or disabling Basic login is not proof of bearer invalidation. |

AWS permits an [AssumeRoleWithWebIdentity request from 900 seconds](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html),
but [CreateRole's maximum-session setting starts at 3,600 seconds](https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreateRole.html).
No shortening or cancellation claim is made for already issued sessions. An
independent termination design must prevent new assumptions, address existing
sessions and verify denied calls/expiry under separately approved test scope.

## Decisions and acceptance still required

Return to HOME-62/Decision Review whether the broad **person-bound native admin**
fallback, static dedicated reader key and shared ESO controller trust are
acceptable *after* custody and independent capability evidence exists. If not,
retain HOLD while identifying an existing server-enforced alternative; no new
broker or issuer revival. No serious risk acceptance is requested now.

Decision Desk cannot approve execution on these files alone. Missing: named
custodian, supported private secret-transfer/publication adapter, IAM/RBAC/
environment enforcement receipts, exclusion of all writers/sessions, signed
revisions, concrete disposable provision/checkpoint/teardown, corrected QA
positive controls, executable Recovery and hook-safe stop, full validation,
proxy runtime/rotation evidence and HOME-3 enforcement. The read split and
offline tests are preparation; no claim of independent all-hop acceptance.
