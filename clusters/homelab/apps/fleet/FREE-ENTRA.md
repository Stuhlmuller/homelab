# Fleet Free and Microsoft Entra for family devices

This setup uses the existing Entra tenant, Fleet Free and Apple's configuration
profiles. Mac login and Fleet administrator login are separate integrations.
It does not enroll devices in Intune or enable Fleet Premium, paid add-ons,
trials, Conditional Access, or Fleet's native Entra compliance integration.

## Feature and license boundaries

References checked on 2026-10-03. A feature advertised today must also work
through supported APIs in the deployed Fleet version; a license error is a
stop condition, not permission to bypass the check.

| Capability | Free setup |
| --- | --- |
| Mac password synchronization | Native Microsoft Platform SSO using Company Portal's extension and `AuthenticationMethod=Password`. Fleet's own Premium password-sync feature stays disabled. |
| Fleet administrator SAML SSO | Supported in Fleet Free. Precreate each authorized console user; leave JIT provisioning and SCIM disabled. Family device users do not automatically become Fleet administrators. |
| Apple OS settings | The Mac password baseline can be assigned through the managed profile catalog. Platform SSO uses explicit, host-scoped Free MDM commands. |
| Inventory and policy reporting | Retain Fleet's free inventory and supported policy queries, subject to platform and enrollment limitations. |
| Conditional Access and Entra compliance integration | Disabled. Entra registration alone proves neither management nor compliance. |
| Password changes | Known-password changes for cloud-only Entra users are free. Forgotten-password self-service reset and on-premises password writeback require eligible licenses. |

