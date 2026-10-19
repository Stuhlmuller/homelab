# Shared Envoy Gateway source

The CRD chart (`gateway-crds-helm` v1.9.2,
`sha256:940b88fe361cb22fb651e3075f649e9be885f35b1c8a990658c1a2acc2d2a678`)
owns Gateway API 1.6.1 experimental and Envoy Gateway CRDs. Its local render
contains 21 CRDs and the Gateway API safe-upgrade admission policy and binding.
It retains TCPRoute/UDPRoute `v1alpha2` and ReferenceGrant `v1beta1` for Istio.

The controller chart (`gateway-helm` v1.9.2,
`sha256:be034275b55deeddd6b7bc1f4da6eeb02b8efc418a4a29e2b1977851b24b1e63`)
disables its CRD dependency and uses digest-pinned Harbor images. The
GatewayClass declares no listener. The Application registration is staged with
automatic sync disabled, and no runtime route exists yet. Argo applies the CRDs
before the controller Deployment (sync wave 1) and class (wave 2) through the
reviewed [platform rollout](../../../../docs/openclaw-enterprise-rollout.md).
The Enterprise EnvoyProxy later needs its own exact image override because its
parametersRef replaces the chart's default proxy image.

Chart behavior and image precedence are documented by
[Envoy Gateway's Helm installation guide](https://gateway.envoyproxy.io/docs/install/install-helm/)
and [v1.9.2 release notes](https://gateway.envoyproxy.io/news/releases/notes/v1.9.2/).
