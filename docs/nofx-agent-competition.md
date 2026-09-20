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

Also require a brief rationale followed by a valid JSON decision array inside
`<decision>...</decision>`. Every entry must use `BTCUSDT`, `ETHUSDT`, or
`SOLUSDT`; never use `ALL`. A no-action response still needs an explicit wait:

```text
No confirmed signal.
<decision>[{"symbol":"BTCUSDT","action":"wait"}]</decision>
```

This prompt mitigation is saved for all three competitors. Start a fresh round
with the same strengthened prompt for each competitor; do not mix its results
with earlier runs. It does not guarantee valid model output.

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

The first observed Trend and Breakout runs displayed Completed despite two and
three failed decisions out of six, respectively. Both are ineligible for ranking.
Their error was `ALL wait: price unavailable for ALL`; failed responses included
prose or a safety label without the required JSON. The parser in
`kernel/engine.go` synthesizes an `ALL` wait when decision JSON is missing, then
`backtest/runner.go` looks up its price before treating wait as a no-op. A future
fix must distinguish malformed model output from a genuine wait, preserve the
failure for round eligibility, and handle valid no-action decisions without
inventing a tradable symbol. Test missing JSON separately from explicit waits;
do not turn parse failures into successful cash decisions.

Keep each round uninterrupted by backend restarts. A running simulation retains
its loaded strategy, but the persisted configuration does not serialize that
strategy object. Cold resume can therefore reconstruct defaults instead of the
selected persona. Start a fresh matched round after a restart; a future runtime
fix should persist and restore the complete strategy snapshot.

The Backtest Lab Compare buttons only select IDs; this release has no rendered
comparison table. Read each eligible run's Overview, Trades, Positions, and
Decisions and record actual results together. Do not publish private account
balances through the live Competition page to imitate a simulation scoreboard.

The next maintained build adds a factual comparison table and strategy names in
new run IDs. It also requests strict JSON-schema output for historical
`openrouter/free` calls to the official OpenRouter API and caps actual fill
leverage. That path makes one provider attempt per cycle, including transient
errors; failures remain failures. Its schema instruction supersedes the earlier
XML-format prompt mitigation. After publishing and deploying the new image
digests, use fresh run IDs and repeat all eligibility checks before ranking.

Source: `backtest/runner.go`, `backtest/account.go`, `kernel/engine.go`, and
`web/src/components/BacktestPage.tsx` at the maintained upstream revision in
`builds/nofx/source.json`. These observations do not establish a complete,
eligible round or a winner.

## Observed prompt-only rerun

The second round used the shared JSON prompt mitigation above. UI inspection
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
