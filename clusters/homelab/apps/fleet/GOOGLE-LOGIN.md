# Google Workspace login on Fleet-managed Macs

## Desired behavior and current state

Fleet is the sole Mac MDM. XCreds supplies the macOS login window and local
account creation/linking using Google Workspace OIDC. Only active users from
`stuhlmuller.net` may authenticate online. New accounts must be standard users;
existing local accounts and recovery access must remain usable.

This route is **not deployed or accepted**. The repository operator below owns
private profile rendering, Fleet delivery and installation of the pinned vendor
package. The non-secret [preferences](google-login-preferences.json) are source
data, not an installable profile; they omit `clientID` and `clientSecret`.
Server health and
Fleet profile delivery do not establish Google login readiness. Microsoft
Platform SSO was retired because the tested Company Portal path required Intune;
do not restore it to implement this route. Console SAML is a separate feature.

## Provider and credential prerequisites

Use a dedicated Web application OAuth client named `XCreds macOS login` in
Google Cloud project `n8n-credentials-498013`. Preserve the existing n8n client.
The dedicated client was created on 2026-10-17. Its initial secret was disabled
and a replacement was saved privately. SecureString injection remains pending;
inspect the existing client before retrying creation.
Verify the OAuth audience is Internal in the `stuhlmuller.net` organization.
The vendor's redirect URI is `https://twocanoes.com/xcreds-redirect`.

`/homelab/fleet/google-oauth` is declared in the shared SSM catalog with
`reader_access = false`. It has no ExternalSecret or application-Pod consumer.
The operator stores the JSON in this SecureString after verifying the exact
client, project, OAuth endpoints and callback. It refuses to create an undeclared
slot. Use the existing SSM apply path before storing credentials.
Keep the client secret out of git, terminal output, PRs and workflow inputs.
Render the device profile privately from that contract; keep only non-secret
settings and references in source. Do not put an administrator password in the
profile to automate account linking or Secure Token grants.

## Profile and installer requirements

The [installer catalog](google-login-installer.json) pins stable XCreds 5.9.1,
build 9157, its vendor URL, SHA-256 and Apple Developer ID Installer identity.
The operator copies the verified bytes into a private directory and requires
macOS signature and notarization acceptance before activation. Fleet Free's
app-delivery limitations mean installation is a local repository-owned operator
step; the Fleet configuration profile alone cannot install XCreds.

Vendor-compiled XCreds requires a license beyond its trial. No license is
provisioned or purchase authorized by this change. An unlicensed pilot must
remain an evaluation, not a completed production rollout. The upstream source
allows free compilation, but this change does not replace vendor signing or
remove license checks.

The staged preferences below must be rendered with the private OAuth credential
into a System-scoped configuration profile. Do not upload the JSON as a profile.
The reviewed profile must include:

| Preference | Desired value |
| --- | --- |
| `discoveryURL` | `https://accounts.google.com/.well-known/openid-configuration` |
| `redirectURI` | `https://twocanoes.com/xcreds-redirect` |
| `scopes` | `profile openid email` |
| `shouldSetGoogleAccessTypeToOffline` | `true` |
| `googleHostDomain` | `stuhlmuller.net` |
| `allowUsersClaim` | `hd` |
| `allowedUsersArray` | `["stuhlmuller.net"]` |
| `CreateAdminUser` | `false` |
| `shouldPromptForMigration` | `true` |
| `shouldShowMacLoginButton` | `true` |
| `shouldSkipFileVaultLogin` | `false` |
| `shouldSkipFileVaultLoginAdmin` | `false` |

The domain hint is not authorization. At upstream revision
`6d70acaf1ed20dd98ca2c0b7b591359752c8f843`, inspected on 2026-10-17,
`XCredsBaseMechanism.setupHints` checks the allowlist only when
the selected claim exists. Therefore an `hd` allowlist alone does not prove
rejection of a token missing `hd`. Require the Internal Google audience and
test personal accounts, other domains and missing-claim behavior before
acceptance. Record the tested installer version and source revision; do not
assume upstream main describes the installed binary.

Use the email claim for account association and verify collisions against
existing short names. Linking requires the existing local user's password;
never reset an unrelated local account merely because its name matches.

## Protected delivery and pilot operator

