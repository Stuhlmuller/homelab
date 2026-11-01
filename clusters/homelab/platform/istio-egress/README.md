# Istio ambient egress waypoint

This dormant Argo Application stages an exact `openrouter.ai:443` TLS
`ServiceEntry` for the `ai/litellm` service account. The `istio-egress`
namespace enrolls its ServiceEntry in a waypoint, and a service-attached
`ALLOW` policy rejects other mesh principals at that waypoint. The TLS session
stays end-to-end between LiteLLM and OpenRouter; the waypoint can enforce the
host and port but cannot inspect HTTPS paths.

The live cluster cannot apply this yet. Gateway API CRDs and `istio-waypoint`
GatewayClass are absent; the single CRD owner is the staged
`platform-gateway-api-crds` Application. It can be qualified before the
Envoy Gateway controller. Istio CNI sets
`cni.ambient.dnsCapture: false` globally. LiteLLM opts in through its pod
annotation, supported since Istio 1.25; verify the replacement Pod has DNS
capture and still reaches its existing destinations before enabling this
Application. The active Istio 1.27.3 release is also
behind the repository's held upgrade ladder. Keep auto-sync disabled until
the CRDs and LiteLLM DNS capture are verified. Then enable it through a
separate reviewed GitOps change and qualify the route before adding callers.

Istio route checks after sync: waypoint Programmed and ready, LiteLLM request
to OpenRouter succeeds through it, and another mesh principal gets denied.
These checks do not prove a hard outbound allowlist: direct IP or undeclared
host traffic still needs an enforcing network-layer rule. Flannel does not
enforce NetworkPolicy; the staged kube-router canary remains held without an
isolated worker. Router enforcement, if later added by the owner, needs its
own evidence. The live Flannel DaemonSet uses `--ip-masq`, so off-cluster Pod
traffic normally reaches the router under the node's address; a router rule
matching only that address cannot distinguish the waypoint from other Pods on
the same node. No router change is part of this Application.
Do not enable `REGISTRY_ONLY` as a substitute. Talos image pulls, non-ambient
namespaces, and Deluge's WireGuard UDP path need separate policy.

Source: [Istio ambient egress gateway](https://istio.io/latest/docs/ambient/usage/egress-gateway/),
[DNS proxying](https://istio.io/latest/docs/ops/configuration/traffic-management/dns-proxy/),
and [security guidance](https://istio.io/latest/docs/ops/best-practices/security/).
