# Harbor Private OCI Registry

Tags: #harbor #oci #packages #gitops

## Ownership And Access

Harbor is declared in `IaC/terragrunt.stack.hcl` and
`clusters/homelab/apps/harbor`. The official chart is pinned to `1.19.2`
(Harbor `2.15.2`). Upstream component references remain digest-pinned; the
Talos mirror rollout redirects their pulls after all artifacts are copied. Fresh
bootstrap and registry recovery use the reviewed upstream rollback path.

`https://harbor.stinkyboi.com` uses Cloudflare Tunnel, the Octelium `harbor`
WEB Service, and the shared Istio gateway. Octelium transport is anonymous and
passes Authorization headers; Harbor authenticates every private artifact
request. Browser login interception would break Docker, Helm, ORAS and
containerd. Harbor registration is disabled and only administrators can create
projects. The `homelab` project is private.

In-cluster DNS resolves the hostname directly to Istio, retaining the same
publicly trusted TLS identity. Talos/containerd uses host DNS and pulls through
the public route. Hosted CI establishes a bounded Kubernetes port-forward to
Istio with the existing Octelium CI credential. Only its disposable runner maps
the Harbor hostname to loopback, bypassing Cloudflare upload-size limits while
retaining TLS verification. See `scripts/ci/harbor-publish.sh`.

The shared Octelium-to-Istio hop currently skips upstream certificate validation
for the Kubernetes Service hostname, as declared in
`docs/examples/octelium/homelab-services.yaml`. Public clients and CI still
verify Harbor TLS. A shared ingress hardening change should establish a trusted
upstream server name/CA and remove this bypass across the service catalog.

## Identity And State

SSM in `us-west-2` generates eleven Harbor secrets. `harbor-secrets` materializes
administrator, internal service, encryption and database secrets as well as
pre-generated project robot passwords. The bootstrap Job creates only the
private `homelab` project and its `pull` and `publisher` robots, plus the public
upstream-only `mirror` project and its own scoped `publisher` robot; publisher has
pull/push permissions and no artifact deletion. Source-controlled bootstrap
credentials stay outside this public repository.

NOFX gets only the read-only robot through its namespace-specific SSM alias
`/homelab/nofx/harbor-pull-password` and `harbor-pull` Docker config Secret.
Retain the database, registry blobs, signing certificate and encryption key
as a recovery set. Database lives on a retained local volume pinned to `acer`;
registry blobs and logical database backups use retained QNAP NFS. Backups on
the same NAS are not independent blob disaster recovery. See the app README
for backup schedule, restore sequence and limitations.

## Image Scanning

The chart enables Trivy with a retained 5 Gi cache. The repository-owned
PostSync bootstrap sets and verifies `auto_scan: "true"` for the private
`homelab` and `mirror` projects on creation and subsequent syncs. New image pushes
trigger scans. Bootstrap also submits missing scans for retained private
`homelab` image artifacts, leaving existing reports and active scans alone and
excluding signatures and attestations. Verify completed reports after sync;
successful submission does not prove a successful scan.
Backfill traverses the complete repository/artifact inventory, including histories
over 1,000 artifacts; duplicate IDs and inconsistent pagination still fail closed.
The separate robot inventory retains its 1,000-object safety bound.
See `clusters/homelab/apps/harbor/README.md`.

Grafana receives `harbor_vulnerability_critical_total` from the repository-owned
Harbor vulnerability collector. It queries only completed scan summaries for the
`homelab` and `mirror` projects and emits aggregate counts per project, without
artifact names, digests, CVE IDs, or credentials in metrics. The Grafana rule
alerts at critical severity after five minutes for a nonzero count; absent data
and evaluation errors also alert. Cached metrics expire within six minutes of a
failed collection, and script revisions roll the collector through its
versioned pod-template annotation. The raw Grafana query preserves healthy
zero-valued project series while missing telemetry enters Alerting. A completed
Harbor scan that omits its zero-valued `Critical` severity bucket contributes
zero. Triage in
Harbor, then rebuild and roll out a
remediated image through GitOps. Source: `clusters/homelab/apps/harbor/vulnerability-exporter.py`,
`clusters/homelab/apps/harbor/vulnerability-exporter.yaml`, and
`clusters/homelab/apps/grafana/values.yaml`.

