# Specify checkpoint

Stage: specify complete, 2026-11-15. Next: clarify in a separate goal turn.
Owner: current AdGuard homelab goal. Issue: https://github.com/Stuhlmuller/homelab/issues/1842
Notion: https://app.notion.com/p/419e535fc62881a394d0e752ab2a4264

Canonical feature: specs/20261115-185603-adguard-tailnet-dns
Worktree: /workspace/homelab-adguard; branch feat/adguard-tailnet-dns.
Baseline: 6a7a2b8d. Active feature selected only in this worktree.

Invoked installed speckit-specify skill by executing its complete instructions:
read hooks (empty), resolve template through installed Python common resolver,
copy resolved template, persist feature selection, author behavioral spec,
evaluate built-in quality checklist, inspect post-hooks (empty).
Resolved template: .specify/templates/spec-template.md. No contributing preset
or override selected. Installed version 0.15.1 uses file priority resolution;
newer upstream composition behavior is not installed and was not backported.
Local skill prohibits environment-based feature selection; honored.

Read complete upstream methodology, quickstart, agentic SDD reference, and
specify command at github/spec-kit a227e38315cd38172b04f2fb8f06ce8b69b38331.
Raw files retained under /workspace/adguard-progress/upstream. Output truncation
in the first combined read was resolved with a second read covering the missing
methodology remainder and both guide/reference documents. The methodology's
historical automatic-branch and sample constitution examples are not governing:
installed feature state, current command, and homelab constitution 1.0.0 govern.
No claim to reading every upstream document or command.

Specification: four user stories, 19 functional requirements, six success
criteria. Built-in requirements checklist 16/16 passing. Assumptions explicitly
cover AdGuard Home, domain-level filtering, global tailnet scope, one initial
service, no per-client query history, and existing enrollment/delivery controls.
Private routing, MagicDNS, both DNS transports, exit-node applicability,
private authenticated administration, verified-before-cutover ordering, client
acceptance, and rollback are covered. No essential user decision identified.

Runtime access, actual endpoint identity/address, images, persistent storage,
and enrollment/signing remain to be investigated during clarification/planning.
They are unverified dependencies, not proof of a blocker or successful rollout.
No implementation, DNS policy mutation, merge, or deployment performed.
