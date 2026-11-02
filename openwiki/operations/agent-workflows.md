---
type: workflow
title: "Agent Workflows"
description: "Focused homelab skills and Spec Kit planning, validation, and rollback."
tags: [agents, skills, spec-kit]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-18T17:42:33.479Z
sources:
  - id: openwiki-source-b0a3b747268ffb4a3afe9b8b
    resource: repo://.specify/extensions.yml
  - id: openwiki-source-06bb1be2fc0a5796cdc353ee
    resource: repo://.specify/extensions/assess/commands/speckit.assess.decide.md
  - id: openwiki-source-fca4dd6930b3588ec83f834f
    resource: repo://.specify/extensions/assess/commands/speckit.assess.research.md
  - id: openwiki-source-35a262cf1ec77a810a576502
    resource: repo://.specify/extensions/assess/extension.yml
  - id: openwiki-source-23f4f29f42d3e5ba42a52b6a
    resource: repo://.specify/extensions/assess/README.md
generated: { by: "codex", at: "2026-10-18T17:42:33.479Z" }
---

# Agent Workflows

Use the task routes in [quickstart](../quickstart.md) before loading a skill.
The homelab skills point to canonical runbooks; OpenWiki supplies searchable
cross-cutting context. See [wiki maintenance](wiki-maintenance.md) for its
installation, update, and verification workflow.

## PR Delivery

Repository change tasks continue through protected merge unless the user asks
for preparation only. The [delivery runbook](../../docs/pr-delivery.md) connects
PR contribution, protected merging, and stack maintenance. The delivery owner
repairs actionable ancestors first, then restacks and resumes descendants.
Drafts and external waits retain a specific next action and ready condition.
Merge completion is verified in GitHub and `main`; deployment acceptance remains
separate. A durable runner must resume pending work after checks or dependencies
change; instructions alone do not schedule another agent session.

The [planner](../../scripts/pr-delivery.py) orders live PR dependencies and
records checkout-local branch ownership and continuation. Its output is
advisory: protected merge still verifies signatures, reviews, integration
identities, and activation gates. The
[regression suite](../../scripts/ci/pr-delivery-test.py) exercises conflicting
parents, restacking, missing checks, and interrupted ownership; it runs in the
repository offline gate and focused PR Delivery workflow. A Codex heartbeat
provides recurring delivery using the authenticated agent runtime.

## Reference Coding

Before nontrivial code with a relevant upstream or peer implementation, search
the pinned XERJ corpus and inspect the cited source. [AGENTS.md](../../AGENTS.md)
sets this workflow; the [reference coding guide](../../docs/xerj-reference-coding.md)
lists the corpora, local indexing commands, and search examples.

## Spec Kit

Spec Kit 0.15.1 provides ten core `speckit-*` skills for specification,
clarification, planning, task generation, analysis, implementation,
convergence, checklists, constitution authoring, and issue creation.
The local [`assess` extension](../../.specify/extensions/assess/README.md) adds
five Codex skills for intake, research, problem definition, concept shaping,
and a go / needs-clarification / kill decision. Its commands write to
`.specify/assessments/<slug>/`; it registers no lifecycle hooks and hands a
`go` decision to `speckit-specify` only when invoked. An automated
needs-clarification result names the artifact to update. Existing artifacts
require user-authorized interactive revision before the decision is rerun.
`.specify/extensions.yml` enables the extension; `.specify/extensions/.registry`
records its manifest hash and five commands. Run `specify extension list` to
verify registration.

`.specify/init-options.json` records the Codex integration, Python helpers,
and timestamp-prefixed feature directories (`YYYYMMDD-HHMMSS`);
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
For assessment content, also lint the new Markdown skills and command files
and run the repository's pre-commit checks.
Installation manifests retain upstream hashes
so local compatibility edits remain detectable during upgrades.

To roll back the assessment extension, revert its source, registry, and five
skills together in a PR, then rerun the checks above. Keep any authored
`.specify/assessments/` records.

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