Merge only after the existing required checks pass. Apply the Fleet-scoped
Terragrunt workflow at exact current `main` to create the operator-only SSM slot
through the shared SSM unit; inspect its private saved plan for unrelated work.
Do not change Google, AWS, Kubernetes or the Mac manually to repair deployment.

Run all writes from a clean checkout on signed, current `main`. The helper
checks the remote head and GitHub commit verification immediately before work.
Its default is a dry run with no credential or service access. It prints fixed
diagnostics on credential-bearing failures; inspect pending MDM commands before
retrying an uncertain write.

```sh
python3 -I scripts/ci/fleet-google-login-test.py
python3 -I scripts/fleet-google-login.py validate
python3 -I scripts/fleet-google-login.py store \
  --credential-file /absolute/private/google-oauth.json --execute
python3 -I scripts/fleet-google-login.py install-profile --execute
python3 -I scripts/fleet-google-login.py install-software \
  --package-file /absolute/private/XCreds-5.9.1-9157.pkg --execute
```

The credential input must be an owner-only regular file outside the checkout.
The operator reads SSM without printing its value, builds the profile in memory
and uses the existing exact-local-Mac Fleet delivery helper. After pilot
acceptance, `install-profile --host-id <Fleet-Mac-ID>` also supports explicit
remote Mac delivery from the trusted operator machine; the existing Fleet
platform/enrollment guard rejects non-Macs and unenrolled hosts. Never copy
operator AWS or Kubernetes credentials onto another user's Mac. It preserves
unrelated profiles and requires Apple acknowledgement and matching profile UUID.
The credential is present on the managed Mac for OIDC token exchange; root on
that Mac can read it. Rotate SSM and reinstall the profile on every managed Mac
after a provider-secret rotation; there is no controller refreshing it for you.

Install the profile before the package: the installer activates the replacement
login window, so the operator refuses installation unless the expected managed
`clientID` is already present. Installation uses `sudo -n`; if no administrator
session is cached, the owner must run `sudo -v` locally and retry. Successful
installation checks the app version and code signature; it does not establish
user login or FileVault acceptance. Do not log out or reboot during unattended
validation.

## FileVault and acceptance

Google login runs after the encrypted volume is unlocked. A brand-new Google
user cannot authenticate to the network at the FileVault preboot screen to
create their first account. An existing volume owner must unlock first. Do not
disable FileVault, enable automatic authenticated restarts, or rotate recovery
keys to hide this boundary.

After protected merge and deployment, verify on the exact Fleet-enrolled pilot:

1. Fleet MDM enrollment and absence of competing MDM enrollment. Inspect the
   local enrollment outside the agent sandbox; correlate hardware identity
   privately with Fleet. Preserve unrelated profiles.
2. Existing local administrator login and an available recovery method before
   enabling the replacement login window. Do not log recovery-key values.
3. Fresh Google user login creates a standard account with the expected home;
   existing-user login links only after proving the local password.
4. Personal Google and other-domain accounts fail. A suspended Workspace user
   cannot obtain a fresh online login. Offline local login is separate and may
   remain usable; cloud suspension is not a disk/account revocation mechanism.
5. Confirm Secure Token and volume-owner status for each test account. Cold
   boot with that account, offline login, and recovery login must be tested
   explicitly. Profile acknowledgement alone proves none of these.
6. Record installer/profile versions, merged SHA, deployment evidence and
   actual sign-in outcomes without credentials or personal device identifiers.

Only then expand beyond the pilot. Removing a configuration profile does not
restore the login authorization database. Roll back through a reviewed operator
path using the installed vendor command
`/Applications/XCreds.app/Contents/Resources/xcreds_login.sh -r`, verify native
local login, and only then remove its managed profile. Preserve users and homes.

Sources: [Google OIDC setup](https://twocanoes.com/knowledge-base/xcreds-setup-with-google-oidc/),
[XCreds administration](https://twocanoes.com/knowledge-base/xcreds-admin-guide/),
[stable releases](https://twocanoes.com/products/mac/xcreds/history/),
[binary licensing](https://twocanoes.com/knowledge-base/licensing-and-pricing-update-for-open-source-projects/),
[login claim check](https://github.com/twocanoes/xcreds/blob/6d70acaf1ed20dd98ca2c0b7b591359752c8f843/XCredsLoginPlugIn/Mechanisms/XCredsBaseMechanism.swift).
