# WireGuard and AirVPN on family Apple devices

The [catalog entry](profiles/airvpn-catalog.json) declares the official WireGuard
downloads for macOS and iPhone/iPad and a Mac installation-reporting policy.
The [operator](../../../../scripts/fleet-airvpn-setup.py) builds an Apple VPN
profile in memory from a privately supplied AirVPN WireGuard `.conf` file.
The configuration is required before a VPN can be provisioned.

Fleet Free supports OS profiles and policies, but app deployment and software
self-service require Premium. A SQL policy reports installation and gives a
download link; it cannot install WireGuard. iPhone/iPad installation is checked
on the device, not through the Mac SQL policy. No paid feature is enabled.
See [Fleet's feature matrix](https://fleetdm.com/pricing) and the deployed
[v4.92.2 App Store API implementation](https://github.com/fleetdm/fleet/blob/fleet-v4.92.2/server/service/vpp.go).

## Install the app

- macOS: [WireGuard in the Mac App Store](https://apps.apple.com/app/wireguard/id1451685025).
- iPhone/iPad: [WireGuard in the App Store](https://apps.apple.com/app/wireguard/id1441195209).

Install and open the app on each selected device. These are the GUI apps linked
by [WireGuard](https://www.wireguard.com/install/); `wireguard-tools` alone does
not provide the Apple VPN extension. Open WireGuard again after profile delivery
so it can migrate the configuration into its keychain.

## Provision a supplied AirVPN configuration

Use a reviewed, signed, merged `main` checkout and the existing Fleet operator
credentials. The script shares the initial administrator authentication path
with `fleet-free-setup.py`; it does not reset a changed administrator password.

```sh
# Local catalog preview; no credentials or network access.
python3 -I scripts/fleet-airvpn-setup.py catalog

# Preview, then add the Mac reporting policy to Fleet.
python3 -I scripts/fleet-airvpn-setup.py policy
python3 -I scripts/fleet-airvpn-setup.py policy --execute
```

Generate a separate AirVPN client configuration for each concurrently used
device. Keep it outside every repository in a private local file owned by the
operator with permissions `0600`. Do not paste it into chat, a policy, a PR,
command arguments, or public storage. The input must contain one interface and
one peer; unsupported shell hooks and Linux-only options are rejected.

```sh
# The path is a placeholder for an existing private AirVPN export.
chmod 600 /absolute/private/path/airvpn-mac.conf
python3 -I scripts/fleet-airvpn-setup.py macos \
  --config /absolute/private/path/airvpn-mac.conf
python3 -I scripts/fleet-airvpn-setup.py macos \
  --config /absolute/private/path/airvpn-mac.conf --execute

# Use a different export and explicitly selected enrolled iPhone/iPad ID.
python3 -I scripts/fleet-airvpn-setup.py ios --host-id <FLEET_HOST_ID> \
  --config /absolute/private/path/airvpn-mobile.conf
python3 -I scripts/fleet-airvpn-setup.py ios --host-id <FLEET_HOST_ID> \
  --config /absolute/private/path/airvpn-mobile.conf --execute
```

Dry runs validate locally without reading Fleet credentials or contacting any
API. Execution matches this Mac by serial and hardware UUID, or validates the
explicit iPhone/iPad ID. The device must use ordinary Device Enrollment;
[Apple's VPN payload](https://github.com/apple/device-management/blob/release/mdm/profiles/com.apple.vpn.managed.yaml)
is unavailable with User Enrollment. Unknown enrollment state is a stop
condition. On both platforms, the operator requests only `UDID` through Apple's
[`DeviceInformation` command](https://github.com/apple/device-management/blob/release/mdm/commands/information.device.yaml)
and matches `QueryResponses.UDID` to the selected Fleet device. Apple forbids
that query for User Enrollment. A missing or mismatched result blocks profile
delivery; neither the command envelope nor Fleet's personal ownership label is
sufficient. It also requests the selected app's `InstalledApplicationList`
entry before installation. Removal does not require these checks or the original
export. No device is enrolled by this command.

The operator uses WireGuard's supported `com.apple.vpn.managed` payload with
the platform's app bundle ID and `VendorConfig.WgQuickConfig`. It preserves the
supplied addresses, endpoint, allowed routes and DNS; it adds no automatic
connection or kill-switch behavior. Details are in
[WireGuard's profile specification](https://git.zx2c4.com/wireguard-apple/about/MOBILECONFIG.md).

This is a repository catalog and explicit-device provisioning workflow. It
does not upload private VPN material to Fleet's global managed-profile catalog:
unscoped profiles there would distribute one AirVPN client key to every device
of that platform. Targeted catalog assignment requires Fleet Premium. The
existing Free MDM command path installs only on the selected device, preserves
other profiles, and does not continuously repair profile drift.

The private configuration exists in operator memory, Fleet's MDM command data
and database backups, and the target device's profile/keychain. Treat access to
those as credential access. Nothing writes a populated `.mobileconfig` to the
checkout or prints its contents. This does not reuse the Deluge VPN secret or
create a new SSM parameter.

## Verify and remove

The operator verifies profile acknowledgement, profile identity, retention of
unrelated profiles, and session revocation. On the device, open WireGuard,
confirm the **AirVPN** tunnel, connect it, and verify a recent handshake,
expected public egress, DNS resolution, and the intended LAN access. Installation
policy success alone proves none of those VPN checks. Pending MDM commands
must be inspected before retrying a write; the operator never retries writes.

```sh
# Removal needs no VPN configuration file and only removes the AirVPN profile.
python3 -I scripts/fleet-airvpn-setup.py macos --remove --execute
python3 -I scripts/fleet-airvpn-setup.py ios --host-id <FLEET_HOST_ID> \
  --remove --execute
```

Removing the profile leaves the WireGuard app and other tunnels installed.
Rotate compromised client keys in AirVPN before provisioning a replacement;
profile removal does not revoke a key at the VPN provider. Retain private
source exports only as needed for recovery. Never publish command bodies or
database backups as acceptance evidence.

Local validation:

```sh
python3 -I scripts/ci/fleet-airvpn-setup-test.py
python3 -I scripts/ci/fleet-free-setup-test.py
```

Live VPN acceptance remains pending until the owner supplies device-specific
AirVPN configurations and completes the app/connection checks.
