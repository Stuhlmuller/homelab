# Homelab Knowledge Base

Open `docs/knowledge-base` as an Obsidian vault. The vault is committed as
plain Markdown so it can be reviewed in pull requests and read without
Obsidian.

This knowledge base is the connective tissue between repo source files,
runbooks, and implementation decisions. It does not replace code, Terragrunt
state, Kubernetes manifests, or the detailed runbooks in `docs/`. When a note
and a source file disagree, fix the source of truth first, then update the note
in the same change.

## Start Here

- [[architecture/cluster-topology]] records the current Talos and Kubernetes
  shape.
- [[architecture/gitops-flow]] explains how changes move from git to the
  cluster.
- [[architecture/storage-and-state]] tracks durable state and backup gates.
- [[architecture/secrets-and-identity]] records secret and identity boundaries.
- [[architecture/ai-observability]] tracks caller routing, Langfuse attribution
  and the outstanding live acceptance gates.
- [[workloads/inventory]] lists app ownership, paths, dependencies, and state.
- [[workloads/application-notes]] points to workload READMEs and keeps only
  shared cross-application rules.
- [[runbooks/index]] maps the top-level onboarding and operations runbooks into
  vault notes.
- [[operations/continuous-improvement]] records the standing stewardship loop
  for security, reliability, findings, and follow-up work.
- [[operations/recovery-exercise-2026-10-01]] records the October synthetic
  Octelium restore exercise, proposed offsite checks and remaining live gates.
- [[operations/octelium-capability-research-2026-09-05]] records the requested
  security, audit-console, and Cordium CI/developer/agent execution expansion.
- [[operations/harbor-oci]] records private OCI registry ownership, package
  migration and rollout acceptance.
- [[operations/wazuh-siem]] records the deferred SIEM plan and restoration
  references for a future hardware upgrade.
- [[source-map]] lists the source docs and repo paths imported into the vault.
- [[patterns/new-application]] is the checklist for adding a new workload.
- [[patterns/helm-chart-organization]] records chart, values, and generated
  Application ownership for small deployment changes.
- [[patterns/new-platform-service]] is the checklist for shared platform
  services.
- [[patterns/new-terragrunt-unit]] is the checklist for new Terragrunt units.
- [[operations/validation-gates]] collects validation expectations.
- [[operations/harbor-recovery-acceptance]] records HOME-15 activation evidence,
  independent recovery inventory gaps and proposed outage targets.

## Focused Agent Workflows

Project skills under `.agents/skills/` route repetitive work to canonical
runbooks: `homelab-app-onboarding`, `terragrunt-workflows`,
`homelab-secret-contracts`, `homelab-harbor-images`, `homelab-protected-prs`,
and `homelab-release-verification`. Load only the workflow needed for the task;
the release skill distinguishes validation, merge, deployment, and live
acceptance.

Obsidian authoring skills are also available under `.agents/skills/`:
`obsidian-markdown` for note syntax, `obsidian-bases` for `.base` views, and
`obsidian-cli` for interacting with a running Obsidian instance. Their upstream
source and hashes are recorded in `skills-lock.json` at the repository root;
`THIRD_PARTY_NOTICES.md` preserves the upstream license notice.

## Update Rule

For every substantive change, update the smallest useful set of notes:

1. Read this index and any note related to the code or docs being changed.
2. Make the repository source change first.
3. Update affected knowledge-base links, inventories, decisions, and validation
   evidence in the notes that remain the durable source for that topic.
4. Mark unverified or environment-specific facts explicitly instead of writing
   them as general guidance.
5. Capture security and reliability findings in
   [[operations/continuous-improvement]] or the more specific affected note,
   with enough source context for the next agent or human to act.
6. When pulling source docs into Obsidian, keep source paths visible so readers
   can jump back to the canonical file before changing desired state.

## Public-Repo Boundary

Do not record secrets, raw credentials, private keys, Talos secrets, kubeconfigs,
token values, raw certificate material, or private-only hostnames here. Safe
references such as ExternalSecret names, SSM parameter paths, public runbook
paths, and known homelab LAN addresses already documented in the repo are fine.
