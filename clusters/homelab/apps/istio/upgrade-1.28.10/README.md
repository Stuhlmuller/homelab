# Istio 1.28.10 image overlays

These JSON files are Helm values (JSON is valid YAML). They are not referenced
by the active 1.27.3 Application. Add one overlay to each chart source's
`helm.valueFiles` only in its reviewed upgrade phase, after the matching
Harbor image and chart receipts pass.

Prefix each file below with
`$values/clusters/homelab/apps/istio/upgrade-1.28.10/`.

| Phase | Source | Overlay file |
| --- | --- | --- |
| 2–5 | `istiod` | `istiod-images.json` |
| 3 | `istio-cni` | `cni-images.json` |
| 4 | `ztunnel` | `ztunnel-images.json` |
| 5 | `istio-ingressgateway` | `gateway-images.json` |
| 6 | `octelium-api-ingressgateway` | `gateway-images.json` |
| 6 | `istiod` | Swap to `istiod-final-images.json` |

Keep each source's existing values file before the added overlay. The phase-2
istiod overlay pins the injector's default proxy to the reviewed 1.27.3
digest. Each gateway's own phase sets its new proxy digest through the Pod
annotation used by the 1.28.10 injection template. Phase 6 changes the
injector default after the first gateway is pinned and while the second is
upgraded. The protected phase gate must allow only these exact source changes
and verify digest-bearing live Pod images before writing its receipt.

`scripts/ci/istio-image-overlays-test.py` checks every value against the
reviewed Harbor image catalog. The protected chart publisher checks the
chart packages; a successful full image mirror and chart publication are
separate prerequisites. Do not apply a chart phase from these files alone.
