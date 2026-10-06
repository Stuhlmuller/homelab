# HOME-30 evidence packet v3

HOME-45's assessment decision is incorporated; refreshed QA and independent
Auditor review remain pending. No control, residual risk or merge gate is
accepted by this packet. This is internal TSC design-assessment evidence, not
a CPA examination, SOC 2 report, certification or operating-effectiveness claim.

| Field | Value |
| --- | --- |
| Issue / control / preliminary mapping | HOME-30; SCOPE-01; CC2.1, CC3.1–CC3.2, CC8.1, subject to HOME-37 mapping |
| PR | [PR #1154](https://github.com/Stuhlmuller/homelab/pull/1154), open, no close intent |
| Selected main | `27e058b5836c2f87f7b8f8ce4700893a559cf3e2` |
| Selected integration revision | `e2aa3e6b7d41bc93df65b6c5f459cc5f81596058` (main plus HOME-30 implementation) |
| Previous main comparison | `b56d8febca2c2eeae03de374b574289502b4feaa` |
| Collector | SOC 2 Security Evidence Engineer, `01e5e4fd-3ecb-48f5-beda-66bd765e474b` |
| Collection and publication-review UTC | Exact timestamps in `validation.json` and `publication-review.json`, 2026-10-04 |
| Period/environment | Isolated repository checkout at recorded revisions; no live collection or operating observation period |
| Version | HOME-30-v3 supersedes v2 for this integrated source baseline; v1/v2 remain historical evidence |

## Decision and five conditions

The [incorporated decision](../../HOME-45-decision.md) records D1–D7 and manual
boundary dispositions, limitations, eight open finding groups and delegated
owners. `HOME-45-original.txt` preserves the attached decision byte for byte;
`decision-provenance.json` records its SHA-256, HOME-45 identity, HOME-29 comment
and attachment IDs, decision-maker role/agent, UTC time and reviewed revisions.
The decision was made by Homelab Decision Review Lead at 02:12:44 UTC on
2026-10-04. Approval applies to assessment approach, not control effectiveness.

| Condition | Incorporation and remaining gate |
| --- | --- |
| 1 provenance | Original decision preserved; scope and decision summary incorporated; historical packet hashes unchanged |
| 2 integration | Whole-tree register covers main plus HOME-30, with identities/modes, both full diff sets, review lanes and open findings; final packet additions separately reconciled below |
| 3 name review | Complete emitted path/name lists manually reviewed before publication; record and digest in `publication-review.json`; required available secret checks run, full local scanning unavailable |
| 4 drift/independence | QA then Auditor must review the final immutable handoff; actual target main must be compared again at any separately authorized merge boundary; ordinary drift refreshes evidence, material scope changes require a decision |
| 5 HOME-36/stages | CSO revised HOME-36 at 2026-10-04T02:15:46Z to a design evidence program; verified through its issue record, still backlog; later operating work needs explicit period/population/sampling approval and collection authorization |

HOME-45 stays open for CSO verification of incorporation and acceptance/merge
gates. HOME-30 stays open; HOME-29 remains in progress; later stages remain in
backlog. No stage promotion or new scope approval is requested for ordinary drift.

## Complete source reconciliation

`whole-tree.json` accounts for all **777** entries at the integration revision:
**520** entries under the collector's six roots and **257** manual entries.
`inventory.json` independently summarizes those 520 entries into 49 groups and
41 literal registrations. These are source counts, not deployed objects/users.

The main diff accounts for 30 paths: 20 additions and 10 modifications, including
an executable-mode change. The HOME-30 diff against selected main accounts for
25 paths: 24 additions and one modification. There are no actual renames or
deletions in either interval. The collector records old/new identities, modes,
paths and statuses and supports renames/deletions; synthetic tests exercise all
four change types. All paths are included, including scripts, docs, top-level
control configuration, agent instructions and HOME-30 artifacts.

The final evidence commit adds only files under this v3 directory. SHA256SUMS
enumerates their paths and SHA-256 values plus changed HOME-30 artifacts. The
verifier requires every integration path/mode/object to remain unchanged and
every final added path to appear in SHA256SUMS, except SHA256SUMS itself. It
checks exact final-tree closure: no undeclared additions, deletions or changes.
The immutable handoff and manifest digest bind the final manifest without a
self-referential hash. All final packet additions are manual review sources.

### Review dispositions and unresolved findings

| Source group | Completed review by SOC 2 Security Evidence Engineer | Named next reviewer / open findings |
| --- | --- | --- |
| Fleet/Entra IaC modules, catalog/stack, lockfiles | Reviewed module/runbook contracts: separate console SAML and cloud-only pilot user; sensitive state/output and certificate lifecycle limitations retained | Homelab QA & Release Engineer reproduces; CSO assigns HOME-40/41/42 owners; F6 effective identities, SAML callback, certificate/recovery and deployment population remain open |
| Apple profiles and Fleet scripts/tests | Reviewed declared profile/delivery boundaries; 37 setup and 17 synthetic API tests pass; no real device/profile/credential action | HOME-40/44 owners via CSO; F4 consent/purposes/retention and F6 enrollment, password sync, offline/FileVault behavior remain open |
| Manual delivery/toolchain sources | Accounted for every path and mode; reviewed Azure credential-diff gate changes and new Fleet test registration | Homelab QA & Release Engineer, then HOME-42 owner via CSO; F8 full local toolchain and final-head CI/signing/protection review remain open |
| Scope, HOME-45, HOME-30 code and evidence | Incorporated decision, reviewed history, names, whole-tree coverage and synthetic change tests | Homelab QA & Release Engineer then Third Party Auditor; F1 commitments, F7 final owner/mapping and independent acceptance remain open |
| Other retained manual sources and unchanged baseline | Complete source-accounting/name review only; no claim of new line-by-line substantive audit | Homelab CSO accountable for assignment to HOME-31/33/34/37/40/41/42/43/44; F1–F7 remain open as applicable |

F1–F8 are defined with required follow-up in the incorporated decision. Assigning
a path to a reviewer does not resolve it. QA and Auditor have not reviewed v3;
no independent acceptance is implied. Supplier internals are outside direct
implementation, while interfaces, exchanged data and failure effects remain in
assessment scope. External chart expansion and live populations need separate
authorized evidence.

The open-PR snapshot includes Fleet SAML follow-up #1155 touching the SAML
module, Fleet runbook and validation note. It is outside the selected main;
its existence reinforces F6 rather than changing this baseline silently.
Wazuh, recovery and containment proposals likewise retain their separate gates.
These pending paths do not overlap the HOME-30 edits, apart from previously
recorded shared knowledge-base navigation in other documentation proposals.

## Publication and historical integrity

The implementer reviewed all 777 path names, diff endpoint names, component paths,
registration names, PR titles and final packet filenames. No apparent secrets,
personal records or private-only hostnames were found in emitted names. Source
values are omitted by collectors; names remain verbatim, not sanitized. Bounded
marker checks supplement manual review but are not full secret scanning. No real
personal data, credentials, raw certificates, backups or recovery material was
collected. Unsafe outputs must be withheld and remediated before publication.

No v1/v2 files were changed in v3. Their manifests are verified against original
heads `0771f1952f8026a7ad9f6e5e5f61752c0a54ae9d` and
`fb0f0296b409d9c21c4d3801beaf0a207aa9fdb1`, respectively. Those manifests describe
those revisions, not current scope files. The original HOME-45 bytes are hashed
separately; its instructions and historical approvals are not rewritten.

## Reproduction, validation and blockers

Exact command arrays, versions, UTC time and outputs are in `validation.json`.
From the final handoff revision, using Python 3.13.15 and Git 2.39.5:

```sh
python3 scripts/soc2-whole-tree.py --previous-main b56d8febca2c2eeae03de374b574289502b4feaa --selected-main 27e058b5836c2f87f7b8f8ce4700893a559cf3e2 --revision e2aa3e6b7d41bc93df65b6c5f459cc5f81596058 --check docs/compliance/soc2/evidence/HOME-30-v3/whole-tree.json
python3 scripts/soc2-scope-inventory.py --revision HEAD --check docs/compliance/soc2/evidence/HOME-30-v3/inventory.json
python3 -I scripts/ci/soc2-whole-tree-test.py
python3 -I scripts/ci/soc2-scope-inventory-test.py
python3 -I scripts/ci/fleet-free-setup-test.py
python3 -I scripts/ci/fleet-apple-csr-test.py
python3 docs/compliance/soc2/evidence/HOME-30-v3/verify.py
sha256sum -c docs/compliance/soc2/evidence/HOME-30-v3/SHA256SUMS
bash scripts/ci/secret-scan.sh --artifacts-only
git diff --check 27e058b5836c2f87f7b8f8ce4700893a559cf3e2 HEAD
```

Local checks include all three collector test methods (positive and negative
cases), 54 synthetic Fleet tests, inventory/whole-tree reproduction, compilation,
Ruff 0.15.17, Markdownlint CLI 0.45.0 with Node 22.22.2 and unchanged pinned
Super-Linter rules from v2, JSON/Markdown checks, artifact-only scan and hashes.
The expected invalid-revision diagnostic is a passing negative test.

The prior v2 Nix-download blocker has historical resolution: QA reported v2
lint/validate passing, and a read-only commit snapshot also shows its Terragrunt
Plan succeeded. One snapshot for the integration revision shows
[Lint](https://github.com/Stuhlmuller/homelab/actions/runs/37170823083),
[validate](https://github.com/Stuhlmuller/homelab/actions/runs/37170823060),
CodeQL and Release successful; Terragrunt Plan was still running.
`ci-snapshot.json` preserves this bounded result. This is not final-packet CI
evidence; external CI is not polled or awaited and no final-head pass is asserted.

Local Nix, Terragrunt, ripgrep, Gitleaks, OpenTofu, Helm, Kustomize, kubectl and
Conftest remain unavailable. Full local static/policy/rendering and complete
secret scanning remain unverified; artifact-only scanning is not a substitute.
Independent v3 QA/Auditor acceptance, final-head CI and signing/protection gates
remain open and unwaived. Current-main movement after this selected snapshot
requires recorded reconciliation at the merge boundary, not an endless scope
approval loop.

No live enforcement, device enrollment, operational recovery or effectiveness
is claimed. Rollout requires a separately authorized merge of HOME-30 artifacts;
this work changed no runtime desired state beyond integrating already-merged
main. Rollback is a reviewed documentation/tooling revert or superseding decision
that retains historical evidence. No live mutation, credential rotation,
permission change, data deletion or control closure occurred.
