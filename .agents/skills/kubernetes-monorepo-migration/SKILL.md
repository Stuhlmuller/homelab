---
name: kubernetes-monorepo-migration
description: Plan or implement folder moves and layout refactors in an existing Kubernetes GitOps monorepo. Use when paths consumed by Argo CD, Flux, Helm, Kustomize, CI, or bootstrap automation must move safely.
---

# Migrate an existing GitOps layout

Treat each move as a change to the deployable source path. For a planning request, identify affected roots, migration order and verification. Make edits and reconcile live state only within the requested scope.

1. **Trace path consumers before moving files.** Start at each affected cluster's bootstrap and walk
   to the manifests. Check Argo CD Application and ApplicationSet source paths, Git file and
   directory generators, Flux Kustomization paths and source exclusions, and local chart and values
   references. Follow Kustomize resources, components, patches and generator inputs. Search literal
   old paths and parent directories for glob consumers in CI, ownership rules, update bots and
   provisioning code. Edit the authoritative generator or input when checked-in output is derived.
2. **Capture the baseline for each affected target.** Render with the repository's
   controller-compatible toolchain, using the same values, overlays, dependencies and destination
   defaults. Compare the proposed render with the baseline, including generated GitOps objects.
   Check resource identity by target cluster, group, kind, namespace and name. Also check controller
   object identity, tracking or inventory, prune settings and finalizers. Review generated names,
   selectors, PVCs and unexpected changes in desired resources.
3. **Keep ownership continuous during cutover.** Prefer changing the path on the same reconciliation
   object if the repo and controller can switch atomically. When independently reconciled roots make
   that unsafe, make the new path renderable first, switch the owner to it, then retire the old path
   after the declared rollout verifies it. Ensure a generator cannot discover both copies. When
   ownership must change, inspect the controller's prune and deletion semantics before choosing the
   handoff. A matching manifest render alone cannot prove a pruning handoff is safe.
4. **Validate through the normal entry points.** Render every affected consumer of shared manifests
   and check generator discovery and path-based CI coverage. Report unexpected render changes and
   any controller-side behavior that local checks could not establish. For an authorized rollout,
   verify the new source revision, reconciliation health and resource inventory through the existing
   deployment workflow. Preserve a rollback that restores both the files and their references.

Keep folder moves distinct from intentional workload changes where practical so resource diffs remain reviewable.

## References

- [Flux repository structure and delivery management](https://fluxcd.io/flux/guides/repository-structure/)
- [Red Hat GitOps directory structure](https://developers.redhat.com/articles/2022/09/07/how-set-your-gitops-directory-structure)
- [k8s Guru repository patterns](https://k8s.guru/docs/gitops/patterns/repo-structure/)
