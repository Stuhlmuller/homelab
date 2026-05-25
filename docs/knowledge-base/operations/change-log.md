# Knowledge Base Change Log

Tags: #operations #knowledge-base

Record entries when a change creates, removes, renames, or materially changes an
app, platform dependency, workflow, topology assumption, secret contract,
storage requirement, or validation gate.

Use [[templates/knowledge-update]] for new entries.

## Entries

### 2026-05-25 - Initial knowledge base

- Added this Obsidian vault under `docs/knowledge-base`.
- Seeded notes for cluster topology, GitOps flow, storage, secrets, validation,
  workload inventory, and build patterns.
- Added the `homelab-knowledge-base` project skill so future agents read and
  update these notes during substantive work.

### 2026-05-25 - Import runbooks into Obsidian

- Added Obsidian runbook notes for onboarding, Argo CD bootstrap, app
  onboarding, image automation, CI/CD, tailnet ingress, rollback, runtime
  isolation, secrets, storage, Talos maintenance, and validation.
- Added app-specific operational notes from workload and platform READMEs.
- Added a source map so vault readers can jump back to canonical repo docs.
- Marked current working-tree app drift: Policy Bot and Hummingbot are present
  in source paths while Freqtrade is deleted and older inventory docs still need
  reconciliation.
