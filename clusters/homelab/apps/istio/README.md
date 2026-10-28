# Held Istio 1.28.10 hop

The live-owned `IaC/homelab/us-west-2/apps/istio/stack.hcl` stays at Istio
1.27.3 with its existing auto-sync and self-heal behavior. This directory's
[`upgrade-1.28.10.json`](upgrade-1.28.10.json) records a **disabled** candidate
for the first adjacent hop. It is not included in `kustomization.yaml` or the
Argo Application. Even if this preparation merges, it changes no Istio
runtime object or Application sync policy.

The target's four digest-pinned images already live in the reviewed
[`platform-maintenance.json`](../../../../scripts/config/platform-maintenance.json)
and [`harbor-images.json`](../../../../scripts/config/harbor-images.json).
Those pins are source inventory, not successful Harbor publication. The
candidate records the SHA-256 of each official 1.28.10 chart archive and the
intended base/CRDs, istiod, CNI, ztunnel, two-gateway sequence. Offline Helm
renders with the existing release names, values, and parameters found every
resource labeled with its release name and no resource-identity changes except
that the 1.28.10 istiod chart omits the old `istiod` PodDisruptionBudget.
The active 1.27.3 sources use Istio's replacement chart repository at
`https://blob.istio.io/istio-release/charts`; the downloaded archives match
these pins. A future active 1.28 phase uses private Harbor OCI charts. The
protected `harbor-helm-charts.yml` workflow publishes five chart archives,
pulls each as the robot reader, and records its OCI manifest digest. That
phase must bind the protected run and all five digests; Argo sources use
`oci://harbor.stinkyboi.com/mirror/helm/<chart>` with
`targetRevision: sha256:<manifest>`. The AppProject allows only those paths,
and an ExternalSecret supplies Argo's OCI reader credential. All six active
chart sources remain on 1.27.3 until a reviewed phase PR. A failed chart
fetch blocks the hop; restore the prior source through a reviewed plan.

The five unreferenced image overlays in [`upgrade-1.28.10/`](upgrade-1.28.10/)
pin pilot, CNI, ztunnel, and injected gateway images by digest. Istiod phases
2–5 hold the old proxy digest as the injector default, even if an old gateway
restarts. Each gateway phase adds the new proxy digest annotation to its own
template. Phase 6 updates the final gateway and Istiod injector default in one
saved Application patch. The gateway chart renders `image: auto`; its Pod must
contain the injected digest reference and matching image ID.

