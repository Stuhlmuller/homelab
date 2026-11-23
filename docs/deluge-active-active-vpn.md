# Staged active-active AirVPN for Deluge

The [active-active profile](../clusters/homelab/apps/deluge/active-active/) stages two independent WireGuard
gateways. The existing Argo CD application still uses Gluetun. The active-active
profile uses a separate AirVPN device and IPv4 server location for each gateway
on `zimaboard-1` and `zimaboard-2`. Deluge remains a singleton on
`zimaboard-0`. The appliance, WAN connection, and AirVPN account remain shared
dependencies.

The Deluge pod installs its firewall before launching the application. The pod
can send encrypted WireGuard transport to either gateway and reply to cluster
Web and metrics requests. The gateways forward public payloads only inside
AirVPN. New flows use both healthy tunnels and retain their selected path in
connection tracking. The loopback DNS resolver uses HTTPS through healthy paths.
Losing a path interrupts flows pinned to it. The surviving path keeps its flows
and takes new ones. Losing both paths removes Deluge from the Web Service and
blocks public egress. Metrics remain available through the dedicated metrics
Service. AirVPN can forward the same port for multiple devices, although remote
peers may discover only one exit through a particular tracker.

## Stage and verify

1. Run the Deluge VPN image workflow. Use the signed, verified Harbor image
   reference from that run for the staged overlays. Run
   `bash builds/deluge-vpn/test-network.sh` against the built
   `homelab-deluge-vpn:build` image on a Linux Docker host with kernel WireGuard
   and nftables support. The fixture uses only simulated exits and runs with no
   external network.
2. Confirm the AirVPN account has room for the two new device sessions alongside
   the existing Deluge session. Export a WireGuard profile for each device with
   a numeric IPv4 endpoint in a different location. Generate two distinct
   transit keypairs for the client and two for the gateways. Populate the
   [declared SSM contracts](secrets-aws-ssm.md#deluge-vpn)
   through the `Deluge VPN Credentials` workflow after applying the SSM
   declarations. Supply the A and B JSON bundles as the protected
   `DELUGE_VPN_PATH_A_BUNDLE` and `DELUGE_VPN_PATH_B_BUNDLE` environment secrets.
   Each bundle contains `airvpn_profile`, `client_transit`, and
   `gateway_transit`. Dispatch once per path with the exact current main SHA.
   Keep profile files and keys out of git, build output, and diagnostic logs.
3. Check that the gateway Service addresses are free, the workers support
   WireGuard and nftables, and pod reverse-path filtering is disabled. The
   gateways require IPv4 forwarding. Stage the gateways and the synthetic
   client through Argo CD using the pinned image. Configure a temporary AirVPN
   forwarded port for both devices and map it to local `5983`. Verify each
   exit, inbound TCP and UDP on the temporary port, surviving-path failover, and
   automatic rejoin after a gateway pod is replaced. Remove the synthetic
   client before starting Deluge with the same transit keys.
4. Validate a Deluge build with libtorrent 1.2.1 or newer against a restored
   copy of the catalog before replacing the current image. The current
   libtorrent 1.1.5 build uses a shared UDP listener. The active profile
   checks for separate listeners on both transit IPv4 addresses so incoming
   UDP can reply through the same exit. LinuxServer Deluge `2.2.0-ls387`
   with libtorrent `2.0.13.0` passed an isolated Web/RPC, port setup,
   listener, and graceful shutdown check on a clean catalog. The existing
   catalog still needs a restore rehearsal. Publish the tested application
   image through the Harbor mirror workflow and pin it for the app,
   port-config, and daemon-metrics containers. Confirm the latest config
   backup succeeded. Set production AirVPN
   port `5983` to All Devices and cut over through the Helm values overlay.
   Keep the old Gluetun profile and base values available for rollback. Verify
   Web access, direct daemon RPC, Sonarr/Radarr download-client tests, and
   inbound TCP/UDP through both exit IPs. Observe seven days of path and pod
   readiness metrics against the pre-cutover baseline.
5. Revert the Argo CD values change if egress, failover, port-forwarding, or
   download-client checks fail. The existing Recreate strategy prevents two
   Deluge daemons from opening the catalog. Rotate one gateway profile at a
   time after cutover, bumping that ExternalSecret and its pod-template
   annotation together. Verify both tunnels before and after each rotation.

The network controller probes each tunnel every three seconds. Both per-path
health metrics should settle at `1` and both path byte counters should rise
under sustained traffic. Wait for at least one path to recover before expecting
the Web Service to become ready after a simultaneous failure.
