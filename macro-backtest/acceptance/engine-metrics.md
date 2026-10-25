# Engine metric and cash-flow contract — inspected implementation

Source: `phill55188-ops/phill55188-ops.github.io`, branch `macro-backtest-v08`, commit `e57e26ef1258cba162471f8e6ba6f2eb9f41efee`. Read-only inspection dated 2026-10-25. This documents existing behavior; it changes no engine, return calculation, portfolio rule, or trading authority. Offline synthetic fixtures are not a successful GitHub backtest and do not prove live integration.

## Core `macro-backtest/backtest.py::stats`

Let r be non-null monthly returns, n its length, W_t the cumulative product of (1+r), and s the sample standard deviation (pandas default ddof=1).

- Annual return: `W_last ** (12/n) - 1` (geometric annualization).
- Annual volatility: `s(r) * sqrt(12)`.
- Sharpe: `mean(r) / s(r) * sqrt(12)`, only if s(r)>0; no risk-free subtraction. Otherwise NaN.
- Internal Sortino: `mean(r) / s(r[r<0]) * sqrt(12)` when that negative-subset **sample standard deviation** exists and is positive. This is not a conventional downside semi-deviation or explicit MAR calculation. Fewer than two negative returns, or equal negative returns, produce undefined NaN.
- Drawdown: `min(W / cumulative_max(W) - 1)`. The series does **not** prepend an initial wealth point of 1. Consequently a first-period loss is not fully reflected: [-10%,-10%] reports -10%, not -19% from inception.
- Worst month: minimum r.
- Empty return inputs are not supported by core stats; missing/NaN and undefined ratios must never be silently converted to zero.

Core `run` adds `ending_value` as final post-trade cash plus marked shares, and `months=len(rets)`. For each month after the first observation: compute pre-contribution portfolio value; append `pre/prev-1`; add contribution; rebalance/refill and charge fees; set prev to **post-trade** value. Initial buys reduce acquired shares by `(1-FEE)`, as do subsequent buys. Sells add proceeds times `(1-FEE)`. Thus reported monthly return excludes contemporaneous external contributions and does **not** charge those trading fees through the return series, although fees lower ending value. Do not call it fee-inclusive total return. Operating cash earns zero explicitly; stock prices use yfinance `auto_adjust=True`.

## Historical `macro-backtest/historical_validation.py`

`stats_from_values` resamples supplied portfolio values to month-end last, then uses raw `pct_change`. Annualization, sample volatility, Sharpe, negative-subset Sortino, drawdown, and worst month otherwise match the above. Undefined Sharpe/Sortino become JSON null rather than NaN; no completed monthly returns raises an error. Ending value is the last retained monthly value, not necessarily the last daily value.

Anchor-forward initializes on the first complete date on/after the anchor (subject to max-anchor-slippage days), applies initial buy fees, then adds configured monthly contributions at each month's final available date (including the anchor month when that date differs from the initial date). It deploys cash via target-gap or proportional rules, or retains cash for `cash_only`. Recorded values are post-contribution and post-refill. Therefore nonzero contributions are included in raw value-growth returns: flat prices, initial 100, monthly 100 over two subsequent observations, 1% buy fee give ending value 297 and annualized value growth 728 (72,800%), **not investment performance**. For a no-contribution frozen thesis this external-flow issue does not arise; initial fees still predate the first monthly return baseline.

Event-dated applies events in chronological order on the first available date on/after each event date, then records daily value. Contributions similarly enter raw growth. Dollar buys cap at available cash; dollar/share sells cap at held amount; share buys require cash and credit shares times `(1-fee)`. Explicit excluded exogenous events are retained in `events_applied` as `EXCLUDED_EXOGENOUS`. Current code's event loop does not itself validate provenance, completeness, or a pre-anchor ledger; the evidence acceptance gate must do so. Events after available prices are not executed by that loop. A contract must not claim a full ledger replay without checking all expected events against outcomes.

## Time and data limits

Both monthly helpers drop the current month when the last observation is in the current month and normalized UTC today is before calendar month-end. On calendar month-end itself the helper includes it even shortly after midnight. A historical/stale series truncated mid-prior-month is resampled to that month's end without detecting incompleteness. Price values can be forward-filled. Preserve raw observation dates, data-as-of time, and completed-month cutoff in the acceptance evidence; never infer complete coverage from a month-end label alone. The independent acceptance validator can reject these outputs; this release does not claim the engine helper itself is fixed.

The defense harness's separate daily/stress diagnostic resamples monthly prices directly without calling the completed-month helper. Its stress proxies are separate diagnostics, not the smart-refill return series. Their dates need separate screening. Its hardcoded architecture is v10.29 and the orchestration overlay refers to an older architecture; neither is proof of current canon alignment. Do not relabel them current without reconciliation.

## Known-answer evidence and scope

`test_engine_metrics.py` AST-extracts only named pure/synthetic functions; does not import the engine, invoke main, download market data, dispatch workflows, trade, or run a live portfolio. Twelve fixtures pass against the pinned source copies with pandas 2.2.3 / numpy 2.3.5. They cover formulas, undefined ratios, drawdown baseline, core vs historical contributions/fees, no completed returns, partial current month, stale partial prior month, and month-end-day behavior. This is characterization, including documented limitations—not engine correction, comprehensive engine certification, or an accepted financial result.
