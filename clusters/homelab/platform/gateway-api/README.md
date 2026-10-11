# Gateway API prerequisite

Istio ambient waypoints need Gateway API resources. The live inspection on
2026-10-10 found no Gateway or GatewayClass CRDs. This platform Application
installs the five standard Gateway API v1.3.0 CRDs, matching the dependency
declared by Istio 1.27.3. The CRDs are vendored from upstream commit
`40be951cebe5cb3f0365fe6951403de4ff8b9f33`, so offline policy checks and Argo
rendering do not need a `raw.githubusercontent.com` fetch; experimental CRDs
are excluded.

The shared Terragrunt template registers `platform-gateway-api` in AppProject
`homelab`, with destination `kube-system` and source revision `main`. The CRDs
are cluster-scoped. Istio's registration depends on this unit; registration
ordering does not prove the CRDs are Established or its controller is ready.
This prerequisite deploys no Pod, Gateway, waypoint, route or DNS-capture change.

Validate without changing live state:

```sh
kubectl kustomize clusters/homelab/platform/gateway-api > /private/path/gateway-api.yaml
kubectl apply --server-side --dry-run=server -f /private/path/gateway-api.yaml
```

Deliver only through the protected Terragrunt saved-plan workflow after the
coordinated merge hold clears. Argo CD installs the rendered CRDs with server-side
apply. Verify the Application revision and Synced/Healthy state, then:

```sh
kubectl wait --for=condition=Established --timeout=60s \
  crd/gateways.gateway.networking.k8s.io \
  crd/gatewayclasses.gateway.networking.k8s.io
kubectl get gatewayclasses istio-waypoint -o yaml
```

Require Istio's waypoint GatewayClass to report Accepted before registering a
waypoint. If its controller does not observe the new CRDs, add a reviewed
declarative Istio rollout; do not restart the Deployment manually.

CRDs hold Gateway/Route objects in etcd; existing cluster backups cover those
objects. `Prune=false,Delete=false` protects them during Application rollback
or retirement. Leave installed CRDs in place while rolling back consumers.
Any schema downgrade or deletion needs a separate reviewed migration that
preserves stored versions and dependent resources.

The next egress canary can enable `ambient.istio.io/dns-capture: "true"` on one
workload while the global setting remains false. Istio 1.27.3's CNI explicitly
supports that override. Pilot's IP auto-allocation is enabled by default, but
ServiceEntry status, synthetic DNS answers and actual waypoint traffic still
need acceptance. Narrow domain policy must also test direct IP, alternate port,
IPv6, forged TLS SNI/shared-IP routing and gateway bypass before enforcement.

Sources: [Istio's pinned Gateway API dependency](https://github.com/istio/istio/blob/1.27.3/go.mod),
[per-pod capture override](https://github.com/istio/istio/blob/1.27.3/cni/pkg/nodeagent/net.go),
and [Gateway API v1.3.0](https://github.com/kubernetes-sigs/gateway-api/tree/40be951cebe5cb3f0365fe6951403de4ff8b9f33/config/crd/standard).
