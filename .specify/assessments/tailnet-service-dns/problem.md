# Problem Definition: Private service names on the tailnet

- **Slug**: tailnet-service-dns
- **Created**: 2026-10-18
- **Inputs used**: `intake.md`, `research.md`

## Problem Statement

The homelab owner wants all 27 currently declared private `stinkyboi.com` names to receive tailnet-only DNS answers, with automatic registration and the familiar HTTPS access path. The repository declares public DNS answers for those names; whether that cutover is live remains unverified. [source: `intake.md`, `research.md`, `decision.md` (owner clarifications)]

## Affected Users & Stakeholders

- **Users**: Homelab owner as a tailnet client — wants private DNS answers for approved service names and access to the intended application. [source: `intake.md`, `decision.md` (owner clarification)]
- **Stakeholders**: Homelab owner as operator and decision maker — owns the current name inventory and access boundaries. [source: `intake.md`, `research.md`]
- [NEEDS CLARIFICATION: Are there other tailnet users or service owners affected?]

## Goals

- Tailnet clients receive private answers for approved application names and reach the intended service. [source: `intake.md`, `decision.md` (owner clarification)]
- Keep approved names aligned with Kubernetes service changes without manual DNS record registration. [source: `intake.md`, `decision.md` (owner clarification)]
- Retire public A/AAAA/CNAME answers for the 27 private names after verified private cutover; private names fail closed if the resolver is unavailable. [source: `decision.md` (owner clarification)]
- Preserve current HTTPS access and the protections on private apps, public callbacks, and Harbor pulls. [source: `research.md`]

## Non-Goals

- Make currently private applications public. [source: `research.md`]
- Weaken existing route restrictions or application authentication to simplify name resolution. [source: `research.md`]
- Change unrelated cluster-internal service discovery. [source: `research.md`]

## Success Metrics

- Share of approved names that receive the intended private answer from a normal tailnet client and reach the intended application: target 100%; baseline unknown beyond 27 declared DNS entries. [source: `intake.md`, `research.md`, `decision.md` (owner clarification)]
- Public A/AAAA/CNAME answers remaining for the 27 private names after verified cutover and cache expiry: target zero; live baseline unknown. [source: `decision.md` (owner clarification), `research.md`]
- Manual DNS record changes per approved name added, changed, or removed: target zero; baseline is one fixed repository inventory, while actual operator time is unknown. [source: `intake.md`, `research.md`]
- Regressions in existing HTTPS URLs, route restrictions, public callback paths, or Harbor image pulls: target zero; live baseline not established in this assessment. [source: `research.md`]

## Cost of Inaction

The declared workflow remains: private app names use public DNS-only records and a fixed inventory, with separate application routes. Existing access boundaries stay in place. The public DNS cutover's live status and maintenance cost have not been verified. [source: `research.md`]

## Open Questions

- [NEEDS CLARIFICATION: Which services may become tailnet-visible, and who approves them?]
- [NEEDS CLARIFICATION: How should tailnet clients resolve public or unrelated `stinkyboi.com` names?]
- [NEEDS CLARIFICATION: What recovery time and resolver redundancy are required when private names fail closed?]
- [NEEDS CLARIFICATION: What is the live DNS baseline and cutover state?]
