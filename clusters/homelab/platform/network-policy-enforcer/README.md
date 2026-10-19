# NetworkPolicy enforcer canary

Flannel supplies transport but does not enforce the cluster's `NetworkPolicy`
objects. This Kubernetes SIG Network userspace enforcer adds the L3/L4 boundary
needed to keep unrelated Pods off Traefik's private listener. The pinned image
is copied to Harbor from the upstream digest in
[`scripts/config/harbor-images.json`](../../../../scripts/config/harbor-images.json).

The `platform-network-policy-enforcer` Argo CD Application has automated sync
disabled. Its DaemonSet selects only a Linux node labeled
`homelab.stinkyboi.com/network-policy-canary=true` and tolerates only the
matching `NoSchedule` taint. The label and taint must belong to a measured,
dedicated worker; [`platform-maintenance.json`](../../../../scripts/config/platform-maintenance.json)
does not yet select one. Registering this Application alone does not install
the enforcer or make existing policies effective.

Before the first sync, require a successful complete authenticated Harbor pull,
review every effective `NetworkPolicy`, establish the dedicated worker and its
recovery receipts, and enable Talos NRI through the guarded canary helper.
Verify active and persistent CRI configuration, the NRI socket, and runtime
registration. Then render and diff the exact Kustomize source, promote only this
Application through reviewed GitOps source, and require one Ready enforcer Pod
on the selected worker. Its `--fail-open=false` and `--strict-mode=true` settings must match
the rendered and live Pod spec. Verify permitted and denied IPv4/IPv6 traffic,
same-node and cross-node Pod IP and Service access, startup isolation, and
existing application paths before selecting another worker.

Traefik currently runs on a different worker, so a successful canary does not
close the private 8443 ingress finding. Expand enforcement to Traefik's worker
only after policy audit and canary acceptance, then require a real Tailscale
request to succeed and unrelated in-cluster probes to fail. For rollback,
withdraw the enforcer through the reviewed GitOps source and verify its Pods
are absent before using the NRI rollback helper.
