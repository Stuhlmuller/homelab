# Harbor Private OCI Registry

Tags: #harbor #oci #packages #gitops

## Ownership And Access

Harbor is declared in `IaC/terragrunt.stack.hcl` and
`clusters/homelab/apps/harbor`. The official chart is pinned to `1.19.2`
(Harbor `2.15.2`); upstream component images remain public, digest-pinned
bootstrap dependencies. Harbor must not depend on images stored in itself.

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

SSM in `us-west-2` generates ten Harbor secrets. `harbor-secrets` materializes
administrator, internal service, encryption and database secrets as well as
pre-generated project robot passwords. The bootstrap Job creates only the
private `homelab` project and its `pull` and `publisher` robots; publisher has
pull/push permissions and no artifact deletion. Source-controlled bootstrap
credentials stay outside this public repository.

NOFX gets only the read-only robot through its namespace-specific SSM alias
`/homelab/nofx/harbor-pull-password` and `harbor-pull` Docker config Secret.
Retain the database, registry blobs, signing certificate and encryption key
as a recovery set. Database lives on a retained local volume pinned to `acer`;
registry blobs and logical database backups use retained QNAP NFS. Backups on
the same NAS are not independent blob disaster recovery. See the app README
for backup schedule, restore sequence and limitations.

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
gates. Live inspection on 2026-09-19 confirmed NOFX still runs its upstream
backend/frontend digests and Argo CD is Synced/Healthy at main `e17e34a6`.
No deployed workload currently consumes the custom packages. Merged PR #1031
bootstraps private GHCR credentials and retains upstream runtime images;
adopting the custom NOFX release remains a separate functional rollout.
Registry-origin cutover is required only for an actual custom-image consumer:
first verify copies and read-only pulls, then preserve that consumer's exact
digest while changing its registry through GitOps. No third-party images are
mirrored by this task.

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
   exact digests, and verify new Pods pulled from Harbor. Current upstream NOFX
   runtime images do not require a registry-origin change.
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

New publications use the dedicated asymmetric KMS key declared by
`IaC/.catalog/units/live/harbor-signing` and `IaC/modules/aws-oci-signing-key`.
`scripts/ci/harbor-publish.sh` signs verified digests and verifies the stored
Cosign signature before publication succeeds. Public Sigstore services and
transparency-log upload are explicitly disabled; signatures remain in Harbor.
The existing protected AWS publishing role can sign; this is not a separate
workflow-specific IAM identity. See `builds/nofx/README.md` for verification,
key rotation, failure recovery and rollback implications.

Status: implementation prepared; KMS apply, first signed publication and
independent live signature verification are pending. Existing artifacts are
not retroactively signed. No admission or pull enforcement is enabled.