Read-only acceptance on 2026-09-28 found scan-on-push enabled in both projects
and Trivy v0.72.0 healthy. Both running NOFX images had successful reports:
backend `6dfec7dd502b` (5 critical, 65 high findings) and frontend `210a1bd9ca7e`
(2 critical, 58 high findings). Remediation requires reviewed dependency/base
image updates and rebuilt images; successful scanning does not imply no known
vulnerabilities. Six retained historical images had no report, motivating the
bootstrap backfill. On 2026-09-29, the automatic PostSync job applied
[PR #1101](https://github.com/Stuhlmuller/homelab/pull/1101) at `453e935c563d`.
All 26 retained private image manifests reported successful scans at 00:18 UTC,
with no missing, pending, running or failed reports. The last of the six
historical scans completed at 00:16:55 UTC; Harbor was Synced/Healthy.
The earlier in-progress
mirror copy had successful scans for all 62 uploaded runnable manifests and
16 indexes inspected; 15 unscanned objects were in-toto attestations. This
snapshot does not establish scan completion for images not yet uploaded.

## Scoped application image publication

`harbor-mirror.yml` accepts only `image_scope=all` (the default) or `fleet`.
Fleet uses the fixed `scripts/config/harbor-fleet-images.json` subset, covering
exactly its rendered Fleet, MySQL, Redis and bootstrap Python images. CI rejects
missing, extra or non-inventoried sources. Both modes keep reviewed-main guards,
anonymous upstream reads, immutable digest checks and complete anonymous pulls.
They use the same existing mirror publisher and destination repositories.

The full-inventory workflow has no verified successful run as of October 3.
Run `36511537440` failed after 75 minutes copying an unrelated Python image
with sanitized category `transport-failed`; that missing digest remained in the
148-image inventory. Fleet's initial rollout therefore uses the fixed scope to
avoid coupling deployment to the full historical mirror audit. This does not
establish full-inventory mirror completion.

## Package Migration

Repository inventory found only the NOFX backend and frontend custom images.
Authenticated GHCR inspection on 2026-09-19 found two tags in each repository:
the Packages API also confirmed two active versions per repository and no
untagged versions. The releases are `f76c27834ff987aa1dfad81d0c9ff273be7dd3cd` and
`0b352ebd05a944de46b0cdda7240edbc10671d76`. Their four manifest hashes match
the [first publication](https://github.com/Stuhlmuller/homelab/actions/runs/34815485548)
and [second publication](https://github.com/Stuhlmuller/homelab/actions/runs/34926391605).
Exact source digests, release provenance and destination tags are committed in
`scripts/config/harbor-migration.json`.
The migration copies all referenced platform manifests, preserves digests,
compares destination manifests, and retains GHCR originals. It then uses the
namespace-scoped read-only robot credential in a separate authfile to download
all four complete artifacts into separate fresh temporary directories and
verify their digests. Explicitly anonymous manifest requests must fail with authentication
denial; network failures do not satisfy that gate. All downloaded content and
credentials are removed before the workflow exits. The repository
Actions token reads those private GHCR packages; local operator OAuth lacks
`read:packages`. This inventory does not establish the absence of packages
in other repositories or organization accounts.

New NOFX builds publish to Harbor after the existing build and reviewed-main
gates. The publisher emits only the two verified current-revision image references
as job outputs. A separate credential-free job validates them again and uploads
one fixed text file, retained for 30 days, for `gh run download`; private logs and
registry credentials remain outside artifacts. The live-job artifact upload ban
is unchanged. See the [NOFX build recipe](../../../builds/nofx/README.md#publish-update-and-revert)
for the artifact name and CLI retrieval command.

At the pre-cutover inspection on 2026-09-19, NOFX still used upstream images.
The initial maintained Harbor rollout then merged in PR #1036 at `78ca869` and
was verified Synced/Healthy with both `f76c278` images ready. See [[../apps/nofx]]
for runtime evidence and `clusters/homelab/apps/nofx/deployment.yaml` for current
desired references. Later source builds require a separate functional rollout.
Registry-origin cutover is required only for an actual custom-image consumer:
first verify copies and read-only pulls, then preserve that consumer's exact
digest while changing its registry through GitOps. The later cluster-wide mirror rollout below extends this to third-party images.

## Rollout And Acceptance

1. Validate static checks, rendered chart/manifests and Terragrunt plan. Merge
   through the repository's signed-commit and review gates.
2. From a clean checkout of exact merged main, regenerate the Terragrunt stack
   and plan/apply only `IaC/live/aws-ssm-parameters`, then
   `IaC/live/argocd-apps/harbor`. Review saved plans and run Conftest before
   applying; reject deletes, replacements, or unrelated changes. The shared
   SSM unit must be inspected for earlier drift before calling it Harbor-only.
   The full apply currently requires missing AzureAD credentials for unrelated
   changes; the documented unit-level path avoids that scope. Require healthy
   external secrets, storage, PostgreSQL and the bootstrap Job.
3. From a clean checkout of that exact reviewed main revision, reconcile the
   fixed Octelium Service with the command below. Reconcile Tunnel DNS through
   the existing `octelium-public-tunnel.yml` workflow.
4. Verify HTTPS, API health, `/v2/` authentication challenge, private project
   settings, denied anonymous artifact access and authenticated pull/push.
5. Run the migration workflow and require preserved digests, complete read-only
   pulls, and denied anonymous access. If custom-image consumers exist at that
   time, update only their registry references through GitOps, retain their
   exact digests, and verify new Pods pulled from Harbor. A source-version
   upgrade requires its separate functional acceptance checks.
6. Require a completed verified database backup, retained PVCs and documented
   restore limits before reporting operational readiness.

Operator command (review the exact SHA before running):

```sh
expected_sha='<reviewed-current-main-sha>'
test "$(git rev-parse HEAD)" = "$expected_sha"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(git ls-remote origin refs/heads/main | cut -f1)" = "$expected_sha"
nix develop --command python3 -I scripts/octelium-harbor-reconcile.py \
  --execute --expected-sha "$expected_sha"
```

The helper defaults to read-only without `--execute`. Execution selects only
`harbor.default`, requires exact clean reviewed main, reuses the pinned native
TLS carrier, verifies a second apply has no change, and reads back its access
contract. It never creates operator credentials or applies the entire catalog.

## Current Evidence

Harbor rollout was independently verified on 2026-09-20 UTC at main
`7a59f266eb0c776c97dc9bc72132e91d2a4dc09d`, merged through
[PR #1046](https://github.com/Stuhlmuller/homelab/pull/1046).
[Repository validation](https://github.com/Stuhlmuller/homelab/actions/runs/35486057081)
and [static policy/security checks](https://github.com/Stuhlmuller/homelab/actions/runs/35486057091)
passed; the corrected VirtualService also passed a live server-side dry run.

- Argo CD was Synced/Healthy with a successful operation at that exact revision.
  All nine workload Pods were Ready, all six PVCs were Bound, and the
  ExternalSecret and token-signing certificate were Ready.
- Public HTTPS passed certificate verification; the native Harbor login page
  rendered, and authenticated administrator API reads succeeded. Registration
  is disabled, project creation is administrator-only, `homelab` is private,
  and both project robots have their exact declared permissions.
  Anonymous `/v2/` returned HTTP 401 with Harbor's native Bearer challenge.
- The bootstrap and initial database-backup PostSync hooks succeeded. The
  initial dump passed archive and checksum verification. Nightly backups are
  enabled at 03:35 America/Los_Angeles; the nightly schedule has not yet run.
  This proves a logical metadata backup, not an independent registry backup
  or a completed restore drill.
- All four Prometheus targets (core, exporter, jobservice and registry) were
  UP without scrape errors; live namespace selection includes Harbor.
- The protected [current-main publisher](https://github.com/Stuhlmuller/homelab/actions/runs/35486181588)
  built and pushed both custom images to Harbor and verified destination
  digests. Future custom builds use this same private OCI path.
- The protected [migration](https://github.com/Stuhlmuller/homelab/actions/runs/35486238550)
  copied all four historical versions with their original tags and digests.
  Separate read-only robot downloads verified every complete artifact, and
  explicitly anonymous requests were denied. GHCR originals remain private
  and retained.
- Independent public Skopeo 1.24.0 acceptance downloaded all four artifacts
  through normal public DNS and verified TLS, with no tunnel or hosts override.
  All tag and full-download digests matched; anonymous requests were denied.
  The downloads totaled 193,487,792 bytes, and temporary credentials, policy
  and downloaded files were removed. Final API inventory showed two private
  repositories with three tagged releases each: both migrated releases and
  the new `7a59f266` build.

Python's default urllib User-Agent received HTTP 403 from the public endpoint.
The same HTTPS request with the descriptive
`homelab-harbor-acceptance/1.0` User-Agent returned the expected Harbor response;
curl also succeeded. Acceptance uses that explicit User-Agent without relaxing
TLS verification. The public Skopeo full-pull checks above also passed. Local
Nix/macOS Skopeo needed a temporary trust policy for these unsigned images:
default reject, with acceptance limited to the two exact repositories; expected
digests remained mandatory. No system policy was changed.

The largest migrated compressed layer was 18.96 MiB. These transfers do not
validate uploads over 100 MiB. No live workload uses the custom images yet;
a new Kubernetes image-pull check is still required before a consumer changes
its registry origin. The GHCR sources remain available for that later rollout.

Two rollout failures refined validation: ESO 2.0.1 requires an explicit
`bcrypt` argument to `htpasswd`, and the installed Istio CRD rejects
`timeout: 0s`. The VirtualService omits timeout (disabled by default) and sets
`retries.attempts: 0` to prevent replaying writes. See the
[Istio HTTPRoute reference](https://istio.io/latest/docs/reference/config/networking/virtual-service/#HTTPRoute).
Static rendering did not catch either runtime validation issue.

## Sources

- [Official chart](https://github.com/goharbor/harbor-helm/releases/tag/v1.19.2)
- [Harbor OCI support](https://goharbor.io/blog/harbor-2.0/)
- `clusters/homelab/apps/harbor/README.md`
- [[../architecture/storage-and-state]]
- [[../architecture/secrets-and-identity]]
- [[../architecture/gitops-flow]]

## Private Signing Rollout

New publications use the local P-256 key in the cert-manager-owned
`harbor-image-signing` Secret. `rotationPolicy: Never` preserves signer identity
through certificate renewal. `scripts/ci/harbor-publish.sh` creates the fixed
`signing-job.yaml` template for its two verified image digests. The Job mounts
the key inside the cluster; CI reads only its public key from successful Pod
status, checks its SHA-256 against `scripts/config/harbor-signing.json`,
and verifies both signatures. The enrolled fingerprint pins the independently
retained public key; an unset (`null`) fingerprint still fails closed. No AWS
signing resource, public signing service or transparency-log submission is used.
Existing registry credentials still follow the SSM/ExternalSecret contract above.

The Job has no API token and declares DNS/Istio egress. That NetworkPolicy is
not enforced by the current flannel CNI, and Harbor is not mesh-enrolled. A
compromised signer could exfiltrate its mounted private key and publisher
credential. This is an open isolation finding, not an enforced key boundary;
source: `docs/runtime-isolation.md` and the signing Job/NetworkPolicy. Before
claiming egress isolation, add a repository-owned enforcing dataplane, validate
DNS/Harbor access, and prove arbitrary external destinations are denied from
the signer. Pinned code, no API token, and a short lifetime do not replace that
control.

Temporary imported keys live
in memory-backed storage; finished Jobs expire after ten minutes. Namespace
Pod creators and cluster administrators remain trusted. Protect the signing
Secret in encrypted off-node etcd backups, retain public keys independently,
and restore the Secret before cert-manager after a disaster. PostgreSQL backups
do not cover the signing key. See `builds/nofx/README.md` for recovery and rollback.

Status: the retained signer's fingerprint is enrolled. Backup verification
receipts and the independently retained public key stay in private operator
storage. [NOFX Images run 36350207462](https://github.com/Stuhlmuller/homelab/actions/runs/36350207462)
completed the first signed publication and verified both stored signatures
against the enrolled fingerprint for source
`f0a60ec70b43e5e5b5a9691b4f59358d13089b7d`.
[NOFX Images run 36368577201](https://github.com/Stuhlmuller/homelab/actions/runs/36368577201)
published and verified the follow-up source
`e7014c8b9644a6c13d909373eda3c572c1cdba00`, including the `0015` protection fix.
Runtime rollout acceptance remains separate from publication; independent
operator signature verification remains pending.
Historical artifacts and pull/admission enforcement remain unchanged.

## Cluster-wide Image Mirror

The [mirror runbook](../../harbor-image-mirroring.md) owns copying, cutover and
recovery. `scripts/config/harbor-images.json` captures public upstream digests
from repository declarations, rendered charts and live Pods/system images. The
protected `harbor-mirror.yml` workflow copies all platforms into the normal
public-read `mirror` project and verifies complete anonymous pulls. A completed
ancestor publication is reusable only with the runbook's six publication files
unchanged; node rollout still requires exact reviewed `main` and live digest checks. Its publisher
uses a separate generated `/homelab/harbor/mirror-robot-push-password`; apply
the reviewed shared SSM plan before expecting the new bootstrap to complete. Private
`homelab` artifacts retain their existing authentication/signing contract.

The [first copy](https://github.com/Stuhlmuller/homelab/actions/runs/36382200622)
and [retry](https://github.com/Stuhlmuller/homelab/actions/runs/36388691071)
stopped during the second upstream copy used for PostgreSQL tag aliases (17.5,
then 14.23). Destination digest uploads and readback
had succeeded; Harbor showed no concurrent error or resource pressure. Deleted
private client logs prevented proving the underlying failure. The publisher now
creates aliases from the verified Harbor digest and resumes already-present
digest tags only after exact hash comparison. Complete anonymous downloads
still run for every entry. Failures expose fixed phase/status/category metadata
and the public catalog source, never raw transport output. This removes the
observed second external transfer.

[Recovery run 36506302738](https://github.com/Stuhlmuller/homelab/actions/runs/36506302738)
passed both PostgreSQL alias failures and completed the first 31 catalog entries,
then stopped at the missing PostgreSQL 18.4 digest tag. Live read-only probes
confirmed Harbor returns HTTP 404 with `NOT_FOUND` and an exact artifact or
repository `not found` message, rather than registry manifest/name-unknown.
The publisher now recognizes only those additional messages naming the expected
mirror repository and, for an artifact, its exact digest tag. Generic 404s and
messages naming other content still fail closed. Complete publication and node
cutover remain pending.

During the staged rollout, `harbor-secrets` reconciled before the new SSM
parameter existed. The approved scoped plan applied 16 creations and three IAM
updates, with no deletions or existing-secret rotations. After that apply, the GitOps
`generated-secret-revision` annotation advances to `v2` to request a fresh
reconciliation. Keep `refreshPolicy: OnChange` to avoid periodically regenerating
the salted bcrypt registry password hash. Require the ExternalSecret to report
Ready and materialize the mirror credential before accepting bootstrap or
starting image publication; the annotation change alone is not readiness evidence.

`.talos/patches/harbor-mirrors.yaml` and the validated
`scripts/talos-harbor-mirrors.py` path redirect containerd for all inventoried
registries, covering controller-generated Pods and Talos system images.
Authenticated Talos calls explicitly select the private `.talos/talosconfig` or
the operator-provided `--talosconfig` path; absent files fail before networking.
Talos skips cached pull references. The cutover probes pause in the `system`
namespace, where it was absent on all four nodes during this rollout. System
images and CRI share the mirror configuration; correlate the pull with Harbor
access logs, since repeating an already-cached probe proves no new request.
`skipFallback: true` prevents silent upstream pulls. Apply only after publication;
new image/chart versions need a prerequisite catalog publication. The rollback
patch restores upstream access for cold bootstrap or Harbor recovery. Existing
public DNS transport remains; this does not establish network isolation.

Initial inspection on 2026-09-28 UTC: all four nodes Ready, Harbor Synced/Healthy;
OpenClaw had unready app/proxy containers before this change. The 145 catalog
entries passed anonymous upstream manifest/digest verification. All four current
Talos configurations passed strict mirror-patch validation. Harbor registry NFS
reported about 901 GiB available (shared filesystem capacity, not a PVC quota);
no storage expansion was needed for this preflight. The shared SSM plan includes
pending AI secrets; the [targeted secret plan](../../harbor-image-mirroring.md#initial-secret-plan-scope)
limits publication to the new mirror credential and documents shared IAM/random
state dependencies requiring explicit operator approval. Image transfer
and node cutover remain pending; source verification is not migration evidence.

## HOME-57 collector privilege and lifecycle proposal

The [transition plan](../../harbor-vulnerability-exporter-transition.md) records
HOME-59's all-hop verified TLS target. No gateway-only exception was granted;
current code still lacks verified gateway→frontend→core TLS. Plaintext exposes
both credential confidentiality and metrics integrity. TLS does not establish
HOME-3 enforcement or prevent stolen-token replay through other allowed routes.

The [lifecycle proposal](../../harbor-vulnerability-credential-lifecycle.md) adds a
disabled manual protected workflow, exact-ID/scope/expiry verification, bounded
renewal, a one-version SSM envelope and unregistered ESO/writer-role candidates.
The proposed one-day issuer has system robot-management authority and requires
separate Decision Review disposition; helper restrictions are not server RBAC.
SRE owns #1163 integration; QA owns pinned-server controls and Recovery owns
first-cutover containment, alert limits and compromise revocation. Signing, full
validation, real authorization, all-hop TLS and operational evidence remain gates.
No provisioning, execution, live health or continuous renewal monitoring is claimed.


## HOME-57 integrated proposal

QA #1164 and Recovery #1165 are integrated into SRE's proposal with original
commits preserved. The [TLS/recovery integration contract](../../harbor-tls-and-recovery-integration.md)
records the unregistered chart renderer, verified upstream identity tests and
standalone metadata-only exact-ID recovery planner. HOME-62 rejected the proposed
system issuer: the workflow/helper cannot execute even if acceptance flags change.
Trust distribution, GitOps materialization, client/hook migration, actual proxy
and Harbor-denial evidence, expiry/alerts, signing and HOME-3 remain HOLD gates.
Recovery interruption limits are proposals, not authorized windows.


### Fixed-proposal integration and finite gaps

HOME-57 integrates QA #1172 and Recovery #1173 with the SRE custody correction
and current main `ee07c797`. See [the finite blocker table](../../harbor-integration-blockers.md)
for separate repository deliverables, unavailable identities/environment records,
signing/full validation, authority and execution approvals, and runtime evidence.
HOME-64 accepts preparation direction only; HOME-62's issuer rejection and all
hard stops remain. Offline model/TLS results do not establish server, proxy,
controller, effective IAM or recovery acceptance.
