---
name: harbor-oci-repository-layout
description: Design or review Harbor OCI project boundaries, repository names, visibility, access, and artifact metadata. Use when organizing image families, onboarding services, separating build and release projects, or planning Harbor namespace migrations.
---

# Organize Harbor OCI repositories

## Design the layout

1. Identify independently published image families, their human and CI owners,
   who needs to pull or push, and which groups require distinct visibility,
   quotas, security settings, or lifecycle policies. For an existing registry,
   inventory current image paths and consumers in CI, deployment manifests, and
   automation.
2. Use Harbor projects to group related repositories with shared ownership and
   policy. Harbor applies RBAC and visibility at project scope and requires the
   project to exist before images can be pushed. Split build and release into
   separate projects when their access, quotas, security policies, or
   administration need to differ. For similar workloads under one owner and
   policy, start with one project and use repository and tag filters for
   lifecycle differences. Choose private projects for internal images and public
   projects for intentionally shared artifacts. Check that CI has push access
   and runtimes have pull access. Prefer project robot accounts for automation
   scoped to one project.
3. Give each independently versioned image family a stable repository. Use a
   readable lowercase convention and verify the full name against OCI naming
   rules and the target Harbor version and clients. A slash within a repository
   name can group names visually. For example, in `payments/services/api` the
   project is `payments` and the repository is `services/api`. Access still
   follows the project. Check existing names and references before recommending
   renames.
4. Document the owner, source, purpose, and usage in the repository's Info
   description. Use project or global Harbor labels for registry-side filtering.
   For metadata carried in the manifest or index, use OCI annotations such as
   `org.opencontainers.image.source`, `org.opencontainers.image.revision`, and
   `org.opencontainers.image.version`. Verify the resulting manifest or index if
   the annotations need to appear in Harbor.
5. Return a project/repository map showing example image references, access, and
   the reason for each project boundary. For migrations, map old to new
   references, verify the destination digest and pull permissions with a
   representative consumer, then update consumers before retiring old paths.

## Example layout

An application whose components share policy can use the project `payments` and
repositories `api` and `worker`, with references like
`harbor.example.com/payments/api:v1.4.2`. If CI can publish development images
but release publishing requires a distinct role, consider `payments-build/api`
and `payments-release/api` as separate project/repository pairs. These names
illustrate conventions you can adapt to the organization.

Use `harbor-oci-image-lifecycle` when designing tags, promotion, and cleanup for
the proposed layout.

## Official references

Use the Harbor docs for the deployed version. These links use Harbor 2.16.0.

<!-- markdownlint-disable MD013 -->

- Project creation, visibility, roles, and automation. [Create Projects](https://goharbor.io/docs/2.16.0/working-with-projects/create-projects/), [Project Configuration](https://goharbor.io/docs/2.16.0/working-with-projects/project-configuration/), [User Permissions by Role](https://goharbor.io/docs/2.16.0/administration/managing-users/user-permissions-by-role/), [Project Robot Accounts](https://goharbor.io/docs/2.16.0/working-with-projects/project-configuration/create-robot-accounts/)
- Image references, artifact descriptions, and labels. [Pulling and Pushing Images](https://goharbor.io/docs/2.16.0/working-with-projects/working-with-images/pulling-pushing-images/), [Repositories](https://goharbor.io/docs/2.16.0/working-with-projects/working-with-images/repositories/), [Managing Labels](https://goharbor.io/docs/2.16.0/working-with-projects/working-with-images/create-labels/)
- Repository name grammar and portable metadata keys. [OCI Distribution Specification](https://specs.opencontainers.org/distribution-spec/), [OCI Annotations Specification](https://github.com/opencontainers/image-spec/blob/v1.1.1/annotations.md)

<!-- markdownlint-enable MD013 -->
