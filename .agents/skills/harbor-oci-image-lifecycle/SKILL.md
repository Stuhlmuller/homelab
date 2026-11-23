---
name: harbor-oci-image-lifecycle
description: Design or review OCI image versioning and cleanup in Harbor. Use for release and build tags, digest pinning, image promotion, multi-platform indexes, tag immutability, tag retention, project quotas, or garbage collection.
---

# Manage the Harbor OCI image lifecycle

## Version and promote

1. Inventory how CI publishes, how deployments resolve images, which releases
   are needed for rollback, and whether the artifact is a platform manifest or a
   multi-platform index. Check the deployed Harbor version before relying on a
   specific copy or policy behavior.
2. Define tag classes suitable for the release process. For example, use
   `v1.4.2` for a release, `git-<full-sha>-<build-id>` for a distinct CI build,
   and `edge` as an optional moving alias. Harbor lets tags move by default.
   Make release tags immutable with project-level repository and tag patterns,
   and ensure rules leave intended moving aliases mutable. Rules combine with
   OR. A protected tag also blocks deletion of its artifact while the protection
   applies.
3. Record the manifest digest, using the index digest for a multi-platform
   release. Use `<registry>/<project>/<repository>@sha256:<digest>` where
   deployments need to reproduce an exact image. Keep a tag covered by a
   retention or immutability rule for any deployed or rollback digest that must
   stay pullable.
4. Promote the same built artifact through validation and release. Check copy
   behavior before selecting a method. Harbor 2.16 documents that its
   Repositories **Copy** action also carries tags, index children, and
   accessories such as Cosign signatures and SBOMs. If only a release tag
   belongs in the destination, account for other source tags before copying.
   Verify the destination digest, tags, platforms, and required signatures or
   attestations before changing consumers.

## Retain and reclaim

1. Translate rollback and CI needs into retention rules. For example, retain
   approved release tags for the agreed support period and keep recent
   disposable builds according to throughput and quota. In Harbor, rules apply
   per project and can select repositories. Counts apply per selected
   repository, rules combine with OR, and retaining one tag can retain other
   tags on the same artifact digest. Check the documented filter order
   (repository, count or age, then tag filter) and review matches for the actual
   tag set.
2. Inventory deployed and rollback digests, index children, and required
   accessories or OCI referrers. Review untagged artifacts explicitly. A
   deployment can still reference an artifact by digest after its last tag
   moves. Compare retention dry-run results against the inventory before
   scheduling or running the policy. Check the quota separately, since retention
   rules do not override project quotas.
3. Use Harbor's administrator garbage collection dry run to estimate physical
   storage reclamation. GC removes unreferenced blobs. Its optional
   untagged-artifact setting can also remove artifacts with no tag, so review
   digest-only consumers before enabling it. Estimate reclaimable space from the
   GC dry run because surviving manifests can share blobs.
4. Return a proposed tag policy, an example deployment reference, the effective
   rules and their scope, and any dependencies or dry-run results that still
   need verification.

Use `harbor-oci-repository-layout` when the policies require changes to project
boundaries or repository names.

## Official references

Use the Harbor docs for the deployed version. These links use Harbor 2.16.0.

<!-- markdownlint-disable MD013 -->

- Tag movement and project immutability. [Harbor Tag Immutability Rules](https://goharbor.io/docs/2.16.0/working-with-projects/working-with-images/create-tag-immutability-rules/), [OCI Distribution Specification](https://specs.opencontainers.org/distribution-spec/)
- Copy, artifacts, and multi-platform indexes. [Harbor Repositories](https://goharbor.io/docs/2.16.0/working-with-projects/working-with-images/repositories/), [OCI Image Index Specification](https://github.com/opencontainers/image-spec/blob/v1.1.1/image-index.md)
- Policy matching, quotas, and storage reclamation. [Tag Retention Rules](https://goharbor.io/docs/2.16.0/working-with-projects/working-with-images/create-tag-retention-rules/), [Project Quotas](https://goharbor.io/docs/2.16.0/administration/configure-project-quotas/), [Garbage Collection](https://goharbor.io/docs/2.16.0/administration/garbage-collection/)

<!-- markdownlint-enable MD013 -->
