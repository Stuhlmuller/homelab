# Fleet Free and Microsoft Entra for family devices

This setup uses the existing Entra tenant, Fleet Free and Apple's configuration
profiles. Mac login and Fleet administrator login are separate integrations.
It does not enroll devices in Intune or enable Fleet Premium, paid add-ons,
trials, Conditional Access, or Fleet's native Entra compliance integration.

## Feature and license boundaries

References checked on 2026-10-10. A feature advertised today must also work
through supported APIs in the deployed Fleet version; a license error is a
stop condition, not permission to bypass the check.

| Capability | Free setup |
| --- | --- |
| Mac password synchronization | Candidate native Microsoft Platform SSO using Microsoft Authenticator, Company Portal's extension, and `AuthenticationMethod=Password`. Before a fresh probe, `mac-pilot` removes the repository-owned PSSO profile. Accept only registration without Intune, Entra Premium, a trial, or another paid entitlement. Fleet Premium password sync stays disabled. |
| Fleet administrator SAML SSO | Supported in Fleet Free. Precreate each authorized console user; leave JIT provisioning and SCIM disabled. Family device users do not automatically become Fleet administrators. |
| Apple OS settings | The Mac and iPhone/iPad password baselines use explicit, host-scoped Free MDM commands. The PSSO profile is host-scoped; `mac-pilot` removes it before a fresh probe and reinstalls it only for that probe. No global Mac-baseline assignment is desired. |
| Inventory and policy reporting | Retain Fleet's free inventory and supported policy queries, subject to platform and enrollment limitations. |
| Conditional Access and Entra compliance integration | Disabled. Entra registration alone proves neither management nor compliance. |
| Password changes | Known-password changes for cloud-only Entra users are free. Forgotten-password self-service reset and on-premises password writeback require eligible licenses. |

