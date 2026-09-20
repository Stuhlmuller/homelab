# NOFX agent competition

Use Backtest Lab for an isolated historical round. Each run has its own virtual
account and AI cache. The live Competition page ranks exchange traders; it is
not the scoreboard for these simulations.

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

These features require the competition build from reviewed source
`25bcecebfd6d18f4a2b41f9bbd7640ad742f9e1b`. Verify its running image digests before
acceptance, then use fresh run IDs. The earlier `f76c278` images lack these fixes.

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