The [Istio 1.28 release](https://istio.io/latest/news/releases/1.28.x/announcing-1.28/)
supports Kubernetes 1.34. Its [upgrade notes](https://istio.io/latest/news/releases/1.28.x/announcing-1.28/upgrade-notes/)
warn that old ztunnels can NACK new `ServiceEntry` resolution `NONE` xDS until
ztunnel is upgraded, `BackendTLSPolicy` v1alpha3 handling is removed, and old
Pilot metric-rotation flags are gone. No Gateway API CRDs are installed by
this candidate; the separately owned Envoy Gateway path handles those.
The [1.27.9 patch](https://istio.io/latest/news/releases/1.27.x/announcing-1.27.9/)
fixes an upgrade with installed Gateway API CRDs; none are installed here, so
the reviewed first hop remains directly from 1.27.3. Istio 1.28 is an
intermediate hop, not the final target.

## Release gate

Do not change the active chart revisions until T024's Talos per-node receipts,
measured node capacity, verified legacy recovery, direct API access, a fresh
off-node etcd backup, and complete authenticated Harbor pull receipts exist.
`platform-maintenance.json` still has `activationEnabled: false` and no
admitted canary node. The protected Talos/Kubernetes workflow does not perform
Istio upgrades. `upgrade-1.28.10.json` has `phase: 0`; a phase means that
exactly that many leading charts use reviewed OCI digests. The offline source
check verifies the exact rendered Argo Application, including per-phase
valueFiles and the phase 6 injector change. In active phases it hashes every
referenced values, overlay, Kustomize, and values-ref file. Git-only changes
to those files can auto-sync without a Terragrunt plan. Refresh a changed
phase-0 baseline pin through review before activation.
The protected source path is ready but remains dormant at phase 0. A future
phase PR advances exactly one chart source in
`IaC/homelab/us-west-2/apps/istio/stack.hcl`, sets the matching phase and
`priorRunId`/`harborRunId`/`chartRunId`, five OCI manifest digests, and pinned
Git-backed values. The PR check requires the exact prior phase's successful
protected run, full image mirror, and chart publication jobs with unchanged
publication sources. Phase 1 uses the final Talos 1.14.4 run as
its predecessor and atomically suspends Argo pruning with the base chart
source update. Later phases keep pruning disabled and the existing `istiod`
PodDisruptionBudget. Phase 6 is the sole two-source transition: final gateway
plus Istiod injector default. A full six-chart source change fails the gate.

After a phase PR merges, dispatch `Terragrunt Apply` with the exact current
main SHA, `argocd_app=istio`, and `istio_phase=N`. The protected preflight
rechecks current-main receipts, the private predecessor record, healthy
Talos/Kubernetes nodes, the live held Application, and a saved plan containing
one exact phase transition. It checks the chart publication artifact,
reconciled Argo repo-creds, and fresh private TLS reads of every OCI manifest
and archive. It saves that artifact receipt inside a private write-once
`started` marker before apply. A terminal no-apply run can be cancelled by a
protected receipt only after the held Application, controller Pods, CRDs,
admission, and PDB match the original snapshot. A fresh exact-main run then
writes a new attempt marker. Changed live state needs a reviewed recovery
change.

Dispatch `Platform Maintenance` with `stage=istio-1.28.10-phase-N` and its
exact current main SHA after Argo sync. It verifies the live Application,
CRDs, live validating and mutating admission, controller readiness and Pod
digests, xDS ACKs from every expected proxy, a
TLS ingress-to-ambient Grafana request, and the functional DNS/NFS, private
access, and webhook probe. Only then does it publish a write-once private
`verified` marker. The next phase PR and apply each require that proof. A later
main merge can use the original protected apply and saved chart receipt while
the verifier reruns all live checks at current main; an interrupted verified
write can be adopted by a new successful protected run. The chart artifact's
30-day GitHub retention does not expire the saved private copy.
Phase 6 also publishes the six-component stage summary used by the later
Kubernetes maintenance gate. Validate the source lane with
`python3 -I scripts/ci/istio-upgrade-gate-test.py`,
`python3 -I scripts/ci/istio-prior-run-check-test.py`,
`python3 -I scripts/ci/istio-upgrade-test.py`, and
`python3 -I scripts/ci/terragrunt-apply-test.py` from the repository root.

The [upstream ambient upgrade sequence](https://istio.io/latest/docs/ambient/upgrade/helm/)
requires base CRDs first, then istiod, CNI, ztunnel, and manually deployed
gateways. The future lane must stop after each component until CRDs are
Established, webhook Services have ready endpoints, each Deployment or
DaemonSet is Ready on the expected nodes, and original API, DNS, HBONE,
storage, Kiali, Octelium/private-route and admission traffic still works.
CNI has no canary upgrade; ztunnel in-place replacement can interrupt
long-lived node connections. Stop on persistent xDS NACK, readiness errors,
admission failures, or unexpected traffic changes.

The 1.28.10 istiod chart omits the old `istiod` PodDisruptionBudget. Pruning
stays disabled through all six phases so Argo retains it. Restore pruning
and review that deletion only after all stages pass and an exact live Argo
diff shows no other unexpected removal. Rollback requires a reviewed source
change in reverse data-plane order; do not automatically downgrade CRDs
without checking stored versions and schema compatibility. Record failure and
recovery proof before the 1.29.9 hop.
