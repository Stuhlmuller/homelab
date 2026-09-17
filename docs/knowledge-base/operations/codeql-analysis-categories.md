# CodeQL Analysis Categories

Tags: #operations #validation #security

Observed on 2026-09-06 while reviewing PR #991 at
`5ec49b6dd82a60e540c338b2d4dc538c5a66a231`: current Actions analysis completed,
but the CodeQL aggregate could not compare introduced alerts because main
retains an obsolete analysis configuration. This predates the image build
and native fixtures; PR #991 does not change `codeql.yml`.

| Configuration | `analysis_key` | `category` |
| --- | --- | --- |
| Current | `.github/workflows/codeql.yml:analyze-actions` | `.github/workflows/codeql.yml:analyze-actions` |
| Legacy | `.github/workflows/codeql.yml:analyze` | `/language:actions` |

[PR #552](https://github.com/Stuhlmuller/homelab/pull/552), commit
[`988ad9be`](https://github.com/Stuhlmuller/homelab/commit/988ad9be62ad391be2d66b115c6762755ff1200b),
renamed the job and removed its explicit category in July. Main still retains
legacy [analysis 1490343985](https://api.github.com/repos/Stuhlmuller/homelab/code-scanning/analyses/1490343985),
dated 2026-07-17.

The current [Actions job](https://github.com/Stuhlmuller/homelab/actions/runs/34065163215/job/101572528093)
uploaded `actions.sarif` at 22:50:35 UTC; processing completed at 22:50:40.
[PR analysis 1732947711](https://api.github.com/repos/Stuhlmuller/homelab/code-scanning/analyses/1732947711)
has no analysis error or warning and uses the current category. Its merge
commit `8b4bf77c7db5b3b034deffd3231f81d11761833f` has parents `da4ad5d9`
(main) and `5ec49b6` (PR head). Main's
[analysis 1732620547](https://api.github.com/repos/Stuhlmuller/homelab/code-scanning/analyses/1732620547)
uses the same current category.

Despite that completed upload, [aggregate check 101572578608](https://github.com/Stuhlmuller/homelab/runs/101572578608)
remains neutral for missing `/language:actions`. The identical warning appears
on PR #991's earlier `4f76e3b817` and `77bc021f22` heads and on
[PR #990's check 101559788519](https://github.com/Stuhlmuller/homelab/runs/101559788519).
Current Actions scanning ran; introduced-alert comparison remains incomplete.
Neither the neutral aggregate nor a successful upload proves all coverage or
an absence of findings.

## Follow-up

Investigate a repository-owned, guarded retirement path for the obsolete
configuration. Its read-only preview must identify exact refs, analysis keys,
categories, affected analysis IDs, and the consequences for retained history.
Require explicit approval before any history deletion, preserve the active
configuration, then verify fresh main and PR analyses produce a complete
introduced-alert comparison. No workflow or remote configuration change is
part of this finding.

Related: [[validation-gates]], [[gluetun-image-build]].
