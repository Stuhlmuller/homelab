# CoreDNS GitOps Ownership

`platform-dns` declares all six CoreDNS resources while preserving the existing
DNS behavior and pinning the running image content. This prepares a handoff from Talos bootstrap;
the declaration alone does not complete it. Source and DNS checks are in the
[platform DNS runbook](../../../clusters/homelab/platform/dns/README.md).

## Why The Handoff Is Required

Talos `v1.11.3 upgrade-k8s` reconciles every bootstrap manifest after upgrading
Kubernetes. Its built-in CoreDNS ConfigMap differs from the repository's
Corefile: it removes the internal Octelium rewrite and replaces the explicit
Cloudflare resolvers with `/etc/resolv.conf`. Waiting for Argo self-healing would
permit a DNS interruption. The upgrade must wait until this ownership conflict
is removed.

An inline ConfigMap cannot override the built-in manifest before reconciliation.
Talos gives [inline manifests priority `99`](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/k8s/control_plane.go#L406-L410),
while the default CoreDNS resources use
[`11-core-dns` and `11-core-dns-svc`](https://github.com/siderolabs/talos/blob/v1.11.3/internal/app/machined/pkg/controllers/k8s/manifest.go#L191-L209).
The upgrade processes both objects rather than merging their desired content.

## Ordered Takeover

1. Keep Talos CoreDNS enabled. After rollout approval, merge and sync the
   six-resource overlay through the existing `platform-dns` Application.
   The image digest intentionally replaces the Pods while preserving the same
   image content. `maxUnavailable: 0` keeps two available replicas while one
   replacement starts; `maxSurge: 25%` permits one additional Pod. Before sync,
   verify a Ready, schedulable node matching the Pod constraints has at least
   `100m` CPU, `70Mi` memory, and one Pod slot beyond existing requests; also check
   current node pressure. The audit found this request headroom on all four nodes,
   but it must be rechecked at rollout. DNS Service addressing, Corefile, and all
   other Pod-template fields must remain unchanged.
2. Require the Application to be `Healthy` and `Synced` at the reviewed commit.
   Check that all six actual resources carry their exact Argo tracking IDs:

   ```sh
   kubectl -n argocd get application platform-dns -o json |
     jq -e '.status.health.status == "Healthy" and .status.sync.status == "Synced"'
   kubectl -n kube-system get \
     serviceaccount/coredns clusterrole/system:coredns \
     clusterrolebinding/system:coredns configmap/coredns \
     deployment/coredns service/kube-dns -o json |
     jq -e '
       .items | length == 6 and all(.[];
         (.apiVersion | split("/") | if length == 1 then "" else .[0] end) as $group |
         .metadata.annotations["argocd.argoproj.io/tracking-id"] ==
         ("platform-dns:" + $group + "/" + .kind + ":" +
          (.metadata.namespace // "") + "/" + .metadata.name))'
   ```

   Also inspect the Application's recorded revision and resource inventory;
   health alone does not prove adoption. Watch the rollout and require at least
   two available replicas throughout. Finish with two updated, Ready replicas
   using the reviewed image digest, with no crash-looping or failed probes;
   Pod UIDs change as expected. The
   [runbook lookups](../../../clusters/homelab/platform/dns/README.md) must resolve
   public names and the Octelium gateway address correctly through cluster DNS.
3. Only after these gates pass, render the current private control-plane config
   with the repository patch
   [controlplane-coredns-gitops-ownership.yaml](../../../.talos/patches/controlplane-coredns-gitops-ownership.yaml).
   Strictly validate the complete rendered config and review that the only
   semantic change is `cluster.coreDNS.disabled`; serialization can omit empty
   maps and lists. Preserve credentials, issuer, SANs, node configuration, and
   component versions. Follow the
   [private config rendering and validation workflow](../../talos-control-plane-maintenance.md#render-and-validate-the-control-plane-changes),
   producing `/private/tmp/controlplane-coredns-gitops.yaml` for this patch.
   After the separate production approval, apply this candidate with the
   matching Talos `v1.11.3` client in `no-reboot` mode:

   ```sh
   talosctl --talosconfig .talos/talosconfig \
     --endpoints 10.1.0.199 \
     --nodes 10.1.0.199 \
     apply-config --mode=no-reboot \
     --file /private/tmp/controlplane-coredns-gitops.yaml
   ```

   This is the CoreDNS handoff command; the issuer runbook's reboot sequence
   does not apply. Merging this PR alone does not authorize the Talos change.
4. Verify the Talos bootstrap manifest inventory no longer contains
   `11-core-dns` or `11-core-dns-svc`. Talos removes those internal manifest
   resources; it does not delete the existing Kubernetes DNS resources. Verify
   all six remain present and Argo-owned, both replicas stay Ready, the Corefile
   is unchanged, and the DNS lookups still pass. Only then unblock the separately
   reviewed Kubernetes upgrade.

Talos 1.11.3's upgrade dry-run is not a read-only acceptance gate: it can pre-pull
images and reapply the unchanged control-plane configuration during the proxy
step. Use targeted read-only state checks for this handoff; upgrade planning
must account for the documented CLI side effects.

## Bootstrap And Rollback

Fresh clusters still require Talos-provided DNS before Argo can resolve and
fetch repositories. Omit the disable patch from initial machine configuration,
bootstrap Argo, adopt all six resources, then perform the gated handoff above.
Automating these verified phases in the repository bootstrap workflow remains
follow-up work. This change does not establish a single-apply bootstrap path
with Talos DNS disabled from the start.

Before the handoff, the new resource declarations can be reverted without
deleting the adopted DNS resources because prune and deletion are disabled.
After the handoff, keep all six declarations and the Application; revert only
the desired DNS policy when rolling back a policy change. Re-enabling Talos
ownership needs a separately reviewed plan preserving the required Corefile.
Do not remove GitOps ownership while Talos's default DNS manifests are disabled.

Validation must compare rendered manifests with the current public resource
specifications, including the complete Pod template, Service IPs, selectors,
ports, and RBAC. Local rendering does not prove the live ownership handoff or
DNS and upgrade acceptance gates.

On 2026-09-07, Talos `v1.11.3` strict metal validation passed for a private
candidate rendered from the current control-plane configuration. The semantic
comparison confirmed that only `cluster.coreDNS.disabled` changed from its
absent/default-false value to `true`. The candidate was not applied; this check
does not complete the ownership or DNS acceptance gates.

Related: [[architecture/gitops-flow]], [[workloads/inventory]],
[[operations/validation-gates]].
