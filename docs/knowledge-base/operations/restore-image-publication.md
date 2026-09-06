# Protected restore image publication

Related: [[restore-egress-boundary]], [[../architecture/gitops-flow]],
[[../runbooks/runtime-isolation]].

## Scope and trust boundary

This follow-up adds a manual publisher for the exact tested amd64 restore image.
It changes no live workload, registry visibility, GitHub environment or cloud
configuration. Publication has not been executed. The extended native schema2
reproducibility test also remains pending until this follow-up's Linux CI runs.
Parent PR #978's Docker result is not evidence that this publisher has run.

The existing `homelab-production` environment is reused. Read-only inspection on
2026-09-06 verified required reviewer approval and a `main` deployment-branch
restriction; self-review is allowed, matching the already documented limitation.
No new environment or unprotected substitute is created. Protection ownership
remains outside this workflow; if those controls change, restore them through
its owning declared path before dispatching.

`.github/workflows/restore-image-publish.yml` accepts only an exact expected
main SHA. Its read-only prepare job runs repository/static policy checks and the
native image/SQL/network tests, then records a candidate schema2 manifest digest.
Only the dependent `homelab-production` job has `contents: read` plus
`packages: write`. It checks exact dispatch/checkout/current-main identity,
rebuilds and retests from that main commit, and requires the exact prepare digest.
No PR code, downloaded Actions artifact, floating image tag or saved runner image
is promoted into the protected job. Credentials are injected only by CI; there
is no PAT, cached-login or local-operator credential fallback.

A UUID-named disposable `docker-container` builder uses the digest-pinned official
BuildKit v0.33.0 image (official release and registry manifest digest verified
on 2026-09-06). It exports a rewritten Docker archive, loads that archive,
and is removed in `finally` before runtime tests. The build context contains only
the public Dockerfile and launcher; no credentials or secrets are forwarded.
The daemon is CI build infrastructure, separate from the non-root/drop-ALL runtime.
Buildx metadata’s `containerimage.config.digest` is validated against the loaded
Docker image ID before tests; its manifest digest is never treated as an image ID.
[Docker archive exporter support][docker-export]. Then
all tests and the export address that immutable ID. The temporary tag is used
only for building and cleanup. No default builder selection is changed. The config is bound to source SHA and repository
label before tests. [Docker-daemon image ID syntax][transport]. The publisher exports that very image as Docker schema2 into Skopeo’s `dir:` layout, hashes every config,
manifest and layer blob, and confirms the tested config ID and amd64 identity.
Export uses `--format v2s2 --dest-compress` to preserve tested config bytes and
prepare compressed layer digests before publication. Default OCI conversion
rewrote the config in Linux run `34012615040` and correctly failed its binding
gate. The directory transport supports the original schema2 manifest; the OCI
layout transport advertises only OCI media types. [Transport implementation][directory].
Publication transfers with Skopeo `--preserve-digests`. Authenticated registry readback must
return the same manifest bytes/digest at both the source tag and digest address.
The prepare/rebuild equality is fail-closed: toolchain/export drift requires
investigation, not accepting a new digest at the approval boundary.
[GHCR source labels and workflow tokens][ghcr], [Skopeo preserved digests][skopeo],
[registry digest verification][registry].

## Dispatch and readback

Only after this follow-up and its parent are reviewed, merged and their Linux
checks genuinely pass, dispatch the committed main workflow with the reviewed
full SHA:

```sh
gh workflow run restore-image-publish.yml --ref main -f expected_sha=REVIEWED_MAIN_SHA
```

Review the prepare job's source/digest summary before approving the existing
production environment. The protected job rechecks current main before testing
and immediately before the push; a stale dispatch fails. The workflow's serial
concurrency group prevents its own simultaneous publishers. Registry tags are
not inherently immutable against other writers: consumers must use the emitted
`ghcr.io/stuhlmuller/homelab-postgres-restore-drill@sha256:...` address, never the
convenience `git-SHA-amd64` tag.

Only explicit registry `MANIFEST_UNKNOWN`/`NAME_UNKNOWN` 404 responses permit a
new push. Authentication/network failures do not imply absence. An existing
tag with a different candidate is refused; an identical retry verifies readback
without pushing again. The final summary records source/config/manifest identity.
A readback failure leaves the run failed even if a push may have reached GHCR;
inspect/retry the same reviewed source, never overwrite its tag to mask a mismatch.

First publication defaults to a **private** GHCR package. Source-repository
association does not make it public. This workflow neither changes visibility
nor injects a cluster image-pull credential. The receipt explicitly leaves
public pull and production-runtime verification false. Before cluster use,
provide and review the missing registry visibility/access code path, verify an
anonymous pull by the exact digest, and complete the separate repository-owned
Talos/containerd synthetic Job with no real backup mount. GitHub UI edits or
extra credentials are not an implicit part of this prerequisite. [GHCR visibility][ghcr].

## Validation and rollback

`restore-image-publish-test.py` exercises source-context rejection, content/source
binding, malformed/corrupt schema2 data, explicit registry absence, overwrite refusal,
idempotent readback, changed response rejection, and builder cleanup after
build/metadata/load failure without any network calls.
The normal static gate runs it and pins both credential-bearing jobs plus the
complete workflow hash in its reviewed inventory. The Linux image job additionally performs two
independent complete image builds/tests/schema2 exports and requires matching bytes.
Both builds disable Docker layer caching and are separated by two seconds to
expose creation-time drift; the immutable base image may remain cached. Docker
export explicitly sets `rewrite-timestamp=true` alongside `SOURCE_DATE_EPOCH=1`:
the build argument alone does not normalize file timestamps inside layers.
Run `34012857646` caught that difference in the new launcher layer while both
runtime tests and exact schema2 config checks passed. [BuildKit reproducibility][repro].
The job
has no publishing permission or credentials. These gates must pass on the
final combined source, including the parent's SCM_RIGHTS denial fix.

Before publication, cancelling the dispatch leaves GHCR unchanged. After a
successful or uncertain push, do not delete/rewrite existing source tags or
blobs. There is no workload to roll back in this prerequisite. Later consumers
must revert their declarative image pin to the prior tested digest through a
reviewed PR; suspend the real drill if its enforced boundary cannot be proven.
Neither a new registry digest nor Docker success authorizes real backup reads.

[ghcr]: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
[skopeo]: https://github.com/containers/skopeo/blob/main/docs/skopeo-copy.1.md
[registry]: https://distribution.github.io/distribution/spec/api/

[transport]: https://github.com/containers/image/blob/main/docs/containers-transports.5.md

[directory]: https://github.com/containers/image/blob/main/directory/directory_dest.go

[repro]: https://github.com/moby/buildkit/blob/master/docs/build-repro.md

[docker-export]: https://docs.docker.com/build/exporters/oci-docker/
