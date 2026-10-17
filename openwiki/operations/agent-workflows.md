---
type: workflow
title: "Agent Workflows"
description: "Focused homelab skills and Spec Kit planning, validation, and rollback."
tags: [agents, skills, spec-kit]
---

# Agent Workflows

Use the task routes in [quickstart](../quickstart.md) before loading a skill.
The homelab skills point to canonical runbooks; OpenWiki supplies searchable
cross-cutting context. See [wiki maintenance](wiki-maintenance.md) for its
installation, update, and verification workflow.

## Spec Kit

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
