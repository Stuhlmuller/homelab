# Implementation increment 1 — image prerequisite

Scope: T001–T002, following the completed read-only analysis turn. Same feature,
branch `feat/adguard-tailnet-dns`, issue #1842 and existing Notion card.

## T001 baseline and readiness

Fetched main on 2026-11-15; HEAD and origin/main both
`6a7a2b8d48be8c0e27cfa17f9fc24748dcca9e24`. No restack needed. Existing changes
were only feature selection and this feature's untracked artifacts. Issue #1842
is open. No other checkout or branch was modified.

Requirements checklist: 16 checked, 0 open. Deployment-quality checklist:
24 checked, 0 open. Checklists remain reviewer-owned and unchanged.
Spec Kit 0.15.1 installed implementation skill and upstream implement command at
`github/spec-kit@a227e38315cd38172b04f2fb8f06ce8b69b38331` read. Hooks are empty.
Existing Git, Docker and Terraform ignores cover private/generated material;
no ignore changes needed for this inventory-only increment.

Read-only Kubernetes inspection: Harbor, external-secrets, tailscale,
tailnet-dns and platform-storage Synced/Healthy; nfs-default Retain exists.
Traefik remains Synced/Progressing, to be diagnosed at T033 before rollout.
Unrelated application drift was observed but is outside this increment.

Docker server 28.4.0 is available; kubectl and gh work. Default sandbox cannot
activate Nix because user namespaces are restricted. Escalated execution of the
reviewed default devShell was approved and is provisioning the pinned tools;
no flake or lockfile changes. Administrator access remains a later dependency.

No live mutation, image publication or deployment occurred. T002 verification
and results will be appended before this increment is complete.

## T002 completed

Skopeo 1.22.2 in the pinned default devShell anonymously retrieved the public
v0.107.80 raw index. SHA-256 matches the reviewed plan:
`e2e1b48c832f7705be915873f95de0d5114de573736441d7f2923a8a6293027c`.
The index contains Linux 386, amd64, arm/v6, arm/v7, arm64 and ppc64le plus
attestation descriptors. amd64 and arm64 child pins match research exactly.
Only that immutable upstream source was added to harbor-images.json; no
consumer manifest, workflow, scope inventory or other catalog entry changed.

Validation in the default devShell passed:

- Inventory helper: 131 output references. It reports three existing digest-only
  chart pins still require renders; no chart changed in this increment, and
  this output is not claimed as fresh full rendered/live inventory.
- Harbor coverage: 139 declared references covered; chart inventory and all
  fixed application scopes match.
- Existing Harbor image coverage regression check passed.
- git diff --check passed; flake.nix and flake.lock unchanged.

T001 and T002 marked complete; T003–T040 remain pending. No publication,
protected PR, merge, app deployment or DNS change has occurred. Next separate
turn: scoped speckit-converge for this increment, then T003 protected prerequisite
PR and exact-main publication. Existing all scope is required for this new image;
no adguard-specific publisher scope exists. Read protected delivery instructions
before creating the PR. Keep source consumers unmerged until full-pull evidence.

Tracking limitation: automatic approval review rejected even the concise Notion Next step update in this increment, citing unestablished destination ownership/payload authorization
for infrastructure status. No retry or alternate external delivery attempted. Local checkpoint remains canonical; leave Notion writes paused pending user authorization.
