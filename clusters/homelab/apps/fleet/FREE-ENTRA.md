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
| Mac password synchronization | Not deployed through Fleet. Company Portal Platform SSO registration requires Intune MDM enrollment; Fleet's own Premium password-sync feature stays disabled. |
| Fleet administrator SAML SSO | Supported in Fleet Free. Precreate each authorized console user; leave JIT provisioning and SCIM disabled. Family device users do not automatically become Fleet administrators. |
| Apple OS settings | The Mac password baseline uses explicit, host-scoped Free MDM commands. No global Mac-baseline assignment is desired. |
| Inventory and policy reporting | Retain Fleet's free inventory and supported policy queries, subject to platform and enrollment limitations. |
| Conditional Access and Entra compliance integration | Disabled. Entra registration alone proves neither management nor compliance. |
| Password changes | Known-password changes for cloud-only Entra users are free. Forgotten-password self-service reset and on-premises password writeback require eligible licenses. |

[Fleet's pricing matrix](https://fleetdm.com/pricing) lists SSO, inventory,
policies and OS settings in Free, while automatic user creation, targeted
scoping and Fleet account/password-sync features are Premium. Microsoft
[explicitly included native Password Platform SSO in Entra ID Free](https://techcommunity.microsoft.com/blog/microsoft-entra-blog/platform-sso-for-macos-now-in-public-preview/4051574).
Its [current overview](https://learn.microsoft.com/en-us/entra/identity/devices/macos-psso)
and [third-party MDM guide](https://learn.microsoft.com/en-us/entra/identity/devices/macos-psso-integration-guide)
describe Platform SSO capabilities but do not make Company Portal usable with
Fleet alone. Company Portal requires Intune MDM and licensed users. See also the
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

The retired Mac Platform SSO pilot used the native Microsoft extension and
Company Portal device/user registration. Fleet console SAML never synchronized
Mac passwords, and neither integration makes the other one successful.

The existing public route must keep enrollment, APNs/MDM check-in, fleetd and
Fleet Desktop requests reachable without an interactive Octelium login.
Administrative requests still require Fleet authentication; SAML delegates the
authorized user's login to Entra. Preserve existing tenant MFA. Do not block
the entire `/api/*/fleet/*` prefix: device and administrative APIs share it.
See the [ingress contract](README.md#public-access-and-authentication) and
[Fleet's endpoint guidance](https://fleetdm.com/guides/what-api-endpoints-to-expose-to-the-public-internet).

## Profiles and actual enforcement

These files are the source of truth:

| Profile | Settings requested from Apple |
| --- | --- |
| [Host-scoped Mac baseline](profiles/macos-security-baseline-host.mobileconfig) | Password required, at least 8 characters, non-simple; maximum 5 minutes idle before screen lock; password required immediately after lock. No scheduled expiration, history requirement, forced next-login password change, or failed-attempt threshold is configured. |
| [Host-scoped iPhone/iPad baseline](profiles/ios-passcode-baseline.mobileconfig) | Passcode required, at least 6 characters, non-simple; numeric passcodes allowed; maximum 5 minutes idle before lock; passcode required immediately. No scheduled expiration, passcode history, or failed-attempt erase threshold is configured. |
| [Retired global Mac baseline](profiles/macos-security-baseline.mobileconfig) | Removal reference only. The operator permits deleting its global catalog assignment, not uploading it again. |
| [Retired Mac Platform SSO](profiles/macos-entra-platform-sso.mobileconfig) | Removal reference only. Fleet must not upload or assign it because Company Portal registration requires licensed Intune MDM enrollment. |

Both baselines use `com.apple.mobiledevice.passwordpolicy`. Apple applies the
most restrictive combination when other passcode profiles exist. The Mac
baseline deliberately avoids a mandatory symbol or longer minimum that could
reject an otherwise valid Entra password. Entra's cloud password policy applies
its own three-of-four character-category rule and weak-password checks; the
local Mac baseline alone does not implement that entire rule. Fleet does not
synchronize local passwords with Entra.
See [Entra's policy](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-password-ban-bad-combined-policy)
and [Apple's passcode schema](https://raw.githubusercontent.com/apple/device-management/release/mdm/profiles/com.apple.mobiledevice.passwordpolicy.yaml).

The Mac profiles explicitly target `TargetDeviceType=5`; the iPhone/iPad
baseline targets `1`. The host-scoped Mac baseline has a distinct identifier
and UUID from the retired global baseline; all profile identities remain stable
across updates. They contain no passwords, enrollment secrets or tenant credentials.
No profile enables FileVault, rotates recovery keys or changes encryption state.
An already noncompliant local password can still produce an Apple password-change
prompt; absent `changeAtNextAuth` does not exempt it from the enforced baseline.

Apple User Enrollment and ordinary Device Enrollment are different. Under User
Enrollment, Apple ignores many passcode keys and imposes its own minimum rules.
Removing the retired baseline does not override Apple's enrollment requirements
or another provider's profiles. Fleet profile acknowledgement is delivery evidence; it is not a test
of password complexity, screen locking or a user's current passcode.

### Mac-only baseline through individual installs

The desired state is no global **Family Mac security baseline** catalog entry.
Each Mac receives the host-scoped baseline through an explicit Free MDM command.
New Macs require an operator install; there is no automatic assignment or
continuous drift repair for this baseline.

Fleet Free 4.92.2 sends global Apple profiles to macOS, iOS and iPadOS; its
`platform: darwin` catalog field does not exclude phones. `TargetDeviceType=5`
makes Apple reject installation on an iPhone, but leaves a failed assignment in
Fleet. Team and label targeting require Premium; see
[Fleet's label-scoping restriction](https://fleetdm.com/guides/custom-os-settings#target-hosts-with-labels)
and the [versioned reconciler](https://github.com/fleetdm/fleet/blob/fleet-v4.92.2/server/mdm/apple/reconcile.go#L39).
The owner's chosen Free workflow removes that global assignment and preserves
Mac enforcement with individual installs.

Migrate existing Macs before removing the global entry:

1. Privately identify each intended Mac's Fleet host ID. Install the new baseline
   on each enrolled Mac with the command below. The operator requires platform
   `darwin`, checks enrollment, and verifies acknowledgement and `ProfileList`.
2. Confirm each Mac has
   `com.stinkyboi.fleet.macos.security-baseline.host`. The new identity prevents
   delayed removals of the old global profile from removing the replacement.
3. Remove the retired global catalog entry. The operator checks the exact
   profile identity/content and preserves every other catalog entry.
4. Verify the old entry and iPhone assignment are absent in Fleet. After Fleet's
   asynchronous removal completes, verify fresh Mac `ProfileList` evidence:
   the old `com.stinkyboi.fleet.macos.security-baseline` is absent, the new
   `.security-baseline.host` remains, and unrelated profiles are retained.

```sh
python3 -I scripts/fleet-free-setup.py mac-baseline --host-id <MAC_FLEET_ID> --execute
python3 -I scripts/fleet-free-setup.py mac-baseline-catalog --remove --execute
```

Pending commands are not confirmed installation or removal. If a Mac is offline,
finish its replacement install before removing the global entry. Direct
`RemoveProfile` commands alone do not disable catalog assignment.
`mac-baseline-catalog` is removal-only and rejects re-upload; re-enabling global
assignment requires a reviewed code change.

For a new Mac, run only the `mac-baseline --host-id` install command. Remove its
host-scoped baseline with the same command plus `--remove`; this stops its
enforcement without restoring an earlier password. `mac-pilot` installs the
baseline and removes the retired Platform SSO profile on the privately matched local Mac.
Record actual migration results in the knowledge base after execution; these
instructions alone do not establish live acceptance.

### iPhone/iPad baseline through individual installs

The iPhone/iPad passcode baseline is also a host-scoped Free MDM command. It
does not create a Fleet catalog entry, label assignment, team assignment, or
automatic drift repair. `ios-baseline` accepts only an explicit Fleet ID,
requires a Fleet MDM-connected `ios` or `ipados` host, and validates its Apple
device identifier before a command is sent.

```sh
python3 -I scripts/fleet-free-setup.py ios-baseline --host-id <IPHONE_FLEET_ID> --execute
python3 -I scripts/fleet-free-setup.py ios-baseline --host-id <IPHONE_FLEET_ID> --remove --execute
```

The operator reads `ProfileList` before and after the command, preserving
unrelated profiles. After installation it also reports `SecurityInfo` fields
`PasscodePresent`, `PasscodeCompliant`, and `PasscodeCompliantWithProfiles`.
Those values are compliance observations, not proof that every passcode payload
key took effect. Verify delivery with `ProfileList`, then physically test a
non-simple passcode of at least six characters, the five-minute idle lock,
and immediate reauthentication. User Enrollment can ignore passcode keys, so that test is
required before treating the device as protected. These instructions do not
record a live phone installation or acceptance result.

## Retired Platform SSO pilot

Fleet no longer deploys the Microsoft Platform SSO profile. The profile stays in
this repository only so `mac-pilot --remove` can remove it from the one previously
targeted Mac. It cannot complete through Fleet: Microsoft requires both Intune MDM
enrollment and a licensed user before Company Portal can register a Mac or provide
Platform SSO. This tenant has no subscribed Microsoft service plans, so Company
Portal sign-in fails after Google authentication when it discovers no Intune
service endpoint. Do not retry, upload the profile, or create a Company Portal
exception in Fleet.

Use Fleet for the supported Apple baseline. To use Company Portal or Platform
SSO later, first adopt Intune, configure its Apple MDM prerequisites, assign an
Intune license to each user, and enroll the Mac in Intune. Microsoft documents the
[Intune macOS prerequisites](https://learn.microsoft.com/en-us/mem/intune/enrollment/macos-enroll)
and requires [Intune enrollment before Company Portal PSSO registration](https://learn.microsoft.com/en-us/entra/identity/devices/device-join-microsoft-entra-company-portal).

## Registration failure: personal account and unapplied UPN correction

Historical record only: the original PSSO pilot exposed an identity collision and
an external-account route. The live `stuhlmuller.net` federation now routes to
Google, but Fleet-only Company Portal/PSSO remains unsupported and must stay
retired. Do not repeat the old registration procedure.

### Owner address migration: alias release blocked

Historical record only: the prior owner-address migration did not provide a
Fleet-only Company Portal or PSSO solution. It is retained as an anchor for the
linked identity evidence, not as an operator procedure.

## Platform differences and acceptance

| Platform | Inventory and compliance evidence |
| --- | --- |
| macOS | fleetd/osquery supplies inventory and supported SQL policy results; Apple MDM supplies profile and command evidence. Agent heartbeat and MDM check-in are separate. Query success reports state; it does not enforce a setting. |
| iPhone/iPad | Apple MDM supplies the host-scoped passcode profile plus inventory/status allowed by the enrollment mode. There is no normal desktop fleetd/osquery agent. `SecurityInfo` passcode fields are reporting evidence, not a complete enforcement test; do not promise arbitrary desktop SQL, process inspection or parity with Mac policies. |
| Linux | fleetd/osquery supplies inventory and supported SQL policy results. Apple profiles and macOS Platform SSO do not apply. This change does not modify PAM, local Linux passwords or Linux enforcement. |

Fleet's [profile-status guide](https://fleetdm.com/guides/custom-os-settings)
distinguishes macOS osquery verification from iOS/iPadOS command acknowledgement.
For this host-scoped command pilot, retain the actual command result and
`ProfileList` evidence; for iPhone/iPad, retain the three `SecurityInfo`
passcode fields as reporting evidence and the physical passcode/lock test.
Do not assume a managed-profile UI status will appear.
Missing/stale inventory or unexecuted queries remain untested. Vulnerability-feed
scanning remains disabled under the existing resource decision in the
[main runbook](README.md); enabling inventory does not enable those scans.

Record **passed**, **failed**, and **untested** separately for each device:

| Check | Required evidence |
| --- | --- |
| Fleet enrollment/check-in | Exact device identity matches privately; fresh agent/MDM timestamps and acknowledged device query as applicable. |
| Profile installation/enforcement | Correct profiles in `ProfileList`; inspect effective settings and test screen locking. |
| iPhone/iPad passcode enforcement | The stable iPhone/iPad profile is in `ProfileList`; retain the three `SecurityInfo` passcode values and physically test passcode and lock behavior. Command acknowledgement or `SecurityInfo` alone is insufficient. |
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
The successful [full apply run 37586972225](https://github.com/Stuhlmuller/homelab/actions/runs/37586972225)
reconciled the outstanding range at signed `main` commit
`f47cf006e1108f2c1d13f7d002b0611fcdfc22df`; it is the current checkpoint.
It deliberately does not traverse `IaC/operator`, so it does not apply the
pilot-user rename or prove native PSSO acceptance. Preserve the fail-closed
gate for later ranges; do not mark a focused operator run as `Full` or advance
its baseline manually.

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
python3 -I scripts/fleet-free-setup.py ios-baseline --host-id <IPHONE_FLEET_ID> --execute
nix develop --command python3 -I scripts/fleet-entra-pilot-credentials.py --pilot stuhlmuller --output <PRIVATE_FILE_OUTSIDE_REPO>
```

Omit `--execute` to preview without reading credentials or contacting APIs.
The credential exporter is different: it writes a new mode-0600 file and refuses
existing paths and repository destinations. Open that file privately, complete
the initial known-password change/MFA flow, and remove the obsolete copy when
finished. The file is not a recovery credential after the initial change.

The Mac pilot privately matches both serial and hardware UUID. Individual Mac
baseline installation requires an explicit Fleet ID and verifies `darwin` and
MDM enrollment. iPhone selection requires an explicit Fleet ID and verifies the
platform and Apple identifier.
Each MDM write is submitted once, with a bounded acknowledgement wait. If it
times out, inspect the pending command and device connectivity before retrying;
a timeout does not prove that a change failed. Removal verifies the selected
profile identifiers are absent and unrelated profiles remain installed. Mac
pilot removal uses `mac-pilot --remove`; baseline-only removal uses
`mac-baseline --host-id <MAC_FLEET_ID> --remove`. Retiring the old global baseline
requires its separate catalog removal action. The iPhone/iPad baseline removes
only from its selected host with `ios-baseline --host-id <IPHONE_FLEET_ID> --remove`;
it has no global catalog assignment.
PSSO removal does not revert the user's password or erase its Entra registration.

The reporting action adds only the macOS FileVault observation policy. Linux
enrollment and layout-specific policies need a real Linux host before acceptance.
On Fleet 4.92.2, iOS/iPadOS are not accepted SQL-policy platforms; use MDM
`SecurityInfo` passcode fields and device inventory instead.
