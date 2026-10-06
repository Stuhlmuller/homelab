# HOME-30 evidence packet v2

Submitted for independent QA, then D1–D7 delegated scope approval and Auditor
review. This is internal readiness evidence, not acceptance, a SOC 2 report or
operating-effectiveness proof. No merge or live execution is authorized.

| Field | Value |
| --- | --- |
| Control / preliminary criteria | SCOPE-01; CC2.1, CC3.1–CC3.2, CC8.1; final mapping belongs to HOME-37 |
| PR | [HOME-30, PR #1154](https://github.com/Stuhlmuller/homelab/pull/1154), no close intent |
| Immutable implementation | `0c45cee76f99661bf7c399933bca78d9140ed302` |
| Fresh main | `b56d8febca2c2eeae03de374b574289502b4feaa`, fetched 2026-10-04 at approximately 02:00:38 UTC |
| Collector | SOC 2 Security Evidence Engineer, agent `01e5e4fd-3ecb-48f5-beda-66bd765e474b` |
| Exact collection UTC | Recorded in `validation.json`; 2026-10-04 |
| Environment / period | Isolated repository checkout; revision-bound control design; no live collection or approved observation period |
| Version | HOME-30-v2 supersedes v1 for current scope, without replacing historical v1 evidence |

## QA findings and remediation

1. Corrected MD034 (bare URL) and MD018 (PR number at the start of a line) in
   the working copy of v1 `packet.md`. Only those two formatting changes were
   made there. The original bytes are retained in `v1-packet.original.txt`.
   Markdownlint now passes with the pinned Super-Linter rule configuration;
   no rule or path is disabled to conceal the errors.
2. Reconciled the nine main changes from `58ecf587d3069fb8e504ac319e2bec2de05785c0`
   to fresh main. Main's Harbor exporter, ServiceMonitor, network rules and
   Grafana alerts are now declared scope. `main-reconciliation.json` binds all
   nine files to SHA-256 hashes. Two added files increase the source population
   from 501 to 503; there remain 49 groups and 41 literal registrations. No
   assumption is made that these declarations have operated successfully.
3. Ran available focused checks, including actual Markdownlint, Ruff and the
   repository's artifact-only secret check. Full Nix/static/policy/rendering
   and secret gates remain blocked as detailed below. No failed gate is waived.

The revised [scope](../../scope.md) explicitly retains all sources outside the
collector in manual review: scripts, documentation, specifications, agent
instructions, toolchain/lock files, Renovate/release configuration, pre-commit,
policy-bot and scanner configuration, and remaining root files. D1–D7 must
approve this review boundary or require automated expansion. The
`excluded-sources.json` register enumerates all 230 excluded tracked paths at
main, with Git blob IDs. They are excluded from the six-root collector only,
not from the proposed system assessment.

The collector omits source values but emits component paths and registration
names verbatim. Tests now explicitly demonstrate both properties. They do not
demonstrate name sanitization. Names must be reviewed before publication; unsafe
names require holding the output privately and remediation, not an assertion
that public Git provenance makes them safe. Manual review of this packet's
emitted names and bounded marker checks found no secret values or personal
records. Full secret scanning remains unverified.

## Historical provenance

The authoritative v1 remains at immutable head
`0771f1952f8026a7ad9f6e5e5f61752c0a54ae9d`. Its original inventory, validation,
PR list and SHA256SUMS remain unchanged. Its working-copy packet has the two
lint corrections; original bytes are preserved alongside v2 and verified
against Git history. The v1 hash list describes the old revision, including
the old scope and collector, and is intentionally **not** rewritten to describe
v2. Run v1 reproduction at its original head, not against revised HEAD files.
`verify.py` reads all nine historical artifacts directly from that commit and
checks their original digests. V2 SHA256SUMS covers the revised current files.

## Changed artifacts and rationale

| Artifacts | Purpose |
| --- | --- |
| `docs/compliance/soc2/scope.md` | Updated main, population, excluded control sources, name-review boundary and Harbor/Grafana declarations |
| `scripts/soc2-scope-inventory.py` | Removes approval-implying wording from a successful comparison |
| `scripts/ci/soc2-scope-inventory-test.py` | Explicit emitted-name versus omitted-value assertions |
| `docs/knowledge-base/operations/soc2-readiness.md` | Links the revised scope and historical limits |
| v1 `packet.md` | Two lint-only presentation corrections; original retained and historical hash list unchanged |
| v2 `inventory.json`, `excluded-sources.json`, `main-reconciliation.json` | Complete six-root population, complementary excluded-path register and all main-change hashes |
| v2 `open-prs.json` | Fresh open-PR title/URL snapshot; 29 including this PR, Harbor #1151 no longer open |
| v2 `verify.py`, `validation.json`, `markdown-lint.yml` | Reproduction of exclusions, source samples, history, exact commands and linter rules |
| v2 `v1-packet.original.txt`, `packet.md`, `SHA256SUMS` | Historical bytes, this review packet and regenerated artifact hashes |

Main was reconciled on the PR branch without changing main. Existing recovery,
containment, Wazuh and Fleet PRs remain proposals. The existing additive
knowledge-base home entry still overlaps other documentation PRs; preserve
both entries during future reconciliation. Fresh open-PR enumeration does not
establish runtime effectiveness or permanently conflict-free integration.

## Reproduction and results

`validation.json` records exact argument arrays, exit codes and output from the
implementation revision. Python 3.13.15, Git 2.39.5, Node 22.22.2,
markdownlint-cli 0.45.0 and Ruff 0.15.17 were used. The Markdown rules are copied
unchanged from [Super-Linter's pinned template](https://github.com/super-linter/super-linter/blob/4ce20838b8ab83717e78138c5b3a1407148e0918/TEMPLATES/.markdown-lint.yml).
They are evidence, not a new repository-wide lint override. Tool downloads
were isolated outside the checkout. Initial Node 22.14.0 installation raised a
transitive engine warning; validation used compatible Node 22.22.2 instead.

All recorded commands produced their expected result: inventory and historical
checks pass; the old v1 inventory correctly rejects fresh main with exit 1.
The two unittest methods cover positive comparison, deterministic collection,
modification/addition/deletion rejection, untracked-content exclusion, omitted
synthetic value, emitted names and invalid revision. The expected Git diagnostic
for the invalid revision is not a collection failure. Compilation, Ruff,
Markdownlint, whitespace and artifact-only checks pass.

At the final immutable handoff head, from the repository root:

```sh
python3 scripts/soc2-scope-inventory.py --revision HEAD --check docs/compliance/soc2/evidence/HOME-30-v2/inventory.json
python3 -I scripts/ci/soc2-scope-inventory-test.py
python3 docs/compliance/soc2/evidence/HOME-30-v2/verify.py
python3 -m py_compile scripts/soc2-scope-inventory.py scripts/ci/soc2-scope-inventory-test.py docs/compliance/soc2/evidence/HOME-30-v2/verify.py
ruff check scripts/soc2-scope-inventory.py scripts/ci/soc2-scope-inventory-test.py docs/compliance/soc2/evidence/HOME-30-v2/verify.py
markdownlint --config docs/compliance/soc2/evidence/HOME-30-v2/markdown-lint.yml docs/compliance/soc2/scope.md docs/compliance/soc2/evidence/HOME-30-v1/packet.md docs/compliance/soc2/evidence/HOME-30-v2/packet.md docs/knowledge-base/operations/soc2-readiness.md docs/knowledge-base/00-home.md
bash scripts/ci/secret-scan.sh --artifacts-only
git diff --check b56d8febca2c2eeae03de374b574289502b4feaa HEAD
sha256sum -c docs/compliance/soc2/evidence/HOME-30-v2/SHA256SUMS
```

Install the stated tool versions in a disposable environment if unavailable.
The recorded `../.tools-v2`, `../.node-v2-runtime` and `../.lint-v2` prefixes are
the collector's tool layout, not delivered artifacts. Equivalent executables
with those versions may be used. Inventory/hash results must match; durations
and collection times need not. SHA256SUMS excludes itself; the issue handoff
binds its digest and final immutable head, avoiding a self-referential hash.

## Validation blockers and residual risk

The previous [validate run](https://github.com/Stuhlmuller/homelab/actions/runs/37169159642)
passed flake inspection but failed at HCL formatting because Nix cache downloads
returned HTTP 416 and transfer errors. Pydantic could not be substituted and
Checkov/Nix shell dependencies could not be realized. This was not evidence of
an HCL-format defect. Stack generation, HCL validation, rendering and secret
scanning were skipped. No success is inferred for those skipped gates.

Locally, Nix, Terragrunt, ripgrep, Gitleaks, OpenTofu, Helm, Kustomize, kubectl
and Conftest remain unavailable. Full static/policy/schema/rendering checks and
the complete repository secret scan were not run. The artifact-only check tests
saved plan/state leakage and is not a substitute for Gitleaks or the complete
scanner. New-head CI is externally triggered and not awaited; no pass is claimed.
Signing/protection requirements remain applicable before any authorized merge.

The source population is revision-bound, not rendered or live inventory.
External charts, provider internals, topology health, isolation enforcement,
restore coverage and operating period remain unproven. No secrets, personal
records, backup content or recovery material were collected. Residual risk is
not accepted by the implementer. D1–D7, actual user/contract commitments,
provider roster, purposes/retention and recovery objectives still need owners.

Rollout is limited to separately authorized review/merge of documentation and
collector changes. No runtime desired state was modified by this remediation;
the runtime diff came from already-merged main. Rollback is a reviewed revert
of HOME-30 changes retaining evidence history, with no live mutation or deletion.
QA reproduces first, CSO routes D1–D7 next, then Auditor reviews. HOME-30 remains
open, HOME-29 in progress, and later stages in backlog. CHANGES_REQUESTED
requires another versioned packet; the implementer cannot accept or close it.
