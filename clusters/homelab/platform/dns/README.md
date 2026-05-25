# Platform DNS

This overlay manages only the CoreDNS `ConfigMap` in `kube-system`. CoreDNS is
installed by the cluster bootstrap path, but this repository owns the resolver
policy so in-cluster controllers do not inherit an unstable node-local upstream.

External lookups are forwarded to the same Cloudflare family resolvers used in
the Talos onboarding examples: `1.1.1.3` and `1.0.0.3`. On 2026-05-25, CoreDNS
was observed forwarding through `169.254.116.108:53`, which timed out for AWS
SSM, GitHub, and Tailscale names. Those failures surfaced as External Secrets
errors for `cert-manager-cloudflare-api-token`, which can block future
cert-manager DNS-01 issuance and renewal.

Verify after rollout:

```sh
kubectl get application platform-dns -n argocd
kubectl get configmap coredns -n kube-system -o yaml
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
kubectl get externalsecret cert-manager-cloudflare-api-token -n cert-manager
kubectl get clusterissuer letsencrypt-cloudflare
kubectl get certificate stinkyboi-wildcard -n istio-system
```

Rollback by reverting this overlay and the `platform-dns` Argo CD Application
registration, then applying the affected Terragrunt stack. Do not manually patch
the live CoreDNS `ConfigMap`; keep the desired resolver policy in git.
