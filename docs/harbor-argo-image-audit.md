# Argo image cutover audit ledger

Read-only baseline: 2026-10-25 06:13 UTC, repository `main` at
`e10199f25a4a7bbf93bd886afe87784ae20fdf6b`. Scope is Pods in the 25
destination namespaces of the 47 Argo CD Applications, excluding Argo CD's
own control plane. Each regular, init and ephemeral container image is one
reference. `Succeeded` and `Failed` Pods are retained below as historical;
they do not count toward the current-workload acceptance target.

| Namespace | Current refs | Current non-Harbor | Historical refs | Historical non-Harbor |
| --- | ---: | ---: | ---: | ---: |
| affine | 0 | 0 | 2 | 2 |
| ai | 11 | 11 | 5 | 5 |
| automation | 7 | 6 | 5 | 1 |
| cert-manager | 3 | 3 | 0 | 0 |
| cordium-storage | 1 | 1 | 1 | 1 |
| crossplane-system | 0 | 0 | 4 | 4 |
| external-secrets | 3 | 3 | 3 | 3 |
| fleet | 4 | 4 | 2 | 2 |
| harbor | 12 | 12 | 3 | 3 |
| istio-system | 12 | 12 | 3 | 3 |
| kube-system | 27 | 27 | 0 | 0 |
| langfuse | 6 | 6 | 0 | 0 |
| mastodon | 5 | 5 | 5 | 5 |
| media | 24 | 24 | 18 | 18 |
| monitoring | 14 | 14 | 4 | 4 |
| nix-builder | 1 | 1 | 0 | 0 |
| nofx | 2 | 0 | 2 | 2 |
| octelium | 113 | 113 | 39 | 39 |
| octelium-client | 2 | 2 | 1 | 1 |
| octelium-public | 2 | 2 | 0 | 0 |
| octelium-storage | 4 | 4 | 3 | 3 |
| storage | 1 | 1 | 1 | 1 |
| tailscale | 9 | 9 | 1 | 1 |
| traefik | 1 | 1 | 0 | 0 |
| **Total** | **266** | **261** | **102** | **98** |

The baseline contains 198 current Pods and 93 historical Pods. Application
status was 42 Synced/Healthy, four Synced/Degraded, and one OutOfSync/Healthy.
Record post-stage current counts here after each protected merge and Argo
reconciliation. Keep the historical column even after current references reach
zero; Kubernetes may later garbage-collect those completed Pods.
