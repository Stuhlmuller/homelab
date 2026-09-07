# Platform DNS

This overlay adopts the six bootstrap CoreDNS resources: ServiceAccount,
ClusterRole, ClusterRoleBinding, ConfigMap, Deployment, and Service. It preserves
the running CoreDNS `v1.12.4` image content, two replicas, scheduling, resource
settings, and DNS Service address `10.96.0.10`.
The existing Corefile remains unchanged. Argo CD pruning is disabled, and each
resource also retains `Prune=false,Delete=false` protection.

The manifests follow the
[pinned Talos templates](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/k8s/internal/k8stemplates/coredns.go),
with the current homelab image, Service address, and Kubernetes defaults made
explicit. The immutable image index digest matches both existing Pods' reported
image IDs; its unique `linux/amd64` child manifest was hash-verified against the
registry.
Adding the digest changes the Pod template and intentionally causes a rolling
replacement. `maxUnavailable: 0` retains two available replicas while
`maxSurge: 25%` permits one additional Pod, requiring another `100m` CPU and
`70Mi` memory request. All other Pod-template fields remain unchanged.

**Do not disable Talos CoreDNS during initial bootstrap.** First complete the
[ownership handoff](../../../../docs/knowledge-base/operations/coredns-gitops-ownership.md).
The separate Talos patch is not wired into bootstrap or applied by this overlay.

Talos still generates a default CoreDNS ConfigMap during Kubernetes upgrades.
The September 2026 upgrade plan would overwrite this policy, including the
internal Octelium route. Resolve that ownership collision before upgrading;
see the [maintenance findings](../../../../docs/knowledge-base/operations/kubernetes-patch-maintenance-2026-09.md).
Do not depend on a later Argo CD reconciliation to repair a temporary DNS
regression during control-plane maintenance.

External lookups are forwarded to Cloudflare's standard resolvers: `1.1.1.1`
and `1.0.0.1`. These resolvers intentionally do not apply Cloudflare Family
category filtering. On 2026-07-19, the Family resolvers returned `0.0.0.0` and
`::` for a configured Prowlarr indexer while the standard resolvers returned
the authoritative public addresses. The sinkhole response surfaced as a
misleading HTTPS connection-refused error in Prowlarr.

Inside Kubernetes, `octelium-api.stinkyboi.com` resolves to the dedicated
`octelium-api-ingressgateway` Service. This split-horizon route keeps Cordium
and other in-cluster Octelium clients independent of the router's WAN mapping;
external clients continue to use public DNS.

Explicit public resolvers remain necessary because CoreDNS was observed on
2026-05-25 forwarding through `169.254.116.108:53`, which timed out for AWS
SSM, GitHub, and Tailscale names. Those failures surfaced as External Secrets
errors for `cert-manager-cloudflare-api-token`, which can block future
cert-manager DNS-01 issuance and renewal. If category filtering is needed in
the future, add a reviewed policy that does not silently sinkhole required
workload destinations.

Verify after rollout:

```sh
kubectl get application platform-dns -n argocd
kubectl get configmap coredns -n kube-system -o yaml
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
kubectl get externalsecret cert-manager-cloudflare-api-token -n cert-manager
kubectl get clusterissuer letsencrypt-cloudflare
kubectl get certificate stinkyboi-wildcard -n istio-system
kubectl -n media exec deployment/prowlarr -c app -- getent ahostsv4 iptorrents.com
kubectl -n media exec deployment/prowlarr -c app -- getent ahostsv4 octelium-api.stinkyboi.com
```

The Prowlarr lookup should return public addresses rather than `0.0.0.0`. The
Octelium API lookup should return the gateway Service's ClusterIP.

After the handoff, keep all six resources declared and retain the Application.
Roll back resolver-policy changes by reverting the Corefile through GitOps.
Returning ownership to Talos requires a separately reviewed handoff: its default
Corefile omits the custom resolver and Octelium routing policy.
