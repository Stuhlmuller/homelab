# Platform DNS

This overlay manages only the CoreDNS `ConfigMap` in `kube-system`. CoreDNS is
installed by the cluster bootstrap path, but this repository owns the resolver
policy so in-cluster controllers do not inherit an unstable node-local upstream.

External lookups are forwarded to Cloudflare's standard resolvers: `1.1.1.1`
and `1.0.0.1`. These resolvers intentionally do not apply Cloudflare Family
category filtering. On 2026-07-19, the Family resolvers returned `0.0.0.0` and
`::` for a configured Prowlarr indexer while the standard resolvers returned
the authoritative public addresses. The sinkhole response surfaced as a
misleading HTTPS connection-refused error in Prowlarr.

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
```

The Prowlarr lookup should return public addresses rather than `0.0.0.0`.

Rollback by reverting this overlay and the `platform-dns` Argo CD Application
registration, then applying the affected Terragrunt stack. Do not manually patch
the live CoreDNS `ConfigMap`; keep the desired resolver policy in git.
