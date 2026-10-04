# HOME-57 disabled TLS materialization and lifecycle alerts

HOLD merge and activation. This extends `8c666d4b` with input-independent R1/R5
source only. HOME-62's issuer rejection, disabled workflow and custody hard stops
remain binding. HOME-66 owns missing custody, environment and signing inputs.
QA's session-survival delivery #1174 at `3569689b` is integrated unchanged;
independent fixed-delivery and integration review remain required. No source or
test result establishes runtime acceptance.

## Concrete materialization

`clusters/homelab/apps/harbor-tls-candidate/kustomization.yaml` is unregistered.
It composes the existing Harbor directory with public NGINX overrides, six
cert-manager leaf declarations, verified Istio upstream identity, HTTPS bootstrap
and lifecycle alerts. Bootstrap/initial backup hooks are marked `Skip`, the
scheduled backup is suspended and the exporter has zero replicas. These are
proposal defaults, **not an approved way to stop production or run a full sync**.
Existing Jobs/Pods would still require Recovery's independent inventory/readback.

The offline renderer verifies the pinned chart archive and writes only three
allowlisted chart objects (NGINX ConfigMap/Deployment and frontend Service) plus
the public Issuer/Certificate declarations. It never serializes chart Secrets:

```sh
python3 scripts/harbor-tls-render.py --chart /reviewed/harbor-1.19.2.tgz --write-public-candidate
```

The unreferenced `application-sources.patch.yaml` describes the existing
Terragrunt-owned three-source Argo application, with the candidate directory last.
Argo's documented last-source-wins behavior replaces exactly those three chart
objects; three corresponding repeated-resource warnings are expected and tested.
Both Git source revisions are deliberately invalid `SIGNED_REVISION_REQUIRED`
placeholders; automation/prune/self-heal/retry are disabled. Review the eventual
change through the existing Terragrunt owner, not a competing applied Application.
No plugin, controller or operational identity is introduced.

The separate `trust/kustomization.yaml` cannot build without a reviewed public
`inputs/ca.crt` (ignored by Git). It generates only a backend ConfigMap, a
frontend CA-only Secret in `istio-system`, and an internal CA-only Secret in
`harbor`. Never supply private-key PEM or an issuer Secret to this generator.
Kustomize does not validate PEM semantics: independent input review must verify
CA constraints, fingerprints, validity, intended trust scope and absence of keys.
The issuer's existing-key Secret reference is an unresolved HOME-66 prerequisite;
these files neither generate nor distribute its key. Public trust must be
materialized separately and proven ready before any TLS leaf/client activation.

## Client and port migration inventory

| Consumer/path | Proposed connection and trust | Remaining acceptance |
| --- | --- | --- |
| Exporter / hosted publisher / signing Job | Existing verified `https://harbor.stinkyboi.com:443` via Istio | Positive private requests; unchanged hostname/public trust; no credential logs |
| Istio to Harbor frontend | Service 443 to NGINX 8443; `harbor-frontend` SAN and CA-only credential | Actual Envoy trust load, correct/wrong SAN/CA, expiry and reload |
| NGINX to core/portal | 8443; explicit `harbor-core`/`harbor-portal` SNI, backend CA, verification on | Actual NGINX negative controls and no HTTP fallback |
| Bootstrap | Fixed `https://harbor-core.harbor.svc.cluster.local:443`, backend CA ConfigMap, TLS >=1.2; no redirect/proxy | Old admin Pods gone; independently approved single execution; hook remains Skip |
| Chart jobservice/registry/scanner/internal clients | Chart TLS and CA bundle; core/portal/jobservice 8443, registry 5443, registryctl/trivy 8443 | Real internal clients, scan completion, push/pull and token flows |
| Browser / Docker / Helm / ORAS / Talos | Existing external hostname/443 | Cold pull, token exchange, upload, UI and recovery compatibility |
| Backup | Existing PostgreSQL 5432; no Harbor HTTP API credential | Existing backup/retrieval acceptance, separate approval to resume schedule |
| Monitoring | Chart metrics 8001; exporter 8080 and metadata 8081, monitoring ingress only | Scrape discovery and route labels; no claim these metrics paths use TLS |
| Redis / PostgreSQL | Existing 6379 / 5432 | Unchanged separate database transports; this proposal does not secure them |

