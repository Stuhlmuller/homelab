<!-- markdownlint-disable MD013 -->
# Renovate dry-run parity receipt

**Gate: OPEN.** The hourly cluster runner remains in full dry-run mode; the
companion GitHub Action remains the sole writer. This receipt records public
aggregates only. Restricted Job logs and private repository/package identities
stay out of Git and PR output.

| Check | Evidence through 2026-10-19 20:20 UTC | Result |
| --- | --- | --- |
| Owner and App scope | The [baseline inventory](../../clusters/homelab/apps/renovate/README.md) found 18 owned repositories: eight eligible, ten archived, four private among the eligible, and no forks. The App installation selects all repositories. The last legacy App-token run scanned eight of eight; the 18:00 cluster Job also finished eight of eight. Direct installation-token repository enumeration is unavailable to the operator. | Pass for the observed inventory; first real owner transition remains a later check. |
| App grants | The existing App has the listed repository and organization grants, except repository Administration read. [PR #1453](https://github.com/Stuhlmuller/homelab/pull/1453) records the narrow exception and the first write-enabled verification requirement. | Accepted exception; do not infer private branch-protection settings. |
| Discovery changes | The pinned Renovate 44.167.4 fixture ran its actual discovery/config-resolution path against owner/App inventories A, A plus config-free B, then A. It scanned B only while owned and did not create an onboarding proposal. | Pass locally on 2026-10-19. |
| Scheduled repository outcomes | [PR #1391](https://github.com/Stuhlmuller/homelab/pull/1391) enabled the hourly full dry run. Job `renovate-29873880` ran 18:00–18:18:32 UTC and succeeded: eight repository starts and finishes, ten archived skips, four config-free repositories, 31 existing PR identities, six would-update and zero would-create outcomes, 131 dry-run markers, and no errors. Its Pod UID was `ba9e801b-f220-4729-a785-406e99dce457`. | Pass for this scheduled cycle; no GitHub write. |
| Warm scheduled Pods | Jobs `renovate-29873940` and `renovate-29874000` succeeded at 19:20:02 and 20:19:24 UTC. Their distinct Pod UIDs were `38ab172e-92c8-45df-9e7c-35cf65375857` and `3725f908-f809-4420-b321-2c66c735f348`. Both used PVC `renovate-cache` and ConfigMap `renovate-config-75df2dgg8h`; each had one hit for the exact tracked public canary namespace and key, eight repository starts and finishes, 131 dry-run markers, and zero errors, lookup errors, or mutex timeouts. | Two consecutive same-key scheduled hits pass. |
| Proposal and merge policy | The [committed config](../../clusters/homelab/apps/renovate/config.js) retains the legacy shared presets, `:automergeAll`, and daily automerge schedule; repository overrides still apply. Existing PR identities remain under `rstuhlmuller-renovate[bot]`. The same App [auto-merged homelab #1407](https://github.com/Stuhlmuller/homelab/pull/1407) after required checks. | Config and historical App parity pass; verify the first new write-enabled outcome, including private policy. |
| Credential projection | Both declared SSM SecureStrings reached version 2 through the [protected transfer](https://github.com/Stuhlmuller/renovate/actions/runs/39196912858), and the temporary role was [retired](https://github.com/Stuhlmuller/homelab/pull/1415). `automation/renovate` ExternalSecret was `Ready=True` after its 19:01:19 UTC refresh. | Pass; no secret value read or published. |
| Registry and alerts | No registry authentication error surfaced in the 18:00 scan; this covers its observed dependencies only. The 17:00 Job failed on Docker datasource mutex waits; failed-Job and incomplete-cycle alerts fired, then cleared after the successful 18:00 cycle. | Recovery observed; hold cutover if the timeout recurs. Missing-cycle drill remains open under T045. |
| Persistent package cache | [PR #1389](https://github.com/Stuhlmuller/homelab/pull/1389) exposed the exact cache-hit marker in restricted logs. The 18:00 Pod used the older ConfigMap; both later consecutive scheduled Pods hit the same tracked datasource key on the retained PVC. | Pass for two-Pod reuse; T022 remains open for freshness. |
| Normal refresh | The protected companion workflow published [v0.0.1](https://github.com/Stuhlmuller/renovate/releases/tag/v0.0.1), then [v0.0.2](https://github.com/Stuhlmuller/renovate/releases/tag/v0.0.2) at 20:20:12 UTC through [run 39318404853](https://github.com/Stuhlmuller/renovate/actions/runs/39318404853), after both cache-hit Jobs. A later healthy scheduled scan must see v0.0.2 after normal refresh. | **OPEN** (T022, T041). |
| Cache fault and recovery | The read-only mount fault, alert timing, and next-hour recovery require the reviewed fault/recovery PRs after normal cache proof. The storage-full path has no NAS quota or PVC resize capability. | **OPEN** (T024, T042, T045); block writer cutover. |

The 17:00 mutex failure does not prove a storage or Harbor fault. Keep T029
unchecked until the later scheduled refresh, cache-fault recovery, and alert
gates have direct evidence. Follow the ordered cutover in
[quickstart.md](quickstart.md); do not remove full dry-run mode while any gate is
open.