[Fleet's pricing matrix](https://fleetdm.com/pricing) lists SSO, inventory,
policies and OS settings in Free, while automatic user creation, targeted
scoping and Fleet account/password-sync features are Premium. Microsoft
[explicitly included native Password Platform SSO in Entra ID Free](https://techcommunity.microsoft.com/blog/microsoft-entra-blog/platform-sso-for-macos-now-in-public-preview/4051574).
Its [current overview](https://learn.microsoft.com/en-us/entra/identity/devices/macos-psso)
and [third-party MDM guide](https://learn.microsoft.com/en-us/entra/identity/devices/macos-psso-integration-guide)
support deployment through another MDM; Company Portal installation does not
require changing the MDM authority. This does not claim Microsoft certification
of the Fleet integration. See also the
[current Entra Free feature list](https://www.microsoft.com/en-us/security/business/microsoft-entra-pricing)
(cloud user management, SaaS SSO and cloud-user password changes) and the
[Entra password-change/reset licensing table](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-sspr-licensing).

## Administrator access and public device access

Fleet-console SAML uses a dedicated Entra enterprise application. Assign only
authorized administrators, precreate their Fleet accounts with matching SAML
identities, and test the complete browser callback and resulting Fleet user.
Keep a privately stored local recovery credential until SAML login and recovery
have been verified. Do not grant console access merely because someone owns an
enrolled device.

The first deployed browser test failed with `account_disabled`. Fleet accepted
the signed identity but matched the external Microsoft-account owner's personal
email to the password-only recovery account. The [SAML module](../../../../IaC/modules/azuread-saml-application/README.md)
therefore declares a dedicated, stable Graph claims mapping from
`userprincipalname` to SAML NameID, preserving basic claims and the existing
signing key. Keep the recovery account password-only and the organizational UPN
account SSO-only. After applying a mapping change, verify the real callback,
resulting Fleet account and separate recovery login. Record the acceptance
result privately; a successful plan or settings readback cannot establish
login success. No paid feature, static shared NameID, tenant-owner conversion
or license bypass is used.

Mac Platform SSO uses the native Microsoft extension and device/user
registration. It does not use Fleet's console SAML application to synchronize
passwords. Neither integration makes the other one successful.

The existing public route must keep enrollment, APNs/MDM check-in, fleetd and
Fleet Desktop requests reachable without an interactive Octelium login.
Administrative requests still require Fleet authentication; SAML delegates the
authorized user's login to Entra. Preserve existing tenant MFA. Do not block
the entire `/api/*/fleet/*` prefix: device and administrative APIs share it.
See the [ingress contract](README.md#public-access-and-authentication) and
[Fleet's endpoint guidance](https://fleetdm.com/guides/what-api-endpoints-to-expose-to-the-public-internet).

## Profiles and actual enforcement

These files are the source of truth:

| Profile | Enforced settings |
| --- | --- |
| [Mac baseline](profiles/macos-security-baseline.mobileconfig) | Password required, at least 8 characters, non-simple; maximum 5 minutes idle before screen lock; password required immediately after lock. No scheduled expiration, history requirement, forced next-login password change, or failed-attempt threshold is configured. |
| [Retired iPhone/iPad baseline](profiles/ios-passcode-baseline.mobileconfig) | Removal reference only. No repository-managed iPhone/iPad passcode baseline is desired; the operator rejects installation. |
| [Mac Platform SSO](profiles/macos-entra-platform-sso.mobileconfig) | Microsoft Company Portal extension, `Password` method, shared device keys, existing accounts only. No account creation, authorization/privilege changes, or forced online authentication. |

The Mac baseline uses `com.apple.mobiledevice.passwordpolicy`. Apple applies the
most restrictive combination when other passcode profiles exist. The Mac
baseline deliberately avoids a mandatory symbol or longer minimum that could
reject an otherwise valid Entra password. Entra's cloud password policy applies
its own three-of-four character-category rule and weak-password checks; the
local baseline alone does not implement that entire rule. After successful
PSSO synchronization, the local account uses the accepted Entra password.
See [Entra's policy](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-password-ban-bad-combined-policy)
and [Apple's passcode schema](https://raw.githubusercontent.com/apple/device-management/release/mdm/profiles/com.apple.mobiledevice.passwordpolicy.yaml).

The Mac profiles explicitly target `TargetDeviceType=5`; the retired mobile
baseline targets `1` (iPhone/iPad). Profile identifiers and UUIDs remain stable across
updates. They contain no passwords, enrollment secrets or tenant credentials.
No profile enables FileVault, rotates recovery keys or changes encryption state.
An already noncompliant local password can still produce an Apple password-change
prompt; absent `changeAtNextAuth` does not exempt it from the enforced baseline.

Apple User Enrollment and ordinary Device Enrollment are different. Under User
Enrollment, Apple ignores many passcode keys and imposes its own minimum rules.
Removing the retired baseline does not override Apple's enrollment requirements
or another provider's profiles. Fleet profile acknowledgement is delivery evidence; it is not a test
of password complexity, screen locking or a user's current passcode.

The iPhone/iPad baseline was retired at the owner's request on 2026-10-04 after
it prompted for a compliant passcode. Its payload remains only to identify
existing installations for removal; `validate-profiles` excludes it and
`ios-baseline` requires `--remove`. Removal preserves the current passcode and
other profiles. Re-enabling this baseline requires a reviewed code change.

### Managed Mac password profile

`mac-baseline-catalog` adds **Family Mac security baseline** to Fleet's
**Controls > OS settings > Configuration profiles** using the supported single
profile upload API. It preserves the firewall and other catalog entries, checks
the uploaded content checksum, and leaves the Entra SSO profile host-scoped.
An identical catalog entry is a no-op; a conflicting entry requires review.

Fleet Free 4.92.2 has no draft/disabled profile state. Uploading activates
continuous assignment; it is not storage-only. Team and label targeting require
Premium. Fleet sends global Apple profiles to macOS, iOS and iPadOS; its
`platform: darwin` catalog field does not exclude phones. This profile retains
`TargetDeviceType=5` (Mac). Apple requires the target and device types to match;
verify the phone's rejection and absence of the profile after uploading.
See [Fleet's reconciler](https://github.com/fleetdm/fleet/blob/fleet-v4.92.2/server/mdm/apple/reconcile.go#L39)
and [Apple's TargetDeviceType slide, page 141](https://devstreaming-cdn.apple.com/videos/wwdc/2019/303te9o8pf35qp/303/303_whats_new_in_managing_apple_devices.pdf?dl=1#page=141).

After authorizing enforcement, upload with:

```sh
python3 -I scripts/fleet-free-setup.py mac-baseline-catalog --execute
```

Verify the catalog entry, per-host status and fresh `ProfileList` responses.
Pending delivery is not confirmed installation. Roll back through the same
operator with `mac-baseline-catalog --remove --execute`; it deletes only the
matching catalog entry and verifies that other entries remain. Fleet then
removes its assignment asynchronously. Inspect devices to confirm removal.
This can also remove the same baseline originally installed on the pilot Mac;
it does not restore that Mac's prior unmanaged baseline automatically.
Direct `RemoveProfile` commands alone do not disable managed assignment.

## Existing-account Platform SSO pilot

Use this Mac first. Before registration, verify Fleet user-approved
MDM enrollment, current check-in, Company Portal installation, the intended
Entra account and the user's permission to join/register devices. Prefer the
latest Company Portal; Microsoft's documented minimum is 5.2404.0. Confirm
there is no competing Microsoft Extensible SSO profile.
Profiles can be prepared and their installation acknowledged before Company
Portal is installed; that acknowledgement does not establish extension or user
registration. The inspected tenant permits all users to join/register devices
with a maximum of 50 devices per user; setup does not change those policies.

Use an organizational Entra identity with its own cloud password. The existing
tenant owner is an invited, externally authenticated Microsoft-account member;
`UserType=Member` alone does not establish an internal Entra credential.
Microsoft distinguishes these [identity types](https://learn.microsoft.com/en-us/entra/external-id/user-properties)
and specifies an organizational account for
[PSSO Entra join](https://techcommunity.microsoft.com/blog/microsoft-entra-blog/platform-sso-for-macos-now-in-public-preview/4051574).
No official assurance was found for native Password PSSO with this invited-MSA
identity; that path is unverified, not a reproduced login failure. Preserve the
owner unchanged for tenant administration and separately authorized console SAML.

The earlier `rodman.mac@stinkyboi.com` cloud-only pilot remains unchanged. It is
not part of the `stuhlmuller.net` workflow below, and this runbook must not plan
or apply it. The selected pilot for this Mac is the isolated account documented
in the next section.

### `stuhlmuller.net` Google Workspace pilot

`stuhlmuller.net` remains a Google Workspace domain. The Entra operator unit
reads its existing, non-default managed domain and returns a Microsoft TXT
ownership record. That record is additional DNS data: preserve Google MX,
existing SPF, DKIM and DMARC, and do not enable Microsoft mail services,
Google SSO, Entra federation, directory-wide assignment, or automatic user
provisioning. Adding or verifying the domain neither converts existing Google
users nor forces them through Entra.

After a separate DNS-owner GitOps change publishes the exact TXT record and the
domain is verified, `IaC/operator/entra-stuhlmuller-pilot-user` creates only
`rodman.mac@stuhlmuller.net`. It is a cloud-only Entra password identity for
this Mac's PSSO pilot, not a mailbox, Google account, Fleet administrator or
replacement for `rodman@stuhlmuller.net` recovery access. The existing
`rodman.mac@stinkyboi.com` pilot remains unchanged. Creating any additional
family pilot requires another explicit reviewed user unit; no domain-wide rule
enrolls or redirects anyone.

Record FileVault and secure-token status without recording recovery material.
The user must retain their current local password and existing recovery access.
Register while signed into the existing local account: PSSO changes that
account's password, preserving its username and data. Do not create a new
account, rename its home directory, reset its password administratively or
rotate FileVault keys as part of setup.

The profile sets both the macOS 13 compatibility `AuthenticationMethod` and
the macOS 14+ `PlatformSSO.AuthenticationMethod` to `Password`.
`UseSharedDeviceKeys=true` shares device signing/encryption keys between local
users, while each person still registers their own account. Changing the method
or shared-key setting later can trigger registration again.

`TokenToUserMapping` is omitted because Apple uses it for account creation and
authorization, both disabled here. It is not needed to rename or replace an
existing account. The profile omits Intune's `{{DEVICEREGISTRATION}}` token,
Setup Assistant registration and all privilege mappings. See the
[Apple SSO schema](https://raw.githubusercontent.com/apple/device-management/release/mdm/profiles/com.apple.extensiblesso.yaml)
and [Microsoft configuration guidance](https://learn.microsoft.com/en-us/intune/device-configuration/settings-catalog/configure-platform-sso-macos).

The initial pilot delivers the committed profiles using Fleet's supported Free MDM
command API to the privately matched Mac only. A successful `InstallProfile`
followed by `ProfileList` establishes installation. It does not create continuous
Fleet profile assignment, automatic drift repair, or a family-wide targeting
rule. The catalog action above makes only the password baseline continuously
managed. Revisions and removals require the reviewed repository operator path;
do not substitute ad hoc commands or enable a paid feature after a license error.

Removing the PSSO profile stops that configuration; it does **not** restore the
old local password. Profile removal also does not imply deletion of Entra device
records. Preserve access and inspect registration before any cleanup.

## User action after preparation

1. After the reviewed `stuhlmuller.net` pilot identity apply and private
   credential handoff, sign in to [Microsoft My Account](https://myaccount.microsoft.com/)
   as `rodman.mac@stuhlmuller.net`. Replace the temporary password and complete the
   tenant's required security-information registration. PSSO cannot synchronize
   a temporary password requiring change. Do not alter the existing owner account.
2. Install the [official Microsoft Company Portal package](https://go.microsoft.com/fwlink/?linkid=853070).
   This is the installer linked by [Microsoft](https://learn.microsoft.com/en-us/intune/user-help/enrollment/enroll-company-portal-macos).
   Do not follow its **Begin / Download management profile / Enroll** sequence;
   Fleet remains the MDM.
3. After the Fleet PSSO profile is installed, while signed into the existing
   local account, choose macOS **Registration Required > Register**. Sign in with
   the new internal pilot Entra account and complete any required MFA.
4. Enter the current Mac-account password whenever macOS requests local
   authorization and the new Entra password in Microsoft's prompt; their order
   can vary. Complete password synchronization if prompted. Enter credentials
   only into the Microsoft/macOS UI, never into chat or scripts.
5. Complete the acceptance checks below before repeating this process from each
   other person's existing local account on each Mac.

Microsoft documents that legacy per-user MFA can prevent Password PSSO
synchronization. Its suggested Conditional Access alternative is outside this
free setup. If that conflict occurs, stop and report it; do not disable MFA or
purchase/activate a trial to make the test pass. An unreadable MFA/security-defaults
configuration is **unknown**, not proof that MFA is absent. The inspected tenant
has security defaults enabled; the owner's legacy per-user MFA is disabled.
Verify the new pilot user's state separately. Security defaults remain enabled;
legacy per-user MFA and security defaults are distinct settings. A local password
policy stricter than Entra can also stop synchronization. See
[Microsoft's known issues](https://learn.microsoft.com/en-us/entra/identity/devices/troubleshoot-macos-platform-single-sign-on-extension).

## Platform differences and acceptance

| Platform | Inventory and compliance evidence |
| --- | --- |
| macOS | fleetd/osquery supplies inventory and supported SQL policy results; Apple MDM supplies profile and command evidence. Agent heartbeat and MDM check-in are separate. Query success reports state; it does not enforce a setting. |
| iPhone/iPad | Apple MDM supplies the inventory/status allowed by the enrollment mode. There is no normal desktop fleetd/osquery agent. Only supported MDM-backed tables/status can be reported; do not promise arbitrary desktop SQL, process inspection or parity with Mac policies. |
| Linux | fleetd/osquery supplies inventory and supported SQL policy results. Apple profiles and macOS Platform SSO do not apply. This change does not modify PAM, local Linux passwords or Linux enforcement. |

Fleet's [profile-status guide](https://fleetdm.com/guides/custom-os-settings)
distinguishes macOS osquery verification from iOS/iPadOS command acknowledgement.
For this host-scoped command pilot, retain the actual command result and
`ProfileList` evidence; do not assume a managed-profile UI status will appear.
Missing/stale inventory or unexecuted queries remain untested. Vulnerability-feed
scanning remains disabled under the existing resource decision in the
[main runbook](README.md); enabling inventory does not enable those scans.

Record **passed**, **failed**, and **untested** separately for each device:

| Check | Required evidence |
| --- | --- |
| Fleet enrollment/check-in | Exact device identity matches privately; fresh agent/MDM timestamps and acknowledged device query as applicable. |
| Profile installation/enforcement | Correct profiles in `ProfileList`; inspect effective settings and test screen locking. |
| Entra registration | `app-sso platform -s` reports device and current-user registration; matching tenant/device/user in Entra. Keep identifiers/tokens out of logs. |
| Mac login | User locks and logs out/in with the Entra password; existing account and home data retained. |
| Password-change synchronization | User changes their known Entra password through the cloud account flow, completes the Mac sync prompt, then verifies the new password. |
| Offline login | After confirmed synchronization, disconnect networking and verify login using the last synchronized password; reconnect afterward. |
| FileVault access | User verifies reboot/unlock with retained recovery access available. Record separately from a screen-unlock test. |
| Fleet-console SAML | Complete real Entra browser login and callback; verify the resulting authorized Fleet user and denied unauthorized access. |

Password synchronization is not instantaneous: Microsoft documents prompting
within four hours of an Entra password change. An offline Mac cannot learn an
unseen cloud password; use its last synchronized password. The pilot leaves
FileVault/login/unlock policies unset, preserving local-password fallback.
Do not add `RequireAuthentication`. Microsoft's optional FileVault
`AttemptAuthentication` policy changes preboot behavior and requires a separate
review and test; it is not enabled here. See
[Apple's login-policy behavior](https://support.apple.com/guide/deployment/platform-sso-for-mac-dep7bbb05313/web).

Server health, an installed profile, and Entra registration are distinct
milestones. None substitutes for the interactive login, password-change, offline
and console-SAML acceptance checks.

## Repository operator workflow

Use reviewed, signed, merged `main` and the existing operator's Azure CLI, AWS
and Kubernetes access. The [Entra provider identities](../../../../docs/entra-terraform-provider.md)
use free GitHub OIDC for CI reads and owned-application changes. User creation,
claims-policy changes and administrator assignments remain focused operator
Terraform operations: CI has no corresponding tenant-wide write grants. Run
these two units from the authenticated operator session after their plans and
the repository gate pass, using the same modules and encrypted remote state.

These focused applies do **not** advance the full infrastructure checkpoint.
The last successful full apply is [run 33680144179](https://github.com/Stuhlmuller/homelab/actions/runs/33680144179)
at `82ebd734ad61357faa0f03212613ef15f593ff80`. Before the Fleet identity changes,
`main` already changed the Grafana/Octelium identity units and their shared root
since that checkpoint. Provider OIDC activation and focused Fleet success do
not reconcile that outstanding range. Preserve the fail-closed gate and
checkpoint; review the complete outstanding plan and complete a real full apply
before claiming recovery of the general infrastructure pipeline. Do not mark a
focused run as `Full` or advance its baseline manually.

Generate the explicit stack, plan each unit, inspect the plans privately, then
apply those exact plans after protected merge:

```sh
nix develop --command bash -c 'cd IaC && terragrunt stack generate'
nix develop --command terragrunt --working-dir IaC/live/azuread-applications/fleet plan -out /tmp/fleet-entra-saml.plan
nix develop --command terragrunt --working-dir IaC/live/azuread-applications/fleet apply /tmp/fleet-entra-saml.plan
```

For the `stuhlmuller.net` pilot, first follow the two-stage
[custom-domain operator module](../../../../IaC/modules/entra-domain-verification/README.md):
read the existing domain with verification disabled, publish its exact returned
TXT through the DNS owner's reviewed code path, then enable verification in a
separate reviewed commit. Only after its `Managed`, verified, non-default status
is confirmed may the operator plan and apply
`IaC/operator/entra-stuhlmuller-pilot-user`. Do not add a DNS record manually
or enable a domain-wide Entra/Google SSO setting to shortcut this sequence.

Treat plans, plan JSON, logs and credential outputs as private. Set `umask 077`
inside the Nix shell when saving artifacts. Never attach them to a public PR.
The SAML signing certificate expires on **2027-10-04**; renew through the unit's
reviewed expiry input and rerun the SAML acceptance check. Keep recovery access
during renewal. The pilot user's initial password is generated into encrypted
state, requires change at first login, and is ignored by later applies after
the user takes ownership. The resource prevents accidental destruction and
grants no role, group membership or license.

Prepare application and device settings using the fixed operator commands:

```sh
python3 -I scripts/fleet-free-setup.py validate-profiles --execute
nix develop --command python3 -I scripts/fleet-free-setup.py console-sso --execute
python3 -I scripts/fleet-free-setup.py reporting --execute
python3 -I scripts/fleet-free-setup.py mac-pilot --execute
nix develop --command python3 -I scripts/fleet-entra-pilot-credentials.py --pilot stuhlmuller --output <PRIVATE_FILE_OUTSIDE_REPO>
```

Remove an existing retired iPhone/iPad baseline with:

```sh
python3 -I scripts/fleet-free-setup.py ios-baseline --host-id <IPHONE_FLEET_ID> --remove --execute
```

Omit `--execute` to preview without reading credentials or contacting APIs.
The credential exporter is different: it writes a new mode-0600 file and refuses
existing paths and repository destinations. Open that file privately, complete
the initial known-password change/MFA flow, and remove the obsolete copy when
finished. The file is not a recovery credential after the initial change.

The Mac pilot privately matches both serial and hardware UUID. iPhone selection
requires an explicit Fleet ID and verifies the platform and Apple identifier.
Each MDM write is submitted once, with a bounded acknowledgement wait. If it
times out, inspect the pending command and device connectivity before retrying;
a timeout does not prove that a change failed. Removal verifies the selected
profile identifiers are absent and unrelated profiles remain installed. Mac
profile removal uses `mac-pilot --remove`; if the password baseline is managed,
remove its catalog assignment first. iPhone/iPad supports removal only.
PSSO removal does not revert the user's password or erase its Entra registration.

The reporting action adds only the macOS FileVault observation policy. Linux
enrollment and layout-specific policies need a real Linux host before acceptance.
On Fleet 4.92.2, iOS/iPadOS are not accepted SQL-policy platforms; use MDM
`SecurityInfo` passcode fields and device inventory instead.
