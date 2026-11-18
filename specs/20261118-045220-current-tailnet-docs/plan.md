# Implementation Plan: Current Tailscale Enrollment Documentation

**Branch**: `docs/current-tailnet-enrollment` | **Date**: 2026-11-17 | **Spec**: [Specification](spec.md)

## Summary

Rewrite authored documentation around ordinary device authentication, tags, access policy, and reachability. Keep only relevant current guides and coherent links. Preserve unrelated operational and security guidance.

## Technical Context

- Format: Markdown and existing authored OpenWiki frontmatter.
- Dependencies: existing Python wiki checker, yq, Markdown lint, Git diff checks.
- Target: repository documentation, including earlier specification prose and local skills.
- Baseline: `3aaf6085` from fetched `origin/main`.
- Scope: approximately 44 initial matching authored documents; follow inbound references beyond initial matches.
- Constraint: documentation and feature records only; no runtime or generated wiki state changes.

## Constitution Check

Both pre-research and post-design checks pass: desired state and live infrastructure remain unchanged; no secrets are added; source-linked learner guidance is preserved; authored wiki pages remain within established ownership; executable checks remain authoritative. No exception is needed.

## Project Structure

- `docs/`: identity/CI, runtime isolation, and Harbor networking guidance.
- `clusters/homelab/apps/`: AdGuard, Tailscale, Traefik and enrollment documentation.
- `clusters/homelab/platform/`: DNS and storage documentation.
- `IaC/terragrunt-catalog/modules/tailscale-access/README.md`: supported provider, authentication and policy contract.
- `openwiki/`: ingress, CI/CD, identity, state, inventory, validation and source-map prose.
- `specs/`: earlier DNS and AdGuard packages remain coherent; irrelevant dedicated packages are deleted.
- This feature: `spec.md`, `plan.md`, `research.md`, `quickstart.md`, requirements checklist; task breakdown follows separately.

## Design

1. Keep only sections, documents and source-map entries relevant to the current setup; repair inbound links.
2. Rewrite mixed-purpose paragraphs to retain current authentication, private routing, DNS, persistent identity, and credential boundaries in a consistent current documentation model.
3. Review commands against owning source. Omit helper recipes outside the current documentation model; retain independently valid commands and tests only when they still verify the described scope.
4. Reconcile earlier authored specs and dated evidence with the current documentation model. Keep the result free of historical and migration prose.
5. Preserve generated wiki metadata, independent commit signatures, and webhook authentication. No public API, data model or runtime contract changes are introduced, so separate contracts and data-model artifacts are unnecessary.
6. Validate authored references and prose, inspect the entire diff, and give the delivery owner exact file and check evidence. Source incompatibilities remain outside this documentation change and are reported in the final handoff.

## Verification

Follow [validation guide](quickstart.md). Success requires only current enrollment prerequisites in authored documentation, no dangling links to removed guides/sections, coherent current setup prose, passing available wiki/format checks, and no executable or runtime changes.
