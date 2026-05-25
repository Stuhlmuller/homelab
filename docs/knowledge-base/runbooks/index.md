# Runbooks Index

Tags: #runbooks #onboarding #operations

This section pulls the top-level onboarding docs and operational runbooks into
Obsidian. The source files remain canonical; these notes are compact maps of
what to read, what facts matter, and what must be updated with future changes.

## Onboarding Path

1. [[homelab-onboarding]] for the Talos cluster shape, worker bring-up, and
   cluster source-of-truth rules.
2. [[argocd-bootstrap]] to install Argo CD and hand steady-state ownership to
   GitOps.
3. [[argocd-app-onboarding]] to register workload Applications through
   Terragrunt and Argo CD.
4. [[storage-nfs]] before any stateful workload is treated as ready.
5. [[secrets-aws-ssm]] before any ExternalSecret or runtime credential contract
   is added.
6. [[tailnet-ingress]] before any app route, Funnel exception, or ingress host
   is added.
7. [[validation]] before any live mutation or rollout.

## Operations

- [[ci-cd]] records the GitHub Actions plan/apply model.
- [[runtime-isolation]] records current Pod Security and network isolation
  assumptions.
- [[rollback]] records dependency-aware app rollback order.
- [[talos-control-plane-maintenance]] records issuer drift repair and upgrade
  gates.
- [[image-automation]] records the opt-in Argo CD Image Updater policy.

## Supporting Maps

- [[../architecture/cluster-topology]]
- [[../architecture/gitops-flow]]
- [[../architecture/storage-and-state]]
- [[../architecture/secrets-and-identity]]
- [[../workloads/inventory]]
- [[../workloads/application-notes]]
- [[../source-map]]
