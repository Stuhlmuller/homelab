# NOFX agent competition

<!-- markdownlint-configure-file { "MD013": { "tables": false } } -->

Use Backtest Lab for an isolated historical round. Each run has its own virtual
account and AI cache. The live Competition page ranks exchange traders; it is
not the scoreboard for these simulations.

## One OKX account

The prepared cash-spot build (patch `0012`) lets the three personas reuse one
OKX US connection. Its ledger separates each trader's allocated quote cash, orders,
fills, fees, holdings, and returns. Other account holdings are not imported.
Multiple connections with the same authenticated OKX account UID share one
capital cap; extra API keys cannot multiply that cap.
The cap bounds outstanding buy reservations plus owned acquisition cost across
agents. Market appreciation can exceed it; the cap does not guarantee a maximum
loss. Agent cash and strategy entry limits also apply.

This feature has not been published, deployed, or activated by this source
change. Follow the [private-image rollout gates](nofx-private-images.md#harbor-runtime-acceptance)
using the exact tested source and reported private Harbor digests. Verify the
served source includes patches `0012`–`0014`, both workloads are ready,
all traders are stopped, and no simulation is active before configuring it in
the UI.

On **AI Traders**, open **Spot allocations** for the saved OKX connection.
Enter the quote currency, total capital limit, and explicit amounts for Trend,
Mean Reversion, and Breakout. No amount is prefilled. Allocations must fit the
cap and available quote cash; this form does not fund the account. Leave
Consensus unallocated unless the operator explicitly includes it. Saving
requires all affected traders stopped, including unverified OKX aliases.
Capital and allocations become immutable after the first persisted order
intent, preserving the competition baseline.

The OKX trader form displays **OKX US Cash Spot** and has no margin or Initial
Balance controls. Editing a trader does not set or reset its capital allocation.

Configure the three saved strategies with identical eligible static spot pairs,
risk limits, timeframes, and scan cadence, keeping their different personas.
Use the account-authenticated spot catalog and the saved quote currency; a public
listing does not establish account eligibility. Automatic borrowing must be
explicitly disabled. The adapter uses `tdMode=cash` only, accepts leverage 1,
and rejects shorts, derivatives, margin changes, and external Arena execution.
Keep every agent on provider OpenAI, base URL `https://openrouter.ai/api/v1`,
and model `openrouter/free`. The free router may choose different underlying
models; competition compares the saved personas, not fixed model identities.

Entries and explicit exits use limit IOC orders at the fresh quoted price,
rounded to the instrument tick without chasing prices. They may fill partly or
not at all. Every entry requires saved stop-loss and take-profit prices; native
OCO sell orders protect only that trader's owned quantity. Protective prices
align to exchange ticks before the bracket and reward/risk checks. Both legs
are limit orders, so a trigger does not guarantee a fill. Reconciliation verifies
terminal parent/child status and cumulative fills before releasing reservations.
Uncertain submissions keep funds reserved and prevent new orders.

While running, the existing one-minute monitor restores missing protection from
persisted entry intent. Dashboard reads never submit orders. Small residual dust
remains owned and may join that trader's next entry under its new saved stops.
A manual account sale or withdrawal that leaves the wallet below ledger ownership
makes balances unavailable and blocks execution; it does not reset allocations.

The Competition page ranks percentage returns from current marked equity
relative to the trader's original allocation, including actual fill fees and
rebates. Unavailable or stale data has no rank. Legacy whole-account equity
history is withheld for cash-spot
traders rather than relabeled as independent results. Live activation remains
an operator action after deployment and stopped-state acceptance.

Run exactly one backend execution process. Reconciliation and submission share
a process lock, while SQLite transactions reserve funds before HTTP. Additional
processes require a durable execution lease first. For rollback, stop traders
and simulations, review unresolved submissions and native protective orders,
and retain the PVC, allocation tables, intents, and fill history. Earlier images
cannot reconcile owned spot state; keep all OKX traders stopped on those images.

The deployed pre-`0012` adapter shares whole-account futures positions and P&L.
Its Initial Balance field is only a calculation baseline, not an allocation or
spending limit. Do not infer isolated competition from that earlier build.

## Configured live drafts

Trend, Mean Reversion, and Breakout are saved as stopped traders using the same
existing OKX connection and `openrouter/free`. Each has its own private,
inactive `Live - <persona>` strategy copied from the matching simulation
strategy. The copies retain their personas but remove historical-only and
historical strict-JSON-schema instructions.

Each draft is configured for 1x leverage caps, at most three positions, a 30%
margin target, a 60-minute scan interval, and hidden leaderboard visibility.
In the pre-`0012` futures runtime, that margin target is advisory prompt text.
The prepared spot executor enforces the saved utilization limit against owned
marked equity before entry. These draft settings alone still reserve no capital;
the explicit allocation form and shared cap are required after rollout.
The existing Consensus trader and `Sim - <persona>` strategies are unchanged.
Live activation remains a user action; no live orders were placed during setup.
Read-only persisted checks verified `is_running=0` and `show_in_competition=0`
for all three after using the trader cards' visibility toggles.

Keep the drafts stopped pending runtime verification. In the earlier
`25bceceb` runtime, `kernel/engine.go` validates a copied decision, so its live
leverage clamp does not persist. `store/trader.go` also defaults newly created
traders to visible despite an explicit false value; the card toggles corrected
the saved drafts. Configured 1x and a creation-form Hide selection alone therefore
do not prove enforcement or persisted visibility. Reviewed source
`05fcf60be529c063ae9f5fa16494466c3db0f400` includes patches
`0007-live-leverage-cap.patch` and `0008-trader-visibility.patch`, which fix those
shared code paths, with parser and SQLite regression checks in the backend build.
`0009-okx-leverage-failure.patch` reads current OKX cross-margin leverage,
skips writes when it already matches, and otherwise sends one instrument-level
request. Invalid lookup data or failed leverage requests stop openings before
canceling existing orders; mocked transport checks cover both directions. Previously,
leverage API errors were logged and trading continued.
The visibility migration removes the old column default while preserving saved
values; omitted API visibility still defaults to true. Follow the
[runtime acceptance checks](nofx-private-images.md#harbor-runtime-acceptance)
before relying on these fixes; `deployment.yaml` owns the desired image pair.
After restart, reload the UI and verify all three drafts remain stopped and
hidden. The legacy Arena `ExecuteConsensus` to `ExecuteDecision` path bypasses
the shared validator. Patch `0012` rejects that path for cash spot; these drafts
use their own saved strategies.

## Competitors and shared rules

| Competitor | Saved strategy | Approach |
| --- | --- | --- |
| Trend | Sim - Trend | Follow confirmed price and momentum trends |
| Mean Reversion | Sim - Mean Reversion | Trade weakening extremes within a bounded range |
| Breakout | Sim - Breakout | Trade confirmed range breaks with volume support |

All three use the same configured model: provider OpenAI, base URL
`https://openrouter.ai/api/v1`, model `openrouter/free`. The router can choose a
different free underlying model per request, so this compares personas using
that router. Do not describe it as a controlled comparison of fixed model IDs.

| Setting | Value |
| --- | --- |
| Data source | OKX US public historical candles |
| Symbols | BTCUSDT, ETHUSDT, SOLUSDT |
| UTC interval | 2026-09-13 00:00 through 2026-09-14 00:00 |
| Los Angeles browser inputs | 2026-09-12 17:00 through 2026-09-13 17:00 |
| Initial virtual balance | 1,000 USDT per competitor |
| Input timeframes | 3m, 15m, 4h |
| Decision timeframe and cadence | 4h, every 1 bar |
| BTC/ETH and altcoin leverage | 1x and 1x |
| Fees and slippage | 5 bps and 2 bps |
| Fill policy | Next open |
| Prompt style | Baseline |
| Reuse AI cache / replay only | On / Off |

Keep shared strategy limits equal: three positions, 30% maximum margin,
confidence 75, minimum position 12, and the same static symbols and indicators.
Disable current quant/ranking feeds for historical decisions. Include the
following in every persona's simulation prompt:

> For every proposed position, set leverage to exactly 1. Manage exits through
> explicit close decisions; do not rely on automatic stop-loss or take-profit
> triggers in this simulation. Holding cash is valid.

The maintained competition build supplies a strict JSON schema to the free
router and validates the returned object locally. This replaces earlier XML
format examples. Keep the persona prompt focused on signals, risk limits, and a
brief rationale. Decisions must use the configured symbols, including explicit
wait decisions when no action is justified; `ALL` is invalid.

## Run and score

Select a saved strategy and the shared model, enter the matching settings,
then start its historical run. Record the strategy-to-run-ID mapping immediately;
the UI includes the strategy name in generated run IDs. Repeat for the other two
strategies. Each round
has six scheduled decision cycles per competitor, 18 logical model requests in
total. The strict historical free-router path makes one provider attempt per
cycle, including transient errors. A free-provider limit is a failed or
incomplete round, not permission to switch to a paid model.

Before ranking a run, verify all of the following in the UI:

1. Status is Completed and all six Decisions show Success without an error.
2. Every executed fill and remaining position uses exactly 1x leverage.
3. Source, interval, symbols, initial balance, fees, slippage, and style match.
4. The saved strategy and generated run ID are recorded together.

Rank eligible competitors by ending marked equity (equivalently net return),
then by lower maximum drawdown for ties. If all eligible competitors hold cash,
report a tie. Do not count a failed decision as a successful cash decision.

Return includes executed fees and slippage plus unrealized P&L. Positions are
not forcibly closed at the interval end, funding is not modeled, and drawdown
is sampled at decision-bar closes. Total Trades counts closed trades rather
than all openings. Preserve these definitions in any published results.

## Current limitations

The simulator does not execute stop-loss/take-profit triggers. Completed can
still conceal earlier failed AI cycles. The maintained competition build caps
actual fill leverage and exposes recorded failures in the comparison table;
nevertheless, enforce every eligibility check above before assigning a score.

The first observed Trend and Breakout runs displayed Completed despite two and
three failed decisions out of six, respectively. Both are ineligible for ranking.
Their error was `ALL wait: price unavailable for ALL`; failed responses included
prose or a safety label without the required JSON. The legacy parser in
`kernel/engine.go` synthesizes an `ALL` wait when decision JSON is missing, then
`backtest/runner.go` looks up its price before treating wait as a no-op. The new
historical free-router path bypasses that fallback: malformed output remains a
failed cycle rather than a successful cash decision. Other model request paths
retain their legacy parsing behavior.

Keep each round uninterrupted by backend restarts. A running simulation retains
its loaded strategy, but the persisted configuration does not serialize that
strategy object. Cold resume can therefore reconstruct defaults instead of the
selected persona. Start a fresh matched round after a restart; a future runtime
fix should persist and restore the complete strategy snapshot.

Select Compare on the three runs to show their recorded metrics side by side.
The table preserves selection order and does not certify eligibility or declare
a winner. Missing metrics stay unavailable, and decision-record completeness
must be checked against the six expected cycles. Read each run's Overview,
Trades, Positions, and Decisions before ranking. Do not publish private account
balances through the live Competition page to imitate a simulation scoreboard.

The earlier competition features shipped in reviewed source
`25bcecebfd6d18f4a2b41f9bbd7640ad742f9e1b`, deployed by
[PR #1052](https://github.com/Stuhlmuller/homelab/pull/1052). Read-only inspection
on 2026-09-20 found Argo CD Synced/Healthy at
`047d26f088b6733dcd8b9c48dcec9cdca393c10f`, both deployments ready `1/1`, and
running image IDs matching the then-declared backend `58c274ba93e0…` and frontend
`92542955d244…` digests. No live traders were running. Current desired image
references are in `clusters/homelab/apps/nofx/deployment.yaml`; those historical
digests do not establish acceptance of patch `0012`.

Reload an already-open Backtest Lab tab after deployment and verify the OKX US
data-source selector before starting fresh runs. An old tab still executing
`index-DZRrtCHp` created `bt_20260920_235904` against Binance and failed with
HTTP 451 despite the healthy new frontend. An ordinary reload loaded
`index-CrqEPk8_` and the OKX selector. Retain the failed row as evidence; it is
not a result from the new OKX round. The earlier `f76c278` images also lack the
competition fixes.

Source: `backtest/runner.go`, `backtest/account.go`, `kernel/engine.go`, and
`web/src/components/BacktestPage.tsx` at the maintained upstream revision in
`builds/nofx/source.json`. These observations do not establish a complete,
eligible round or a winner.

## Observed prompt-only rerun

The second round used a shared prompt requiring a JSON array inside `<decision>`
tags and explicit configured symbols. UI inspection
on 2026-09-20 UTC found the following completed simulations:

| Persona | Run ID | Successful cycles | Failed cycles | Ending virtual USDT | Eligible |
| --- | --- | --- | --- | --- | --- |
| Trend | `bt_20260920_050546` | 5 | 1 | 999.72 | No |
| Mean Reversion | `bt_20260920_050609` | 6 | 0 | 1,000.00 | Yes |
| Breakout | `bt_20260920_050642` | 5 | 1 | 1,000.00 | No |

Mean Reversion made six explicit no-action decisions and had no trades. Both
other runs still hit the `ALL` parse fallback. Prompt wording alone therefore
did not produce a complete eligible competition; these results do not identify
a winning persona. These amounts are simulated balances, not OKX account data.

## Observed structured-output round

After the browser reload, all three saved persona prompts used the supplied
JSON schema without the old XML examples. UI inspection on 2026-09-21 UTC
verified matching settings from the table above, OKX US candles, and all six
expected decision timestamps per run. The terminal comparison displayed:

| Persona | Run ID | Successful cycles | Failed cycles | Ending virtual USDT | Net return | Max drawdown |
| --- | --- | --- | --- | --- | --- | --- |
| Trend | `bt_sim_trend_20260921000146206_162142266b29` | 3 | 3 | 1,000.00 | 0.00% | 0.00% |
| Mean Reversion | `bt_sim_mean_reversion_20260921000231158_226312a5f5bb` | 5 | 1 | 1,000.00 | 0.00% | 0.00% |
| Breakout | `bt_sim_breakout_20260921000254193_9c618d52e692` | 5 | 1 | 999.75 | -0.02% | 0.25% |

All three displayed Completed, but none is eligible and there is no winner.
Trend had two client timeouts and one non-normal structured response finish;
Mean Reversion and Breakout each had one non-normal finish. The displayed
errors do not distinguish truncation, filtering, or another provider cause.
Mean Reversion had no fills; Breakout opened BTC, ETH, and SOL shorts at 1x.
These are recorded virtual results with displayed rounding. They verify that
failed decisions remain visible, not successful competition acceptance. Keep
the runs for diagnosis rather than counting their failures as cash decisions.
