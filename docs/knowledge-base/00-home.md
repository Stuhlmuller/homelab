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
  publication and rollout acceptance.
- [[source-map]] lists the source docs and repo paths imported into the vault.
- [[patterns/new-application]] is the checklist for adding a new workload.
- [[patterns/helm-chart-organization]] records chart, values, and generated
  Application ownership for small deployment changes.
- [[patterns/new-platform-service]] is the checklist for shared platform
  services.
- [[patterns/new-terragrunt-unit]] is the checklist for new Terragrunt units.
- [[operations/validation-gates]] collects validation expectations.

## Focused Agent Workflows

Project skills under `.agents/skills/` route repetitive work to canonical
runbooks: `homelab-app-onboarding`, `terragrunt-workflows`,
`homelab-secret-contracts`, `homelab-harbor-images`, `homelab-protected-prs`,
and `homelab-release-verification`. Load only the workflow needed for the task;
the release skill distinguishes validation, merge, deployment, and live
acceptance.

Spec Kit 0.15.1 adds ten `speckit-*` skills for specification, clarification,
planning, task generation, analysis, implementation, convergence, checklists,
constitution authoring, and issue creation. `.specify/init-options.json` records
the Codex integration, Python helpers, and sequential feature numbering;
`.specify/templates/` and `.specify/workflows/speckit/workflow.yml` own the
artifact templates and review gates. Feature selection is stored in
`.specify/feature.json`; helpers ignore `SPECIFY_INIT_DIR`, `SPECIFY_FEATURE`,
and `SPECIFY_FEATURE_DIRECTORY` inherited from the shell. Run commands from
the intended checkout and edit `feature_directory` in that file to switch
features. `.specify/memory/constitution.md` remains an
unfilled template; use `speckit-constitution` to establish project principles
before relying on constitution checks. Repository `AGENTS.md` remains the
operational guide.

Spec Kit updates must pass the existing Super-Linter Markdown and ShellCheck
rules; imported upstream files are not exempt. Run
`shellcheck -x -P SCRIPTDIR .specify/scripts/bash/*.sh` and
`python3 -I scripts/ci/speckit-check.py` before pushing. The static gate runs
the latter against temporary projects, including paths with spaces, stale
shell variables, missing selection, and existing-plan preservation.
Installation manifests retain upstream hashes
so local compatibility edits remain detectable during upgrades.

To roll back an upgrade, open a PR with `git revert <spec-kit-upgrade-commit>`
and run the checks above. This restores the skills, `.specify` helpers,
templates, and manifests together. To remove the initial installation, revert
its squash commit; that also removes the smoke-check registration from
`scripts/ci/static-checks.sh`. Keep authored `specs/` documents. Before either
rollback, copy any `.specify/feature.json` to a private backup when it exists;
do not commit the backup. Restore its `feature_directory` to the intended
existing spec path after an upgrade rollback, then verify with
`python3 .specify/scripts/python/check_prerequisites.py --json --paths-only`.
For complete removal, remove a leftover untracked `.specify/feature.json`
only after backing it up: `if [ -f .specify/feature.json ]; then rm .specify/feature.json; fi`.

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
