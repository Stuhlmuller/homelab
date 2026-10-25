# Istio ambient egress waypoint

This dormant Argo Application stages an exact `openrouter.ai:443` TLS
`ServiceEntry` for the `ai/litellm` service account. The `istio-egress`
namespace enrolls its ServiceEntry in a waypoint, and a service-attached
`ALLOW` policy rejects other mesh principals at that waypoint. The TLS session
stays end-to-end between LiteLLM and OpenRouter; the waypoint can enforce the
host and port but cannot inspect HTTPS paths.

The live cluster cannot apply this yet. Gateway API CRDs and `istio-waypoint`
GatewayClass are absent; the single CRD owner is the staged
`platform-envoy-gateway` Application. Istio CNI currently sets
`cni.ambient.dnsCapture: false`; ambient ServiceEntry routing to a waypoint
requires DNS capture. Enable and qualify it through the owned Istio release
path before syncing this Application. The active Istio 1.27.3 release is also
behind the repository's held upgrade ladder. Keep auto-sync disabled until
the prerequisites are deployed and an isolated traffic canary passes.

Activation checks: CRDs established, `istio-waypoint` class present, waypoint
Programmed and ready, LiteLLM request to OpenRouter succeeds through the
waypoint, another mesh principal gets denied, and direct IP or undeclared host
traffic is blocked by an enforcing network-layer policy. The last condition
cannot be supplied by Istio alone. Flannel does not enforce NetworkPolicy;
the staged kube-router canary must qualify before claiming hard default deny.
Do not enable `REGISTRY_ONLY` as a substitute. Talos image pulls, non-ambient
namespaces, and Deluge's WireGuard UDP path need separate policy.

Source: [Istio ambient egress gateway](https://istio.io/latest/docs/ambient/usage/egress-gateway/),
[DNS proxying](https://istio.io/latest/docs/ops/configuration/traffic-management/dns-proxy/),
and [security guidance](https://istio.io/latest/docs/ops/best-practices/security/).
