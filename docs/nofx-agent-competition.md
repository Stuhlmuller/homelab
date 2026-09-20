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

## Run and score

Select a saved strategy and the shared model, enter the matching settings,
then start its historical run. Record the strategy-to-run-ID mapping immediately;
the UI generates the run ID. Repeat for the other two strategies. Each round
has six scheduled decision cycles per competitor, 18 logical model requests in
total. Provider retries may add requests. A free-provider limit is a failed or
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

The pinned simulator does not execute stop-loss/take-profit triggers. Its
leverage validation currently clamps a copy of each decision while execution
can use the original requested leverage. Also, Completed can conceal earlier
failed AI cycles. Enforce the eligibility checks above; a violating run cannot
supply a valid score. A future runtime change should clamp the actual executed
decision and preserve failed-cycle visibility, with focused regression tests.

The Backtest Lab Compare buttons only select IDs; this release has no rendered
comparison table. Read each eligible run's Overview, Trades, Positions, and
Decisions and record actual results together. Do not publish private account
balances through the live Competition page to imitate a simulation scoreboard.

Source: `backtest/runner.go`, `backtest/account.go`, `kernel/engine.go`, and
`web/src/components/BacktestPage.tsx` at the maintained upstream revision in
`builds/nofx/source.json`. This document specifies the round; it does not claim
that any run completed or that a winner exists.
