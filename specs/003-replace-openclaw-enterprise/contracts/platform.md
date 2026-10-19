# Platform Maintenance and Network Qualification Contract

Implementation contract for the new maintenance lane; none of its new commands
exist yet. Read-only inspection remains available through existing clients.

## Committed Inputs

`scripts/config/platform-maintenance.json` declares schema version, a policy requiring
the exact current `main` SHA supplied by the protected workflow at execution,
ordered Talos/Istio/Kubernetes target versions and immutable image references,
node order/expected identities, expected starting versions, canary label/taint,
readiness deadlines, and references to safe configuration patches. It contains no
credentials, shell fragments, arbitrary command arguments, or environment lookups.

Targets follow [research.md](../research.md#r2--upgrade-supported-platform-branches-in-separate-stages).
No downgrade, version skip, node substitution or image substitution is inferred.
The maintenance workflow accepts only an exact current `main` SHA and a fixed
stage identifier from committed inputs. Credentials come from its protected
credential path and never become desired-state inputs.

## Planned Helper Interface

```text
platform-maintenance.py inspect --config PATH --output PRIVATE_RECEIPT
platform-maintenance.py validate --config PATH
platform-maintenance.py execute --config PATH --stage STAGE --expected-sha SHA
```

- `inspect`: read-only versions, node/image identity, health and capacity metadata.
- `validate --config`: pinned declaration schema, supported hop/order, and immutable
  references only. Supplying both private role-specific Talos configurations also
  renders and strictly validates every target patch offline. Neither form proves
  recovery or live readiness or invokes upgrade operations.
- `execute`: protected workflow only; verifies current SHA, maintenance stage,
  live starting state and private recovery receipt before each mutation. It uses
  the supported Talos upgrade path and records per-node completion.
- Interrupted runs compare observed state against receipts. Unknown or partially
  converged state stops execution; never repeat a reboot solely because a receipt
  was not written. No `--force`, arbitrary node flags, or unchecked retry option.
- All failures return nonzero; public output is a fixed phase/result label.
  Full failure diagnostics remain private and preserved for operator review.

The helper must not mistake `upgrade-k8s --dry-run` for a read-only probe.
Validate configs with `talosctl validate --mode metal --strict`; use authenticated
Talos access. Confirm direct recovery and fresh etcd backups before the sole
control-plane change. No automatic Kubernetes rollback.
The protected runner needs an explicitly reviewed Octelium TCP grant to the
Talos API: the existing service policy admits only the owner human session.
Use the hostname covered by the Talos server certificate with a fixed local
publish port, keep Talos mTLS, and prove a separate direct-LAN recovery path.
Do not use `--insecure` to work around transport or certificate failures.
Talos appends the target `:v<version>` tag to `upgrade-k8s` image-base flags;
verify every resulting tag against its digest-pinned Harbor catalog entry and
private publication receipt before execution. Do not pass `tag@sha256` values
directly to those flags.

## Enforcement Configuration

The repository owns a minimal kube-router DaemonSet at the verified v2.11.1
Harbor digest with these explicit flags:

```text
--run-router=false
--run-service-proxy=false
--run-loadbalancer=false
--run-firewall=true
--enable-cni=false
--netpol-default-deny=true
--use-nftables-for-netpol=false
--enable-ipv4=true
--enable-ipv6=false
```

Render tests reject CNI installation init containers, CNI ConfigMaps/environment
settings, CNI/`/opt` mounts, NRI sockets, host kubeconfigs, service-proxy/router
activation, or undocumented host privileges. The firewall is a reviewed privileged
platform exception; do not label it a restricted application workload.

A declared canary taint and matching toleration isolate qualification workloads;
a node selector alone is insufficient. Include the unavoidable infrastructure
DaemonSets in the canary review. Before broadening the selector, review every
policy affecting Pods on the next node, including rendered/controller-generated
policies and ingress. Use exact snapshot/render/review hashes in receipts.

## Required Traffic Matrix

| Scenario | Expected result |
| --- | --- |
| Bootstrap/API/worker/agent to declared TCP and UDP DNS | Allowed |
| API/worker to exact Kubernetes API and TLS PostgreSQL | Allowed only for required service identities |
| Owner through Octelium to OCE/native agent | Allowed with authentication and exact-agent authorization |
| OCE API through private Envoy to its agent | Allowed; wrong identity/agent denied |
| Agent to configured public model HTTPS | Allowed by stock OCE public TCP/443 policy |
| Agent to Kubernetes API, database, NAS, metadata or unrelated LAN/tenant | Denied unless an exact required upstream grant is documented |
| Existing mesh HBONE/probes, webhooks, NFS, ESO/Argo, Octelium and image pulls | Existing authorized paths preserved |
| Direct unauthorized access to API/native gateway/private Envoy | Denied |
| Alternate ports, private direct IP bypass, wrong/missing labels, stale extra allow policies | Denied or rejected by audit |
| Tenant IPv6 path in this IPv4-only installation | Unavailable; no dual-stack enforcement claim |

Repeat the negative probes before first application traffic, during enforcer
SIGTERM/crash/restart, API loss, policy changes, Pod reschedule/IP reuse and node
reboot. Include cold bootstrap with DNS and infrastructure Pods starting together.
An existing connection may survive a policy change through conntrack; quiesce
sessions when immediate revocation is required, and test that behavior explicitly.

Host-network, privileged, VPN and Multus secondary interfaces need separate
control-path evidence. Stock OCE public TCP/443 permits more than one model
hostname; this plan does not claim arbitrary-internet or FQDN filtering.

## Failure and Recovery

No capacity or isolation result may be waived by a healthy DaemonSet count.
On failure, stop expansion and quiesce affected Enterprise tenants. Policy fixes
and rollback follow GitOps. DaemonSet removal alone leaves firewall chains;
implement a tested cleanup of only owned objects, never blindly use kube-router's
all-controller cleanup. Preserve kube-proxy, Flannel and human/CI recovery.

Retain the previous compatible Talos boot image; after Kubernetes upgrade,
re-evaluate its compatibility before any fallback. Unsupported rollback requires
separately declared disaster recovery, not an automatic downgrade command.
