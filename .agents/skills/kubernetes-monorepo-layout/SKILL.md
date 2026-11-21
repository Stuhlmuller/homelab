---
name: kubernetes-monorepo-layout
description: Design or review Kubernetes GitOps monorepo folder structure for Argo CD or Flux. Use for choosing cluster and environment roots, placing apps and platform components, and defining how reusable manifests are composed.
---

# Design a Kubernetes GitOps monorepo

Inspect current controller entry points and repository conventions first. Identify the deployment targets, the owners of platform and workload changes, and where promotion is recorded. Preserve an existing layout that meets those needs.

## Choose the entry points

- Prefer a directory on the default branch for each independently reconciled target. Use a cluster name when the controller selects by cluster and an environment name when clusters intentionally share the same composition. Add a cluster override only when there is a real difference.
- Keep target roots focused on selecting deployable components and setting target-specific inputs. Follow the controller's actual wiring from bootstrap to workload. In Flux, trace the GitRepository and Kustomization source, path and dependencies. In Argo CD, trace Application sources and ApplicationSet generators or the parent Application where used.
- Keep cluster provisioning, GitOps bootstrap, shared platform services and workloads distinguishable by ownership and lifecycle. Define reconciliation dependencies for prerequisites such as CRDs, controllers and their custom resources. Directory ordering alone does not enforce readiness.
- Keep repository metadata and build inputs outside recursively scanned manifest roots, or use explicit inclusion rules. Check what the renderer will discover.

## Place reusable configuration

A starting point for a multi-cluster repo is `clusters/<target>/` for composition, `platform/<component>/` for shared operators and services, and `apps/<app>/` for reusable workloads. A single-cluster repo can keep components under its cluster root until sharing is useful. Use consistent names from the existing repository.

Use Kustomize bases and small overlays for manifest deltas, or shared Helm charts with target-specific values. Keep overrides at one obvious layer. Promote an immutable artifact or pinned version by changing the target declaration through the existing Git workflow. A shared base edit can affect every consuming target.

Match review ownership to paths and runtime permissions to controller configuration. CODEOWNERS routes reviews and can support branch protection. Git readers can see every tracked directory in the repository, so a requirement for separate read access needs a separate repository or source boundary. Keep credentials in the existing encrypted-secret or external-secret workflow.

For a design request, return the proposed tree, what reads each deployable root, and where a new app or target would go. Cite actual paths when reviewing an existing repo. Use the migration skill when rewriting live source paths.

## References

- [Flux repository structure](https://fluxcd.io/flux/guides/repository-structure/)
- [Red Hat GitOps repository considerations](https://developers.redhat.com/articles/2022/09/07/how-set-your-gitops-directory-structure#repository_considerations)
- [k8s Guru repository patterns](https://k8s.guru/docs/gitops/patterns/repo-structure/)
