# Clarify checkpoint

Stage: clarification complete, 2026-11-15. Next separate stage: speckit-plan.
Canonical feature: specs/20261115-185603-adguard-tailnet-dns.
Owner/worktree: current AdGuard goal, /workspace/homelab-adguard.
Issue: https://github.com/Stuhlmuller/homelab/issues/1842

Executed installed speckit-clarify instructions. Prerequisite resolver ran once
with --json --paths-only and selected this feature. Its BRANCH field is derived
from feature identity; actual Git branch remains feat/adguard-tailnet-dns.
Before/after hook inventory is empty. Existing constitution 1.0.0 retained.
Upstream clarify command consulted at github/spec-kit revision
 a227e38315cd38172b04f2fb8f06ce8b69b38331; file retained in the local upstream
reference directory. Project clarification preference resolves routine decisions
from evidence, so zero user questions were asked and four agent decisions were
recorded explicitly as such.

## Decisions and evidence

1. Preserve split private DNS and MagicDNS; an IPv4 endpoint can answer A/AAAA.
   Evidence: tailscale-access/main.tf, tailnet-dns/README.md and
   scripts/tailnet-dns-check.py. Direct private queries to AdGuard must also
   preserve private resolution; design chooses the forwarding mechanism.
2. Durable configuration remains repository-owned; UI supports inspection.
   Evidence: AGENTS.md desired-state rules and constitution I/II. Isolated
   recovery must restore effective settings and usable credentials, consistent
   with docs/application-recovery.md; backup existence is not functional proof.
3. At least one real system-resolver client test is required with OS/version,
   exit-node mode and cache treatment recorded. Existing exit-node coverage
   remains conditional on available authorized access and never inferred from
   direct queries. Evidence: existing tailnet DNS runbook and user intent.
4. Direct acceptance queries have a three-second deadline and no hidden retries,
   matching scripts/tailnet-dns-check.py DNS parameters. This is a bounded
   acceptance test, not an invented uptime or performance SLO.

## Coverage

| Category | Status | Evidence/disposition |
| --- | --- | --- |
| Functional scope and behavior | Clear | US1–US4 and explicit non-goals |
| Domain and data model | Resolved | Durable desired state and credential custody clarified |
| Interaction and UX | Resolved | Authenticated inspection and normal-client test clarified |
| Non-functional quality | Resolved | Bounded queries, privacy and recovery behavior |
| Integration and dependencies | Resolved | Private routing, address families, client behavior |
| Edge cases and failures | Clear | Failure/update/cache/trust and no-bypass behavior |
| Constraints and tradeoffs | Clear | Single service; existing delivery and trust controls |
| Terminology and consistency | Clear | AdGuard Home, endpoint versus query record type |
| Completion signals | Resolved | Direct checks versus actual client acceptance |
| Miscellaneous/placeholders | Clear | No unresolved placeholders |

No outstanding behavioral decision requires user input. Implementation method,
image selection, storage arrangement, secret provisioning, signer integration,
upstream/filter selection and delivery mechanics belong to planning.

## Verification and remaining limits

Sections changed: status, Clarifications, Functional Requirements, Key Entities,
Success Criteria. Four stories, 19 FRs and six SCs preserved.
Built-in requirements checklist re-evaluated: 16/16 -> 16/16; no newly passing,
regressed or unchecked items. Checklist bytes preserved as required.
Structure, unique identifiers, links, whitespace and preserved checklist hash
validated. No deployment or runtime tests performed in this requirements stage.

Read-only source finding: scripts/tailscale-ingress-sign.py signs fixed targets
and requires an existing trusted Mac signer. The Codex webhook signer permits
only its constrained ephemeral Codex class, not arbitrary workload proxies.
Planning must preserve that boundary and establish an authorized signing path;
no trust change, signer reuse, enrollment, or live API action was attempted.

The full Notion spec copy remains rejected by automatic approval review; no
retry or alternate-route copy was attempted. Existing local artifacts and concise
tracking remain usable. This does not block independent engineering. No goal-wide
blocker; zero consecutive turns without meaningful progress.
