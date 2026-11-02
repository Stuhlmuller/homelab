# Compass security update

Compass uses chart `0.11.0` and the Harbor mirror of upstream release `0.13.0`.
The stateless dashboard discovers Kubernetes services and opens their existing
launch URLs. Its [values](values.yaml) own the discovery configuration and image.

## Image evidence

The August [0.7.0 baseline](https://github.com/Stuhlmuller/homelab/issues/895)
reported 30 fixable HIGH findings. After the September update to 0.9.0,
the November 2, 2026 scan used Trivy 0.72.0 with the 01:14 UTC vulnerability
database. It scanned the linux/amd64 and linux/arm64 children of each source
index for fixable HIGH and CRITICAL findings with an empty ignore file.
Each platform yielded 17 Alpine packages and 86 Go packages from the Compass
binary. Counts below are unique vulnerability, package and fixed-version tuples
per platform.

| Compass | Upstream Docker index SHA-256 | HIGH | CRITICAL |
| --- | --- | ---: | ---: |
| 0.9.0 | `f8f99955b60d3b5d0f2747d5a911d1b03c8ca1aff8f6aa592d1cc7fa2d8020c0` | 7 | 0 |
| 0.13.0 | `f1f4a6bc529eb8a424b6125c39e839d108b06e975cf314181f8398bbc55fd498` | 0 | 0 |

The unfiltered 0.13.0 scan retained one medium and three unknown findings on
each architecture.

The 0.9.0 findings affected OpenSSL, `golang.org/x/net` and the Go standard
library. The [upstream release](https://github.com/adinhodovic/compass/releases/tag/0.13.0)
includes the fixes. Rendering chart `0.11.0` with these values changes the
image and version labels from chart `0.6.0`.

## Delivery and acceptance

1. Publish the reviewed image catalog from current `main` using the protected
   [Harbor mirror workflow](../../../../docs/harbor-image-mirroring.md) with
   `image_scope=all`. Verify the complete authenticated Harbor pull, exact
   index and both platform digests before merging the workload update. Require
   fresh destination vulnerability reports with usable Alpine and Go coverage
   and zero fixable HIGH or CRITICAL findings on each platform.
2. Verify `kubectl -n argocd get application compass` reports Synced and Healthy
   at the merged Git revision and chart `0.11.0`. Confirm the ready Deployment
   Pod uses the reviewed digest and serves the `compass` endpoint. Record its UID,
   restart count and the check time.
3. During the next 24 hours, use an authenticated operator session for the
   Octelium Compass service. Verify the dashboard renders the discovered list
   and a known launch link opens the intended service. Check the private
   Traefik route when verifying current launch hostnames. Retain timestamped
   functional checks and availability observations across the window. Require
   zero new restarts and image errors, and investigate any probe failures
   before closing #895. Keep session cookies and catalog data private.
4. To roll back, revert the workload chart and image pins and their chart
   inventory entries through a reviewed PR. Confirm chart `0.6.0` and the
   retained `0.9.0` digest reconcile, then repeat the authenticated checks.
