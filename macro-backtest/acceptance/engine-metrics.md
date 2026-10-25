# Macro performance contract v1.4

## Current investment performance

The only current accepted metric source is each individual result's `performance` block, convention `unitized_fee_inclusive_twr_v1`. Acceptance binds the entire block to the exact raw scenario output and sets sidecar `metrics` equal to `performance.metrics`. Legacy top-level numbers cannot substitute.

Unit NAV begins at 1 immediately before initial purchases. Initial purchase fees lower NAV and therefore count in inception total return and drawdown. Each positive external contribution issues units at contemporaneous **pre-flow** NAV; the cash addition itself does not change NAV. Subsequent buys/sells and their fees change NAV. Same-date event order is retained. For core end-period contributions this is equivalent to geometrically linking the pre-flow market factor with `post_trade_value / (pre_trade_value + contribution)`; subtracting contribution after charging fees would misallocate those fees. Withdrawal/negative contribution handling is not supported and rejects. Nonpositive capital, nonfinite values, and fees outside [0,1) reject.

Completed-month endpoint unit NAVs produce monthly investment returns. The first measured interval includes the initial fee; no fictitious extra month is added. `total_return = final_unit_NAV - 1`. `ann_return = final_unit_NAV ** (365.25 / elapsed_calendar_days) - 1`, where inception and final actual observation dates are recorded. An initial partial month may occur. `first_period_partial` describes calendar-inception timing, not independent exchange-session completeness; elapsed-day/sampling warnings must be retained.

`ann_vol = sample_std(monthly_returns) * sqrt(12)`. Internal Sharpe uses monthly mean divided by sample deviation, no risk-free subtraction. Internal Sortino uses sample deviation of the negative-return subset, **not** conventional downside semideviation/MAR. These monthly-sampling ratios are not duration-normalized for irregular/partial first intervals. Undefined denominators/insufficient samples produce null plus `undefined_reasons`, never fabricated zero.

Drawdown includes initial wealth1 and post-initial-fee NAV before all month-end endpoints. Consequently two -10% periods produce -19% inception drawdown. This is inception-and-month-end sampled drawdown, not a claim to maximum intraday/daily drawdown. Worst month is the minimum sampled interval return. `ending_value` is flow-inclusive ending wealth at the final retained observation, not investment return or investor money-weighted return/IRR.

This implements a unitized time-weighted calculation; **no GIPS compliance claim** is made. Calculation repair does not authenticate market data, historical source assertions, current-canon alignment, portfolio suitability, or live readiness. Calendar/raw observation checks and workflow provenance remain separate mandatory gates.

## Preserved legacy history

Existing top-level metrics and explicit `legacy_metrics` retain the prior calculation for compatibility and characterization. Core legacy returns omit contemporaneous fees; historical legacy value growth includes external contributions; legacy drawdown omits initial wealth1. These are not the current accepted performance series. The exact prior contract and pinned characterization tests remain in `legacy-v1.3/` and `test_engine_metrics.py`.

No stored result is silently recalculated or overwritten. `legacy-inventory.json` identifies tracked pre-v1.4 result artifacts by path and SHA256; they are `LEGACY_NOT_REVALIDATED`, not automatically false. Revalidation requires a separately authorized rerun/reconstruction with all current data, code, flow, control, historical and completed-workflow evidence. Missing evidence stays quarantined. No auto-runs are authorized by inventory or migration.

## Test-type and historical controls

Each run has exactly one uppercase primary type: `COMMON_WINDOW_ARCHITECTURE`, `ANCHOR_FORWARD_THESIS`, or `EVENT_DATED_SYSTEM`. A suite is a collection of separately identified runs, not a fourth primary type. Raw legacy lowercase labels are not authoritative contract labels.

Retrospective architecture explicitly carries selection/survivorship exposure. Historical `FULL_SCOPE` means only its declared evidenced scope, never all conceivable history. `SUPPORTED_SUBSET` requires omitted-scope disclosure and `SUPPORTED_SUBSET_ONLY`; incomplete evidence cannot become complete merely by changing a label. Historical controls must be explicit in executed config and tied to pre-anchor source identity/digest/date; unsupported/missing defaults reject. March's actual zero-contribution `cash_only` configuration is preserved. Other evidenced historical studies may have different approved flows. Events have separately bound fingerprints and actual execution outcomes.