NetworkPolicy changes follow rendered target ports; they do not prove enforcement.
Carry 8443/5443 and monitoring 8081 into HOME-3's every-node allow/deny matrix.
The external Octelium-to-Istio validation bypass documented in the KB remains an
independent HOME-59 client-path gate; this overlay does not claim to fix it.

## Rotation and reload proposal

`rotation/*.values.yaml` are unregistered, review-only annotation deltas for all
seven chart components. They are not automatic rotation jobs. Each phase needs
its own reviewed immutable revision and regenerated public NGINX overrides:

1. Expand the approved public CA bundle to old+new, increment trust revision to
   2, and explicitly plan bootstrap/collector client recreation. Establish actual
   bundle mount and proxy/client reload with positive and negative controls.
2. After verified overlap, change the separately approved issuer/leaf inputs;
   leaf revision 2 requests component rollout after certificates are Ready.
   Verify new serials/SANs/validity on every actual hop and all clients. A changed
   Secret or cert-manager `rotationPolicy: Always` alone does not prove reload.
3. Only after all old leaves/clients are gone and the recovery checkpoint is
   accepted, remove old public trust and advance trust revision to 3. Prove old
   trust rejection and retained new-path success. Do not rollback to HTTP/admin.

Issuer custody, overlap length, issuer and leaf deadlines, disruption limits,
client restart ownership and private backup/recovery records are input-dependent
HOME-66 items. No CA, key, operator identity or operational window is invented.

## Expiry, alert and deadline checks

The unregistered ESO proposal also projects numeric `expires_at` from the same
SSM envelope into `expires-at`. Only the sidecar mounts that key; it never mounts
the password or an API token, calls Harbor/AWS, or logs request contents. Missing,
malformed and implausibly distant metadata emit invalid status. Metadata is an
observation, not independently verified server expiry or atomic publication proof.
Writer races and ESO/version readback remain custody gates.

The proposed Prometheus rules detect missing/invalid metadata, renewal due with
ten days left (day 20 for a 30-day credential), passed expiry and absent/stale
collection. One-minute evaluation and an eight-minute stale threshold with a
one-minute pending period fire at nine minutes in the offline model. This is
not a guaranteed notification deadline: scrape/evaluation delay, Alertmanager
grouping, route delivery and observer latency must fit the proposed ten-minute
stop-forward bound in an approved environment. Recovery's 20-minute cutover and
15-minute renewal interruption limits remain proposals, not approved windows.

`scripts/ci/harbor-lifecycle-alert-check.py` runs nine actual PromQL cases using
promtool, including healthy controls, missing/invalid/expired metadata, wrong
namespace, and the stale deadline. `harbor-materialization-test.py` checks the
rendered composition, ports, disabled hooks, mounts, rotations and metadata errors.
Both are registered in the existing offline Harbor check, not a live workflow.

Runtime acceptance must separately record: named staffed renewal owner and
observer; verified server expiry against SSM/ESO versions; fresh collector
success; unique alert fingerprint/evaluation/firing/receipt timestamps through
the existing Alertmanager Discord route; independently observed wall-clock
deadline; missing-telemetry visibility; and resolved notification after recovery.
Use the existing route without silencing or changing the CVE alert. A synthetic
rule result or self-attested receipt is not delivery proof. No automatic renewal
or continuous monitoring is claimed while the candidate is unregistered.

The full finite gate inventory remains in [integration blockers](harbor-integration-blockers.md).

## Offline validation record

On 2026-10-04: 91 focused unit cases passed (11 materialization, 9 TLS,
25 lifecycle, 8 reader-boundary, 17 collector and 21 baseline bootstrap), plus
all nine PromQL cases using promtool 3.5.0. The local Prometheus archive matched
the upstream release checksum
`e811827af26d822afb09a4f28314f61b618b12cff5369835a67f674d8b46f39a`.
Changed Python passed Ruff; the candidate rendered with Kustomize 5.7.1 and
Helm 3.17.3 against the digest-checked Harbor 1.19.2 archive. These checks use
synthetic/offline inputs only. Full static checks passed runtime-bootstrap checks
then stopped at unavailable Terragrunt; no full validation or CI result claimed.
Main was re-fetched at `ee07c79754b10e2a708f45ba50f556102261b4ba` and #1163 at
`8c666d4ba98b60e91aa631e7c87a4ee837cde059` before publication.
