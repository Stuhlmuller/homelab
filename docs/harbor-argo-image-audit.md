# Argo image cutover audit ledger

Read-only baseline: 2026-10-25 11:17 UTC, repository `main` at
`1e46ec59f422e315509b9af4298d864a8559128c`. Scope is Pods in the 25
destination namespaces of the 47 Argo CD Applications, excluding Argo CD's
own control plane and Talos-managed static/system Pods. Each regular, init and ephemeral container image is one
reference. `Succeeded` and `Failed` Pods are retained below as historical;
they do not count toward the current-workload acceptance target.

| Namespace | Current refs | Current non-Harbor | Historical refs | Historical non-Harbor |
| --- | ---: | ---: | ---: | ---: |
| affine | 0 | 0 | 2 | 2 |
| ai | 11 | 11 | 5 | 5 |
| automation | 7 | 6 | 6 | 1 |
| cert-manager | 3 | 3 | 0 | 0 |
| cordium-storage | 1 | 1 | 1 | 1 |
| crossplane-system | 0 | 0 | 4 | 4 |
| external-secrets | 3 | 3 | 3 | 3 |
| fleet | 4 | 4 | 1 | 1 |
| harbor | 12 | 12 | 3 | 3 |
| istio-system | 12 | 12 | 3 | 3 |
| kube-system | 12 | 12 | 0 | 0 |
| langfuse | 6 | 6 | 0 | 0 |
| mastodon | 8 | 8 | 6 | 6 |
| media | 26 | 26 | 18 | 18 |
| monitoring | 14 | 14 | 4 | 4 |
| nix-builder | 1 | 1 | 0 | 0 |
| nofx | 2 | 0 | 2 | 2 |
| octelium | 113 | 113 | 39 | 39 |
| octelium-client | 2 | 2 | 1 | 1 |
| octelium-public | 2 | 2 | 0 | 0 |
| octelium-storage | 4 | 4 | 3 | 3 |
| storage | 1 | 1 | 1 | 1 |
| tailnet-dns | 2 | 0 | 0 | 0 |
| tailscale | 9 | 9 | 1 | 1 |
| traefik | 1 | 1 | 0 | 0 |
| **Total** | **256** | **251** | **103** | **98** |

The baseline contains 192 current Pods and 94 historical Pods. Eleven current
Talos-managed kube-system Pods (15 image references) are outside this cutover.
Application
status was 44 Synced/Healthy, two Synced/Degraded (Bazarr and Deluge), and one
Synced/Progressing (Octelium Enterprise). The read-only controller inventory
includes 264 meaningful image references in current
Deployment, StatefulSet, DaemonSet, CronJob and unfinished Job templates,
including scaled-down workloads. The two Istio `auto` injector placeholders are
excluded. All 261 upstream references map to the reviewed catalog after
normalizing registry shorthand and tag/digest aliases.
Record post-stage current counts here after each protected merge and Argo
reconciliation. Keep the historical column even after current references reach
zero; Kubernetes may later garbage-collect those completed Pods.
