---
type: overview
title: "Homelab OpenWiki"
description: "Task routes to homelab architecture, workload owners, bug diagnosis, validation, and agent skills."
tags: [homelab, navigation, agents]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-07T03:28:13.795Z
sources:
  - id: openwiki-source-22e2bb4f70068fd836cc9813
    resource: repo://scripts/ci/openwiki-check.py
generated: { by: "codex", at: "2026-10-07T03:28:13.795Z" }
---

# Homelab OpenWiki

Start here for feature work and bug fixes. This wiki connects repository source,
operating decisions, and runbooks. Current code and read-only live evidence
settle discrepancies; dated incident notes are historical evidence.

The wiki validation gate requires pages to be reachable from this entrypoint.
Generated indexes: [root](index.md), [apps](apps/index.md),
[architecture](architecture/index.md), [operations](operations/index.md),
[patterns](patterns/index.md), [runbooks](runbooks/index.md), and
[workloads](workloads/index.md).

## Find Task Context

<!-- markdownlint-disable MD013 -->

| Task | Read first | Owning source or skill |
| --- | --- | --- |
| Add or change an app | [Inventory](workloads/inventory.md), [application pattern](patterns/new-application.md) | App README under `clusters/homelab/apps/`; [app onboarding](../.agents/skills/homelab-app-onboarding/SKILL.md) |
| Fix a bug or regression | [Application notes](workloads/application-notes.md), [runbooks](runbooks/overview.md), [validation gates](operations/validation-gates.md) | Search the app, symptom, or resource name; follow callers, manifests, tests, and relevant incident evidence |
| Change IaC or GitOps | [GitOps flow](architecture/gitops-flow.md), [unit pattern](patterns/new-terragrunt-unit.md) | `IaC/stacks/`, shared catalog/modules; [Terragrunt workflow](../.agents/skills/terragrunt-workflows/SKILL.md) |
| Add a platform dependency | [Platform pattern](patterns/new-platform-service.md), [topology](architecture/cluster-topology.md) | `clusters/homelab/platform/`; [app onboarding](../.agents/skills/homelab-app-onboarding/SKILL.md) |
| Change secrets or identity | [Secret boundaries](architecture/secrets-and-identity.md) | [Secret contracts](../.agents/skills/homelab-secret-contracts/SKILL.md) |
| Diagnose storage or recovery | [Storage and state](architecture/storage-and-state.md), [PVC metrics](operations/pvc-metrics-recovery.md), [etcd scheduling](operations/etcd-scheduler-diagnostics.md) | Workload backup/restore runbooks and [application recovery](../docs/application-recovery.md) |
| Diagnose network or access | [Topology](architecture/cluster-topology.md), [Octelium](runbooks/octelium.md), [ingress](runbooks/tailnet-ingress.md) | Route manifests and workload README; compare native client and browser behavior |
| Change AI routing | [AI observability](architecture/ai-observability.md) | Caller configuration, LiteLLM/Langfuse contracts, and per-caller acceptance evidence |
| Publish or upgrade images | [Harbor](operations/harbor-oci.md), [chart organization](patterns/helm-chart-organization.md) | [Harbor images](../.agents/skills/homelab-harbor-images/SKILL.md) |
| Repair a PR or deliver a rollout | [Validation gates](operations/validation-gates.md) | [Protected PRs](../.agents/skills/homelab-protected-prs/SKILL.md), [release verification](../.agents/skills/homelab-release-verification/SKILL.md) |
| Maintain documentation | [Source map](source-map.md), [wiki maintenance](operations/wiki-maintenance.md) | [Homelab context](../.agents/skills/homelab-knowledge-base/SKILL.md), [OpenWiki](../.agents/skills/openwiki/SKILL.md) |
| Plan a larger feature | [Agent workflows](operations/agent-workflows.md) | Repository `speckit-*` skills and `.specify/` templates |

<!-- markdownlint-enable MD013 -->

## Gather Only Needed Context

1. Pick the task route, then locate the owner in inventory or the source map.
2. Search the wiki for the concrete uncertainty and read the matching sections.
   With OpenWiki MCP, use `openwiki_search` then `openwiki_read` with returned
   page and section references. Without it:

   ```sh
   rg -n -i 'octelium|grpc|transport' openwiki
   rg -n '^## ' openwiki/architecture/cluster-topology.md
   ```

3. Follow source pointers and inspect current callers, configuration, tests,
   and relevant read-only runtime evidence before editing.
4. Update the affected wiki pages with the change. Keep local validation,
   merged source, deployment, and live acceptance distinct.

Do not preload the full wiki. Use [source map](source-map.md) for canonical
paths, [runbooks](runbooks/overview.md) for operations, and
[continuous improvement](operations/continuous-improvement.md) for findings.
Preserve public-repository boundaries: secret references and safe examples
only; no credentials, raw private outputs, or certificate material.