[Fleet's pricing matrix](https://fleetdm.com/pricing) lists SSO, inventory,
policies and OS settings in Free, while automatic user creation, targeted
scoping and Fleet account/password-sync features are Premium. Microsoft's
[current overview](https://learn.microsoft.com/en-us/entra/identity/devices/macos-psso)
requires Intune or another supported MDM and directs third-party MDM users to
their vendor. Its [third-party MDM guide](https://learn.microsoft.com/en-us/entra/identity/devices/macos-psso-integration-guide)
confirms the payload values, but neither current source confirms a zero-cost,
non-Intune entitlement for this tenant. The 2024
[public-preview announcement](https://techcommunity.microsoft.com/blog/microsoft-entra-blog/platform-sso-for-macos-now-in-public-preview/4051574)
is historical, not current licensing proof. This repository installs Company
Portal only for its SSO extension and does not invoke Intune enrollment or
change Fleet's MDM authority. The one-device pilot must prove no-cost
eligibility; it does not claim Microsoft certification of Fleet. See also the
[current Entra Free feature list](https://www.microsoft.com/en-us/security/business/microsoft-entra-pricing)
(cloud user management, SaaS SSO and cloud-user password changes) and the
[Entra password-change/reset licensing table](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-sspr-licensing).

## Administrator access and public device access

Fleet-console SAML and Mac Platform SSO are separate. The Entra SAML application
maps `userprincipalname` to Fleet's SAML NameID. After the supported Entra
conversion, that claim is exactly `rodman@stuhlmuller.net`; it does not
synchronize a Mac password.

Fleet starts with one local recovery administrator. After the Entra SAML
application is applied, stage the second administrator before conversion:

| Fleet account | Fresh bootstrap | Staged/final state |
| --- | --- | --- |
| `rodman@stuhlmuller.net` | Absent | Precreated SSO admin |
| `rodman@stinkyboi.com` | Local bootstrap/recovery | Local recovery |

Run `console-sso --execute` without a password file while logged in as the local
recovery account. It configures the reviewed SAML metadata, precreates the exact
target as an SSO-only Fleet administrator, and verifies both accounts. It does
not sign in as the target before Entra conversion. After attestation, rerun the
same no-file command to verify the final topology, then complete the interactive
browser SAML test. A `--current-password-file` is only for an older deployment
that already has a target local administrator; do not use it for this bootstrap.

Terraform resolves the tenant owner, Fleet assignment, Grafana ownership and
Octelium ownership by immutable Entra object ID before the UPN changes. Existing
SAML role assignment keys remain Terraform addresses, not sign-in names. This
preserves grants and ownership through the conversion without creating a second
Entra identity.

The existing public route must keep enrollment, APNs/MDM check-in, fleetd and
Fleet Desktop requests reachable without an interactive Octelium login.
Administrative requests still require Fleet authentication; SAML delegates the
authorized user's login to Entra. Preserve existing tenant MFA. Do not block the
entire `/api/*/fleet/*` prefix: device and administrative APIs share it. See the
[ingress contract](README.md#public-access-and-authentication) and
[Fleet's endpoint guidance](https://fleetdm.com/guides/what-api-endpoints-to-expose-to-the-public-internet).

## Profiles and actual enforcement

These files are the source of truth:

| Profile | Settings requested from Apple |
| --- | --- |
| [Host-scoped Mac baseline](profiles/macos-security-baseline-host.mobileconfig) | Password required, at least 8 characters, non-simple; maximum 5 minutes idle before screen lock; password required immediately after lock. No scheduled expiration, history requirement, forced next-login password change, or failed-attempt threshold is configured. |
| [Host-scoped iPhone/iPad baseline](profiles/ios-passcode-baseline.mobileconfig) | Passcode required, at least 6 characters, non-simple; numeric passcodes allowed; maximum 5 minutes idle before lock; passcode required immediately. No scheduled expiration, passcode history, or failed-attempt erase threshold is configured. |
| [Retired global Mac baseline](profiles/macos-security-baseline.mobileconfig) | Removal reference only. The operator permits deleting its global catalog assignment, not uploading it again. |
| [Mac Platform SSO](profiles/macos-entra-platform-sso.mobileconfig) | Microsoft Authenticator and Company Portal's extension; `Password` method, shared device keys, existing accounts only. No account creation, privilege changes, or `RequireAuthentication`. Registration and password sync need Entra connectivity; offline login with the last synchronized password needs a separate acceptance test. |

Both baselines use `com.apple.mobiledevice.passwordpolicy`. Apple applies the
most restrictive combination when other passcode profiles exist. The Mac
baseline deliberately avoids a mandatory symbol or longer minimum that could
reject an otherwise valid Entra password. Entra's cloud password policy applies
its own three-of-four character-category rule and weak-password checks; the
local Mac baseline alone does not implement that entire rule. If Password PSSO
registration succeeds, the local account uses the accepted Entra password.
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
enforcement without restoring an earlier password. `mac-pilot` remains the
single local first-device probe: before its fresh install, it removes only the
repository-owned PSSO profile and verifies its absence while retaining the
baseline and unrelated profiles. After a successful no-cost probe,
`mac-psso --host-id` installs or removes only Platform SSO on one enrolled Mac;
its removal preserves the host-scoped baseline. Use that PSSO-only removal if an
entitlement check fails. Record actual migration results in the knowledge base
after execution; these instructions alone do not establish live acceptance.

### iPhone/iPad baseline through individual installs

The iPhone/iPad passcode baseline is also a host-scoped Free MDM command. It
does not create a Fleet catalog entry, label assignment, team assignment, or
automatic drift repair. `ios-baseline` accepts only an explicit Fleet ID,
requires a Fleet MDM-connected `ios` or `ipados` host, and validates its Apple
device identifier before a command is sent.

```sh
python3 -I scripts/fleet-free-setup.py ios-baseline \
  --host-id <IPHONE_FLEET_ID> --execute
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

## Existing-account Platform SSO pilot

Use this Mac first. Before the one-device eligibility probe, verify Fleet
user-approved MDM enrollment, a current MDM check-in, [Microsoft
Authenticator][authenticator] registered for the target account, Company Portal
installation, the intended Entra account and the user's permission to
join/register devices. Install Authenticator on a phone and complete its Entra
registration before the Mac flow. Prefer the latest Company Portal; Microsoft's
documented minimum is 5.2404.0. Confirm there is no competing Microsoft
Extensible SSO profile. Do not accept a trial, license purchase, or Intune
enrollment. Profile acknowledgement only proves delivery; it does not prove
registration, no-cost eligibility, or password synchronization.

The exact identity for this pilot is the existing Entra owner object, converted
in place from its external Microsoft-account sign-in to an internal Entra user
with UPN `rodman@stuhlmuller.net`. It keeps its Entra object ID, so Terraform
ownership and application assignments remain attached. It receives a new Entra
password and may require fresh security-information registration. This is the
supported external-to-internal conversion documented in the
[Entra provider runbook](../../../../docs/entra-terraform-provider.md), not a
new user, a pilot rename, an SMTP-alias change, or a support case.

`rodman.mac@stuhlmuller.net` remains the separate cloud-only pilot declared by
`IaC/operator/entra-stuhlmuller-pilot-user`; it must remain unchanged. The
conversion touches only the existing owner object. It does not create, redirect,
license, federate, or otherwise affect other `stuhlmuller.net` users.

### `stuhlmuller.net` Google Workspace boundary

`stuhlmuller.net` remains a Google Workspace domain. The Entra domain unit reads
its existing managed-domain state and its TXT ownership record is additional DNS
data: preserve Google MX, SPF, DKIM and DMARC. Do not enable Microsoft mail,
Google federation, directory-wide assignment, or automatic user provisioning.
Domain verification lets Entra issue the converted owner's UPN; it does not
change any Google account or require other people to use Entra.

Before conversion, create and successfully test an independent cloud-only Entra
Global Administrator. Do not convert the sole working tenant administrator. The
independent account is a recovery precondition, not a family-device identity or
a Fleet administrator. The focused
`operator/entra-emergency-global-admin` Terraform unit is disabled for
apply/destroy by its source-controlled default-false
`emergency_global_admin_enabled` literal. After explicit authorization, set that
literal true only through a separate signed, reviewed change and apply its
reviewed plan to create the cloud-only recovery account and permanent role
assignment. Test its independent login, then restore the literal to false in a
separate signed change. Keep a verified local Fleet administrator until the
post-conversion console-SAML test passes.

Record FileVault and secure-token status without recording recovery material.
If Password PSSO eligibility and registration succeed, register while signed
into the existing local account: PSSO changes that account's password,
preserving its username and data. Do not create a new local account, rename its
home directory, reset its password administratively or rotate FileVault keys as
part of setup.

The profile sets both the macOS 13 compatibility `AuthenticationMethod` and the
macOS 14+ `PlatformSSO.AuthenticationMethod` to `Password`.
`UseSharedDeviceKeys=true` shares device signing/encryption keys between local
users, while each person still registers their own account. `TokenToUserMapping`
is omitted because account creation and authorization changes are not enabled.
The profile omits Intune's `{{DEVICEREGISTRATION}}` token, Setup Assistant
registration and privilege mappings. See the
[Apple SSO schema](https://raw.githubusercontent.com/apple/device-management/release/mdm/profiles/com.apple.extensiblesso.yaml)
and [Microsoft configuration guidance](https://learn.microsoft.com/en-us/intune/device-configuration/settings-catalog/configure-platform-sso-macos).

The initial no-cost eligibility probe may deliver the committed profiles with
Fleet's supported Free MDM command API to this matched Mac only. Before that
fresh install, `mac-pilot` removes the repository-owned PSSO profile if present
and verifies its absence with `ProfileList`, retaining the baseline and unrelated
profiles. `InstallProfile` followed by `ProfileList` then proves the fresh probe
delivery. This cannot erase an Entra registration or restore a synchronized local
password. It does not create continuous Fleet profile assignment, automatic drift
repair, or family-wide targeting. If Entra requests a paid entitlement, run
`mac-psso --host-id <MAC_FLEET_ID> --remove --execute` to remove only the PSSO
profile and leave the Mac baseline enforced.

## User action after preparation

1. Merge and apply the reviewed immutable-object Terraform refactor. Its plans
   must retain the owner object, Fleet assignment, Grafana ownership and
   Octelium ownership without replacement or role reassignment. Confirm the
   applied `operator/entra-stuhlmuller-domain` output is verified, managed,
   non-default and non-initial. After explicit authorization, separately set the
   source-controlled recovery literal true, apply the guarded unit, verify the
   independent cloud-only Global Administrator can sign in, then restore the
   literal to false in a signed change.
2. Stage the Fleet SAML configuration and precreate the authorized SSO
   administrator while the local recovery account is still usable:

   ```sh
   nix develop --command python3 -I scripts/fleet-free-setup.py console-sso --execute
   ```

   This must report the reviewed staged topology. It does not prove an
   interactive SAML login and must not be substituted with a target password
   login.
3. From clean, signed current `main`, create the private conversion receipt. The
   directory must already be mode `0700` and outside every Git checkout:

   ```sh
   nix develop --command python3 -I scripts/entra-owner-conversion.py prepare \
     --expected-sha <SIGNED_CURRENT_MAIN_SHA> \
     --receipt-directory <PRIVATE_MODE_0700_DIRECTORY_OUTSIDE_GIT>
   ```

   It makes only Microsoft Graph v1.0 reads. It refuses an unverified domain,
   occupied target UPN, wrong owner object, unclean checkout, or unsigned/stale
   `main`.
4. After direct authorization, in Entra admin center use only **Convert to
   internal user** for that prepared external owner. Set the UPN to exactly
   `rodman@stuhlmuller.net` and set the new Entra password. Do not alter the
   separate `rodman.mac@stuhlmuller.net` pilot or Google Workspace. No support
   case, Graph beta/API write, browser automation, user creation, or alias change
   is allowed.
5. Complete required password and security-information registration through
   [Microsoft My Account](https://myaccount.microsoft.com/). Sign in to Azure
   CLI as `rodman@stuhlmuller.net` with its new tenant password, then attest the
   immutable object and target UPN with the same receipt and SHA:

   ```sh
   nix develop --command python3 -I scripts/entra-owner-conversion.py attest \
     --expected-sha <SIGNED_CURRENT_MAIN_SHA> \
     --receipt-directory <SAME_PRIVATE_MODE_0700_DIRECTORY>
   ```

   The receipt must show the same object as an internal `Member` with the exact
   target UPN, `externalUserState: null`, one local `userPrincipalName` identity
   issued by the tenant default domain, and `onPremisesSyncEnabled: null` (never
   directory-synced). It also requires a password timestamp strictly after
   preparation and `/me` from the new
   target-account token. `Member` and the historical `creationType: Invitation`
   alone do not prove local-tenant authentication. Rerun the protected Entra
   OIDC verification from this `main` to reconcile Terraform data sources; there
   is no user resource to import.
6. Re-run the staged Fleet topology verifier after attestation:

   ```sh
   nix develop --command python3 -I scripts/fleet-free-setup.py \
     console-sso --execute
   ```

   It verifies the local recovery account and the exact SSO-only target. Complete
   the browser callback test in the acceptance table; this API readback alone
   does not prove SAML login.
7. Install [Microsoft Authenticator][authenticator] for the target account and
   the [official Microsoft Company Portal package][company-portal]. Do not
   follow Company Portal's **Begin / Download management profile / Enroll**
   sequence; Fleet remains the MDM.
8. Run the one-device `mac-pilot` eligibility probe only if its registration
   flow offers no Intune enrollment, trial, license purchase, or other paid
   entitlement. It first removes and attests absence of only the repository PSSO
   profile on this exact Mac, retaining the baseline and unrelated profiles,
   before it installs a fresh probe. Stay signed in to the existing local Mac
   account and choose macOS **Registration Required > Register**. Sign in as
   `rodman@stuhlmuller.net`, complete MFA, and enter the current local-account
   password when macOS requests it. If any paid condition appears, run
   `mac-psso --host-id <MAC_FLEET_ID> --remove --execute`, report PSSO unavailable,
   and retain the Mac baseline. This cleanup cannot erase an Entra registration
   or restore an old local password. Enter credentials only in the Microsoft/macOS
   UI, never in chat or scripts.
9. After the first Mac passes every acceptance check, repeat only the explicit
   per-Mac flow for each family Mac: enroll and check in with Fleet, install
   `mac-baseline --host-id <MAC_FLEET_ID> --execute`, install
   `mac-psso --host-id <MAC_FLEET_ID> --execute`, then have that local user
   complete the physical registration. Use the same `mac-psso` command plus
   `--remove` to roll back PSSO without removing the baseline.
10. Complete the acceptance checks below before reporting a different local
   account or family Mac as managed.

Microsoft documents that legacy per-user MFA can prevent Password PSSO
synchronization. Its Conditional Access alternative is outside this free setup.
If that conflict occurs, record it as a failure; do not disable MFA, enable a
trial, or purchase a license to make the pilot pass. A stricter local password
policy can also block synchronization. See [Microsoft's known issues](https://learn.microsoft.com/en-us/entra/identity/devices/troubleshoot-macos-platform-single-sign-on-extension).

## Registration failure and historical alias-release evidence

On October 6, 2026, the Mac Microsoft SSO extension reached the personal-account
tenant and rejected `Device.Join` with `invalid_scope`
(`MSIDOAuthErrorDomain -51413`). Read-only Graph inspection found the separate
cloud pilot at `rodman.mac@stuhlmuller.net`, while the requested exact UPN was
already reserved by the external owner object's mail/proxy data. A focused
pilot rename failed with `DirectoryUniquenessException`; repeated registration
attempts did not change identity state.

### Owner address migration: alias release blocked

This is historical evidence, not an operator path. The reviewed mail-only Graph
PATCH preserved the owner's object ID, UPN, external identity, roles, grants and
application ownership, but it did not release `rodman@stuhlmuller.net` from its
secondary SMTP alias. `proxyAddresses` is read-only; clearing `otherMails` is
not a supported alias-release mechanism and can remove a contact/recovery value.
Read-only Exchange queries found no mail-enabled recipient that could use the
Exchange route. No Exchange license, trial, write, support case, or alias
workaround is needed or authorized.

The mail-only Terraform resource is retired and must not run again. The supported
replacement is the in-place Entra external-to-internal conversion above. It
keeps the existing object ID while assigning the required UPN, so it avoids the
alias-release and pilot-rename path entirely. The conversion and the resulting
interactive logins are still untested until performed; historical successful
plans, mail readback, Octelium session checks and Fleet health do not establish
PSSO or console-SAML acceptance.

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
unseen cloud password; use its last synchronized password. The pilot does not
modify FileVault or login/unlock policies. Do not add `RequireAuthentication`.
Microsoft's optional FileVault
`AttemptAuthentication` policy changes preboot behavior and requires a separate
review and test; it is not enabled here. See
[Apple's login-policy behavior](https://support.apple.com/guide/deployment/platform-sso-for-mac-dep7bbb05313/web).

Server health, an installed profile, and Entra registration are distinct
milestones. None substitutes for the interactive login, password-change, offline
and console-SAML acceptance checks.

## Repository operator workflow

Use reviewed, signed, merged `main` and the existing operator's Azure CLI, AWS
and Kubernetes access. The [Entra provider identities](../../../../docs/entra-terraform-provider.md)
use free GitHub OIDC for CI reads and owned-application changes. The conversion
itself is a supported Entra admin-center operation; it has no supported GA
Terraform resource. Terraform remains the source of truth for the object-ID
references, application ownership and SAML configuration around it.

Before the portal conversion, generate the explicit stack, validate the changed
units and inspect private saved plans after protected merge:

```sh
nix develop --command bash -c 'cd IaC && terragrunt stack generate'
nix develop --command terragrunt --working-dir IaC/live/azuread-applications/fleet plan -out /tmp/fleet-entra-saml.plan
nix develop --command terragrunt --working-dir IaC/live/azuread-applications/fleet apply /tmp/fleet-entra-saml.plan
```

The plans must keep the existing owner object, Fleet assignment, Grafana
ownership and Octelium ownership. Stop for a user replacement, application
replacement, role revocation/regrant, changed application ID, signing key,
callback, secret, license or directory-wide permission. The retired
`operator/entra-owner-mail` unit must only remove its obsolete mail-PATCH state;
it must not call Graph.

After explicit authorization, enable the guarded recovery unit in a separate
signed, reviewed change, then create and test the independent cloud-only Global
Administrator before conversion. The domain output must be verified, managed,
non-default and non-initial. Run the private `entra-owner-conversion.py prepare`
transaction from the exact signed `main`; only after it passes may the Entra
admin center convert the existing external owner to
`rodman@stuhlmuller.net`. Run `attest` with the same receipt immediately after,
then verify a fresh Entra sign-in and the protected Entra OIDC workflow. Do not
create a second target user, rename `rodman.mac@stuhlmuller.net`, alter Google
Workspace, attempt SMTP-alias release, or make a Graph/API write. No support
case is required.

### Existing target-local Fleet topology only

The fresh recovery bootstrap uses the no-file staging and verification flow
above. If an already deployed Fleet instance instead has a target-local
`rodman@stuhlmuller.net` administrator, stage its SAML transition **before** the
Entra conversion with a mode-0600 private file containing the current
target-local Fleet password. It may differ from the SSM
`/homelab/fleet/admin-password` recovery password:

```sh
nix develop --command python3 -I scripts/fleet-free-setup.py \
  console-sso --current-password-file <PRIVATE_FILE_OUTSIDE_REPO> --execute
nix develop --command python3 -I scripts/fleet-free-setup.py console-sso --execute
```

The first command authenticates the target-local account, creates
`rodman@stinkyboi.com` as a local recovery administrator using the existing SSM
secret, reads back the exact two-account topology, and proves a recovery login
before it configures SAML or enables SSO for the target. If creation, readback,
or recovery login fails, it does not enable target SSO. After the Entra
conversion and attestation, the no-file command verifies the final state. Delete
the temporary password file afterward. Never use recovery-authentication tooling
until this historical migration succeeds, use this legacy path for a fresh
recovery bootstrap, or put the file, plan output, credentials or Entra
identifiers in Git, a public PR or chat.

Prepare the Free device settings only after the identity work is complete:

```sh
python3 -I scripts/fleet-free-setup.py validate-profiles --execute
python3 -I scripts/fleet-free-setup.py reporting --execute
python3 -I scripts/fleet-free-setup.py mac-baseline --host-id <MAC_FLEET_ID> --execute
python3 -I scripts/fleet-free-setup.py ios-baseline \
  --host-id <IPHONE_FLEET_ID> --execute
```

The Mac pilot privately matches serial and hardware UUID. Run `mac-pilot` only
for the no-cost PSSO eligibility probe described above; it first verifies the
repository PSSO profile is absent while retaining the baseline and unrelated
profiles, then installs a fresh probe. `mac-psso --host-id` is the post-pilot,
one-Mac rollout and PSSO-only rollback path. Individual Mac and phone baseline
actions require an explicit Fleet host ID where shown and verify enrollment
before sending one bounded MDM command. If acknowledgement times out, inspect
device connectivity and the pending command before retrying. PSSO removal does
not restore a prior password or erase Entra registration.

The reporting action adds only a macOS FileVault observation policy. Linux needs
a real host before inventory/policy acceptance. On Fleet 4.92.2, iOS/iPadOS are
not SQL-policy platforms; use MDM `SecurityInfo` passcode fields and device
inventory instead.

[authenticator]: https://www.microsoft.com/en-us/security/mobile-authenticator-app
[company-portal]: https://go.microsoft.com/fwlink/?linkid=853070
