# HOME-30 packet v6 — exact historical object closure, HOLD

[PR #1154](https://github.com/Stuhlmuller/homelab/pull/1154) repairs
[P2 4176031368](https://github.com/Stuhlmuller/homelab/pull/1154#discussion_r4176031368),
while retaining the repair for
[P2 4175951204](https://github.com/Stuhlmuller/homelab/pull/1154#discussion_r4175951204).
An intact v5 archive did not prove that its verifier rejected unrelated objects.
V6 tracks every root/intermediate tree and final blob reached by the fixed
historical manifest proofs, then requires exact set equality with supplied
archive objects. It rejects extra objects even when their Git hashes are valid.
It does not hardcode an object count or traverse unrelated tree-entry siblings.
Missing required objects fail explicitly; original packet bindings remain fixed.
Both P2 dispositions require refreshed independent QA and explicit Auditor review.

## Review bindings and evidence

Previous source S2: `e337c7a9798b2b652dfbf7f21f2fb3797bcb42e1`.
Selected target B: `2be233ffce44495ab63e5c1b3d349eeb795c28b6`.
Previous tree T2: `035a37127979a0df09fef670526e0630d4db0185`.
Fresh main fetch confirmed no drift. The external handoff records the exact
repaired source S3/tree T3 and supplies full S2..S3 and B..S3 patches, avoiding
self-referential evidence hashes. Only existing PR #1154 is updated for review.

Control SCOPE-01; preliminary CC2.1, CC3.1–CC3.2 and CC8.1 mapping remains subject
to HOME-37. Collector: SOC 2 Security Evidence Engineer,
`01e5e4fd-3ecb-48f5-beda-66bd765e474b`. UTC, commands, versions and results are
in validation.json. Scope is every tracked repository path at the review tuple,
not deployed objects or users. Internal point-in-time design preparation only;
no operating period, real-record sampling, effectiveness, CPA examination,
certification or attestation claim.

All v1–v5 evidence directory bytes remain unchanged. V6 history.json is byte-identical
to v5's original archive. review.json also preserves original changed S2 source
bytes, Git identities and SHA-256 values. The current verifier preserves the
fixed v1–v3 unique revision/root/manifest-path/digest contract. Root associations
are collector statements checked against original Git, not signed attestations.
The new set-equality guard proves exact proof-object membership, not merely
valid hashes or the presence of the right number of entries.

population.json records every non-envelope tracked path with mode, Git identity
and SHA-256. Exactly seven v6 envelope files complete the tree; SHA256SUMS binds
six and HEAD binds the manifest. Delivery/control sources, Fleet/Entra, HOME-30
and historical evidence stay included. No runtime source was changed.
HOME-45 D1–D7 and all five conditions remain unchanged. F1–F8 stay downstream;
ordinary drift requires evidence refresh rather than repeated scope approval.

## Reproduction and regression coverage

```sh
python3 scripts/soc2-evidence-verify.py
python3 -O scripts/soc2-evidence-verify.py
python3 scripts/ci/soc2-history-test.py
python3 -O scripts/ci/soc2-history-test.py
python3 scripts/ci/soc2-evidence-test.py
python3 -O scripts/ci/soc2-evidence-test.py
```

The history suite adapts QA's exact nonsecret extra-blob payload from attachment
`01a1050a-4a27-71d7-a323-94cadfb5be21` / HOME-29 comment
`35b52465-d2f7-4650-8737-2209e3c9172e`. It adds an unrelated valid tree, missing
root and blob cases, and a same-count replacement. It retains all 13 previous
historical-contract negatives, clean and reordered positives. All 20 cases
actually regenerate, stage and commit before checking the main, v2 and v3
entrypoints in normal Python, `-O` and `PYTHONOPTIMIZE=1`: 180 checks.
Negative diagnostics must identify historical-contract/object failures, not
unrelated dirty-envelope checks. Existing 39-check fresh-squash/source-corruption
suites remain required. Fixtures create local synthetic commits only, not a
signed replacement candidate or remote branch.

Available checks and exact output are in validation.json. Nix, Terragrunt,
OpenTofu, Helm, Kustomize, kubectl, Conftest, ripgrep and Gitleaks remain locally
unavailable; full infrastructure/render/policy and complete secret checks are
unwaived. Artifact-only scanning is limited. Prior CI success is not current-head
CI evidence; a skipped plan is not an executed plan.

## Review and authority boundaries

Implementer publication review covers changed names, paths, proof bindings and
copied historical source bytes. Names are verbatim, not automatically sanitized;
value omission and emitted-name review remain distinct. No credentials, private
keys, personal records, backup contents or recovery material were collected.
The new payload is explicitly synthetic and nonsecret.

Homelab QA & Release Engineer must reproduce exact object closure and all
regressions at S3/B/T3. Third Party Auditor must explicitly dispose both P2s
and bind a fresh verdict to S3. Prior acceptance does not transfer. Existing
P1/P2 reviewer dispositions, genuine policy approval and final required checks
remain separate gates; implementer results do not change review state.

HOME-47 remains parked for eligible signer/effective-protection evidence; no
repeat access probing occurred. HOME-46 preparation authorization needs that
evidence plus the reviewed candidate; final merge permission remains separate.
No signing, signed replacement preparation/publication, shared-account approval,
history rewrite, access/protection change, bypass, merge or live action occurred.
HOLD remains: HOME-30/HOME-45 open, HOME-29 in progress, later stages backlog.
Rollback is a reviewed superseding tooling change preserving historical evidence
and unrelated main changes. No shared-history reset or runtime rollback is needed.
