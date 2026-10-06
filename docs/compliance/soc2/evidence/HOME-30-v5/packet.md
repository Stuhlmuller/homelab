# HOME-30 packet v5 — historical completeness repair, HOLD

[PR #1154](https://github.com/Stuhlmuller/homelab/pull/1154) addresses
[P2 4175951204](https://github.com/Stuhlmuller/homelab/pull/1154#discussion_r4175951204).
V4 validated supplied history entries but allowed an empty or substituted set
after regeneration. V5 requires exactly the unique v1–v3 versions and pins each
original revision, root tree, manifest path and manifest SHA-256 in verifier
source before traversing archived objects. These constants are independent of
the regenerated envelope and were compared with the original Git commits.
This is an implementer disposition; explicit QA and Auditor disposition remains
required. V4 acceptance does not extend to this revision.

## Scope and provenance

Control SCOPE-01; preliminary CC2.1, CC3.1–CC3.2 and CC8.1 mapping remains subject
to HOME-37. Internal revision-bound design preparation only; no operating period,
real-record sample, control effectiveness, CPA examination or certification claim.
Collector: SOC 2 Security Evidence Engineer, `01e5e4fd-3ecb-48f5-beda-66bd765e474b`.
UTC and exact commands/results/tool versions: validation.json.

Original source S: `ff43156fec0d762a147876a3b69af445f7b5ed99`.
Selected target B: `2be233ffce44495ab63e5c1b3d349eeb795c28b6`.
Original tree: `9c7d2acd1bf8ddd1a8f212ea8aec8322e2b113c1`.
Fresh main fetch confirmed B unchanged; no Fleet/Entra or runtime-source changes.
The handoff supplies repaired S2 and exact T2, the S..S2 patch and B..S2 diff.
These are review bindings, not authorization for a signed replacement.

All v1–v4 evidence directory bytes remain unchanged. V5 history.json is an exact
copy of v4's 71-object archive; its three original bindings remain pinned rather
than inferred from its own packet list. review.json preserves the original v4
bytes of changed source files as base64 with Git identities and SHA-256 values.
Historical bytes are evidence, not today's executable contract. Archived root
associations remain collector statements independently reviewable against
original Git; no signature or independent attestation is claimed.

population.json records every tracked non-envelope source; exactly seven v5
paths complete the tree. SHA256SUMS binds six envelope files; HEAD binds the
manifest. Complete-tree identity checks remain in effect, including `.policy.yml`,
all delivery scripts, Fleet/Entra and HOME-30. The earlier six-root collector is
only a limited summary. Counts identify sources, not deployed objects or users.

HOME-45 D1–D7 and all five conditions are unchanged: original decision provenance,
complete integration, emitted-name review, independent/drift/merge gates and
HOME-36 design-only preparation. F1–F8 remain downstream; ordinary main drift
requires refreshed evidence, not repeated scope approval.

## Repair and validation

The verifier rejects missing packets, an empty archive, duplicate versions,
unexpected versions, substituted revision/root/manifest/digest bindings, a
coherent alternate packet mislabeled as v1, missing packet keys and empty
objects. No integrity check depends on Python assertions. Packet order alone
is not significant; a valid reordered set passes.

```sh
python3 scripts/soc2-evidence-verify.py
python3 -O scripts/soc2-evidence-verify.py
python3 scripts/ci/soc2-history-test.py
python3 -O scripts/ci/soc2-history-test.py
python3 scripts/ci/soc2-evidence-test.py
python3 -O scripts/ci/soc2-evidence-test.py
```

The new history fixture starts from a fresh synthetic squash clone and exercises
13 negative histories plus a reordered positive. For every case it runs the
actual index regeneration command, stages and commits the resulting envelope,
then checks the main verifier and v3 compatibility entrypoint under normal,
`-O` and `PYTHONOPTIMIZE=1` modes. Rejection must report the historical-contract
failure, not an unrelated checksum failure. Existing fresh-clone source/evidence
corruption and committed-policy-drift checks remain required.

Synthetic commits exist only inside local fixtures; they do not prepare or
publish the selected signed replacement. Available results and limitations are
recorded in validation.json. Nix, Terragrunt, OpenTofu, Helm, Kustomize, kubectl,
Conftest, ripgrep and Gitleaks remain unavailable locally. Full infrastructure,
policy, rendering and complete secret checks remain unwaived. Artifact-only
scanning is limited. Prior CI success is not a repaired-head CI result; a
skipped plan is not execution evidence.

## Review, publication and authorization boundaries

The implementer reviewed new emitted filenames, fixed original bindings,
reconciliation paths and copied historical source bytes. Names remain verbatim;
source-value omission is not emitted-name sanitization. No credentials, personal
records, private keys, backup contents or recovery material were collected.
No full secret-scanner pass is claimed.

Homelab QA & Release Engineer must reproduce the new committed-history fixtures,
whole-tree reconciliation and exact S2/B/T2. Third Party Auditor must explicitly
dispose the P2 repair and bind a verdict to S2. Existing P1 thread dispositions
and qualifying policy approval remain reviewer gates, not implementer approval.
CSO retains downstream F1–F8 ownership and stage coordination.

HOME-46 selected a replacement signed PR but authorized neither preparation nor
merge. HOME-47 reports no verified eligible signer, classic-protection 403 and
incomplete effective-protection confirmation. Operations Decision Lead retains
those read-only prerequisites. Return repaired candidate plus verified actor
and protection evidence to Decision Review Lead for concrete preparation
permission. Final merge permission is a separate immutable-head/target decision.
Shared-account author approval, history rewriting, permission changes, direct
main pushes and bypass are excluded. No replacement was prepared or published.

HOLD remains: HOME-30/HOME-45 open, HOME-29 in progress, later stages backlog.
Rollout is only the authorized update to existing PR #1154 for review. Rollback
requires a reviewed superseding tooling change that retains historical records;
never reset shared history or alter unrelated main/runtime sources. No merge,
live action, self-approval, risk exception or control closure occurred.
