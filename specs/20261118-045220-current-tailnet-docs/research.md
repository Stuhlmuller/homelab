# Documentation Research

## Current baseline

Decision: use fetched current main `0f4f806262d9d2cf0ab1296334e4d907a2ce5f3f`, including AdGuard documentation and its specification package.
Rationale: current main contains additional enrollment guidance that must be consistent with the user-provided setup.
Alternative rejected: limiting review to the first four cited documents would leave the scope incomplete.

## Operational accuracy

Decision: retain operational recipes only when owning source supports the documented behavior.
Rationale: documentation-only work must not claim new executable capabilities.
Alternative rejected: inventing replacement CLI invocations.

## Document ownership

Decision: keep only relevant current enrollment guides and repair their inbound links. Revise authored wiki pages directly under repository AGENTS policy.
Rationale: readers need coherent current guidance, while generated wiki state remains separately owned.
Alternative rejected: historical stubs or manual changes to generated Claims and provenance.

## Workflow sources

Inspected local Spec Kit 0.15.1 specify, clarify and plan skills, active templates, constitution, extension settings and resolver behavior. The coordinator read the saved homelab
workflow reference and the complete official `spec-driven.md`, quickstart and agentic SDD reference at upstream `a227e38315cd38172b04f2fb8f06ce8b69b38331`. Full upstream
command-definition coverage was not performed; installed local skills govern invocation.
