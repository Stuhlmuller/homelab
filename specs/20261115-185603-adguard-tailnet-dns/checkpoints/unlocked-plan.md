# Unlocked-tailnet planning checkpoint

- Stage: plan complete. Next: checklist generation and evidence-based review.
- Branch: fix/adguard-unlocked-tailnet; base 0f4f806262d9d2cf0ab1296334e4d907a2ce5f3f.
- setup_plan.py resolved existing feature and preserved its plan before amendment.
- Reconciled plan, research, data model, operator contract and quickstart.
- Research agent adguard_research inspected pinned official Tailscale source;
  coordinator checked PeerStatus and lock serializer. No XERJ available.
- Design: AdGuard-only mode-aware identity functions; shared signing unchanged;
  explicit Lock mode inside existing freshness/identity binding; no bypass flags.
- Locked CLI peer-schema compatibility limitation recorded, not treated as pass.
- Constitution pre/post checks pass. No hooks registered. git diff --check passes.
- No implementation or functional test claims. No live mutations or Notion writes.
- Next stages must create/review amendment checklist, append scoped tasks and
  analyze amended artifacts before implementing. Existing completed tasks retained.
