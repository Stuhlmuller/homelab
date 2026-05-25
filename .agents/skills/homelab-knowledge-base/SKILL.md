---
name: homelab-knowledge-base
description: Use for every substantive change in the homelab repository, especially when adding, modifying, or reviewing applications, platform services, Terragrunt/OpenTofu units, Talos/Kubernetes workflows, runbooks, or architecture. Read the Obsidian knowledge base before building new things and update it after the change.
---

# Homelab Knowledge Base

This skill keeps `docs/knowledge-base` useful as the repo evolves. Use it for
non-trivial homelab work, especially new apps, platform services, infrastructure
units, topology changes, secret contracts, storage behavior, validation gates,
and runbook updates.

## Workflow

1. Read `docs/knowledge-base/00-home.md`.
2. Read the smallest relevant set of linked notes before changing behavior.
3. Read the source docs and code named by those notes. The knowledge base is an
   index and memory layer, not the source of truth.
4. Implement the requested repo change through repository-owned code and docs.
5. Update the affected knowledge-base note or notes in the same change.
6. Add an entry to `docs/knowledge-base/operations/change-log.md` when the work
   creates, removes, renames, or materially changes an app, platform dependency,
   workflow, topology assumption, secret contract, storage requirement, or
   validation gate.
7. Record validation performed and any skipped checks in the final response.

## What To Update

- New or changed app: update `docs/knowledge-base/workloads/inventory.md`,
  relevant architecture notes, and the change log.
- New platform service: update the relevant architecture note, validation gates
  if readiness checks changed, workload dependencies if downstream apps depend
  on it, and the change log.
- New Terragrunt/OpenTofu unit: update GitOps flow or validation notes when the
  unit changes module ownership, bootstrap flow, dependency structure, or
  command expectations.
- Secret contract change: update `architecture/secrets-and-identity.md` and the
  workload inventory without committing secret values.
- Storage or state change: update `architecture/storage-and-state.md`,
  `workloads/inventory.md`, and any storage runbook references.
- Docs-only learning update: update the knowledge-base note that helps future
  readers find or understand the new runbook material.

## Style

- Use Obsidian wikilinks for knowledge-base links, for example
  `[[architecture/gitops-flow]]`.
- Keep notes concise and source-linked. Prefer pointers to source docs over
  copying long runbook sections.
- Mark unverified facts as unverified. Do not turn guesses into durable facts.
- Keep public-repo boundaries: no raw secrets, kubeconfigs, Talos secrets,
  tokens, private keys, raw certificate material, or private-only hostnames.
- If a note conflicts with repository source files, fix the source of truth
  first, then update the note.
