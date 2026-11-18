# Unlocked-tailnet clarification checkpoint

- Stage: clarify complete. Next: plan amendment and upstream/schema research.
- Feature selector resolved the existing AdGuard feature successfully.
- Questions asked: 0; owner already supplied the material Lock-mode correction.
- Agent-resolved boundaries recorded in spec Clarifications and FR-021.
- Evidence: adguard-check.verify compares snapshots before/after direct tests;
  adguard-dns-cutover.binding includes the peer object and validate_binding
  compares it to a fresh snapshot immediately before apply. Existing rollback
  explicitly does not require a healthy online AdGuard peer.
- Coverage: functional scope, identity/lifecycle, operator journey, security,
  dependencies, failure cases, constraints, terminology, completion and
  placeholders are clear for this amendment. No outstanding behavioral question.
- Technical schema details and reuse/separation of helper functions belong to
  planning, including actual Tailscale unlocked status/peer representation.
- Requirement checklist re-evaluated: 16/16 to 16/16, no marker changes,
  newly passing items, regressions or unchecked items.
- Extensions have no registered hooks. Constitution unchanged.
- No code or live changes; no functional acceptance claimed.
