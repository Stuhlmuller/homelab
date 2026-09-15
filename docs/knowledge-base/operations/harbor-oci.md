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
The successful [source publication](https://github.com/Stuhlmuller/homelab/actions/runs/34815485548)
used commit `f76c27834ff987aa1dfad81d0c9ff273be7dd3cd`; exact source digests and
destination tags are committed in `scripts/config/harbor-migration.json`.
The migration copies all referenced platform manifests, preserves digests,
compares destination manifests, and retains GHCR originals. The repository
Actions token reads those private GHCR packages; local operator OAuth lacks
`read:packages`. This inventory does not establish the absence of packages
in other repositories or organization accounts.

New NOFX builds publish to Harbor after the existing build and reviewed-main
gates. Changing runtime image origins happens only after destination copies
and private authenticated pulls pass. The separate NOFX simulation deployment
PR owns functional image activation; preserve its selected version during
registry cutover. No third-party images are mirrored by this task.

## Rollout And Acceptance

1. Validate static checks, rendered chart/manifests and Terragrunt plan. Merge
   through the repository's signed-commit and review gates.
2. Dispatch the protected full `Terragrunt Apply` at the exact merged main SHA
   to create SSM parameters and register Harbor. Require healthy external
   secrets, storage, PostgreSQL and the bootstrap Job.
3. From a clean checkout of that exact reviewed main revision, reconcile the
   fixed Octelium Service with the command below. Reconcile Tunnel DNS through
   the existing `octelium-public-tunnel.yml` workflow.
4. Verify HTTPS, API health, `/v2/` authentication challenge, private project
   settings, denied anonymous artifact access and authenticated pull/push.
5. Run the migration workflow, verify both preserved digests, then update NOFX
   registry references through GitOps. Verify new Pods pulled from Harbor.
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

Implementation validated; live Harbor deployment and migration remain pending.
The full static gate, four-platform Nix evaluation, signed-commit hooks,
deterministic Helm/Kustomize policy checks, 51 focused regression tests, and
OpenTofu module validation passed. The Harbor Application also passed a live
server-side dry run. Independent review corrected PostgreSQL prerequisite
ordering and the ClusterSecretStore namespace allow-list; the initial backup
hook is bounded to ten minutes within Argo CD's fifteen-minute operation.
Read-only inspection on 2026-09-14 found all four nodes Ready, every Argo CD
Application Synced/Healthy, no placement-blocking node taints, and the wildcard
TLS certificate Ready. Local AWS SSO was expired; protected Actions uses its
own AWS OIDC identity. None of these checks constitutes live Harbor rollout
or package migration acceptance.

## Sources

- [Official chart](https://github.com/goharbor/harbor-helm/releases/tag/v1.19.2)
- [Harbor OCI support](https://goharbor.io/blog/harbor-2.0/)
- `clusters/homelab/apps/harbor/README.md`
- [[../architecture/storage-and-state]]
- [[../architecture/secrets-and-identity]]
- [[../architecture/gitops-flow]]
