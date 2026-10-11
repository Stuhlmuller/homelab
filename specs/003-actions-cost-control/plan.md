# Implementation Plan: Homelab Actions Cost Control

**Branch**: `codex/actions-cost-control` | **Date**: 2026-10-11 | **Spec**: [spec.md](spec.md)

## Summary

Keep the seven `main` ruleset PR checks automatic, retain existing `main` push and manual lanes, remove optional PR work
and excessive schedules, and remove only the `homelab-plan` environment reviewer from its declared source in
`Stuhlmuller/github-iac`. The environment change and workflow changes are coordinated with documentation and
exact-context verification. No production apply or credential change is part of this feature.

## Technical Context

**Language/Version**: GitHub Actions YAML, HCL, Python/shell repository checks  
**Primary Dependencies**: GitHub Actions, GitHub environments/rulesets, Terragrunt/OpenTofu, repo static policy  
**Storage**: Git source in homelab and github-iac; no new runtime storage  
**Testing**: YAML parsing, static checks, Spec Kit check, `git diff --check`, GitHub PR context observation, read-only environment and ruleset inspection  
**Target Platform**: `Stuhlmuller/homelab` and its declared GitHub configuration in `Stuhlmuller/github-iac`  
**Project Type**: Repository CI and GitHub configuration  
**Performance Goals**: Eliminate five-minute image automation runs and optional PR jobs while keeping seven required contexts available  
**Constraints**: Preserve fork isolation, exact-SHA dispatch, OIDC trust, credentials, permissions, concurrency, production gates, and full-container scan  
**Scale/Scope**: Homelab workflows and one `homelab-plan` environment rule only

## Constitution Check

The project constitution is an unfilled template. `AGENTS.md` is the operative repository policy. GitHub configuration is represented in github-iac; homelab workflow changes remain in Git. Existing branch and credential boundaries are retained. The user explicitly requested the plan reviewer removal, with the security implication recorded below. Recheck these conditions after implementation.

## Design

1. Obtain read-only current environment and ruleset settings before mutation. Repository source says ruleset `14700233`
   requires `policy-bot: main`, `Lint`, `repo`, `Analyze (python)`, `analyze-actions`, `release-dry-run`, and
   `Terragrunt Gate`. An authenticated operator read confirmed the `homelab-plan` reviewer, but GitHub denied its
   removal with `Must have admin rights to Repository`; that setting remains unchanged.
2. Keep PR triggers for all required context producers: Lint, validate, CodeQL, Release dry run, and Terragrunt Plan. Preserve the external `policy-bot: main` producer. Retain PR security/static checks rather than deadlocking protected merges.
3. Review optional PR triggers in NOFX Images, OpenClaw native config, and Image automation. Remove only their PR events. Preserve their matching main push events; add a guarded main push to Image automation if its verification should run on merge. Keep existing manual dispatch for NOFX and Image automation; add manual dispatch to OpenClaw only if an actual operator use case requires it.
4. Remove the five-minute Image automation schedule and document that its `observe` alert no longer runs automatically. Keep the weekly CodeQL schedule because it is a low-frequency security scan; review its value separately if cost remains a concern.
5. Once repository admin access is available, remove only the `homelab-plan` required reviewer list in `Stuhlmuller/github-iac/Stuhlmuller/repositories/terragrunt.hcl`. Preserve the environment, secrets, OIDC subject, and `homelab-production` rules. Inspect module semantics and plan to confirm the reviewer rule is removed. Apply GitHub desired state through its declared code path.
6. Update homelab CI runbook and source-linked OpenWiki CI note to explain event selection, reviewer behavior, lost five-minute observation, and rollback.
7. Verify exact required contexts on a representative PR and main push/manual jobs after the coordinated rollout. Do not remove a required context from the ruleset to hide missing automation.

## Security Consideration

Current `homelab-plan` live plan checks out same-repository PR code before using AWS/OIDC and Octelium inputs. Removing
its reviewer allows such code to reach credentials unattended. Before applying the environment change, confirm the
workflow's static gate, same-repository condition, plan identity permissions, and secret-output controls still match the
repo policy. The user authorized this specific tradeoff; no broader approval gate removal is included.

## Project Structure

```text
specs/003-actions-cost-control/       # planning artifacts
.github/workflows/                 # homelab trigger owners
docs/ci-cd.md                     # operator runbook
openwiki/runbooks/ci-cd.md         # source-linked summary
../github-iac/Stuhlmuller/repositories/terragrunt.hcl
```

**Structure Decision**: GitHub environments and rulesets stay in github-iac; workflow events stay in homelab. This plan introduces no new runtime component.

## Rollout and Rollback

Land trigger changes while preserving all seven required PR context producers. Reconcile github-iac environment desired
state through its protected workflow; inspect resulting settings and one trusted plan job for removal of the waiting
state. Revert the exact workflow and HCL commits to restore former triggers/reviewer if required contexts or credential
boundaries fail acceptance. No live cluster rollout is involved.
