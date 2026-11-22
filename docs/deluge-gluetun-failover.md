# Deluge Gluetun failover

Deluge uses one AirVPN profile and one torrent catalog. Two Gluetun pods run
on separate workers. A Kubernetes Lease elects one pod to start Gluetun and
connect to AirVPN. The standby uses the same existing `deluge-vpn` Secret and
starts its tunnel when it takes over. The two pods share the provider and
profile, so an AirVPN-wide outage or profile failure affects both. Deluge
remains pinned to its existing storage node.

A selectorless Service gives Deluge a stable UDP address for its internal
WireGuard link. The lease holder publishes its pod address after Gluetun
passes its health check. It withdraws the endpoint and stops Gluetun on
demotion. A short local nftables lease expires even when the control process
is paused or loses access to Kubernetes. The old pod stops using the AirVPN
underlay before another pod can take over. Existing public connections may
need to reconnect after a failover.

The Gluetun pod firewall accepts client forwarding only between WireGuard
transit and the AirVPN interface. It allows the AirVPN endpoint transport
on the cluster interface only while the local lease is valid. Deluge's
firewall starts before the daemon and permits public traffic only through its
encrypted transit link. Deluge DNS uses that link and the Web Service remains
unready without a working tunnel. The existing forwarded port remains
`5983`.

The runtime derives separate internal transit keys locally when it mounts
the existing profile. There are no new external VPN keys, AirVPN account
changes, or secret uploads. The profile is mounted only by the networking
containers.

## Rollout

1. Run the isolated network tests with kernel WireGuard and nftables, along
   with the lease, firewall, and Kubernetes render checks. Publish the
   helper image through the protected `Deluge Gluetun Image` workflow and
   pin the verified Harbor digest.
2. Stage the exact Lease and EndpointSlice using the declared Terraform unit.
   Argo CD owns the gateway pods, Service, and scoped role. Verify that the
   two worker nodes are eligible and the latest Deluge backup succeeded.
3. Stop the existing Deluge deployment through GitOps and verify its old
   Gluetun pod is gone before starting the new pair. The original pod and
   the new leader share one AirVPN identity. Apply the pinned gateway
   overlay, confirm one healthy endpoint, and restore the singleton with
   its transit guard overlay.
4. Verify Web and authenticated daemon RPC, Sonarr and Radarr connectivity,
   and inbound TCP and UDP `5983`. Observe gateway takeover in a controlled
   failover test. Confirm Deluge remains on the same pod and sends no
   direct IPv4, IPv6, or DNS traffic while neither gateway is healthy.
5. If rollback is needed, stop the new gateway pods and verify that their
   lease is no longer active before restoring the original Gluetun sidecar.
   Retain the existing Secret, application image, and catalog throughout
   the rollout.
