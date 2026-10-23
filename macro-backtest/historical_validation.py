import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

FEE_DEFAULT = 0.0005


def _completed_monthly_values(values):
    values = pd.Series(values, dtype=float).dropna().sort_index()
    if len(values) == 0:
        return values
    last_obs = values.index.max()
    monthly_values = values.resample("ME").last()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    if last_obs.to_period("M") == now.to_period("M"):
        monthly_values = monthly_values[monthly_values.index.to_period("M") < now.to_period("M")]
    return monthly_values


def _flow_adjusted_monthly_returns(values, cash_flows=None, initial_value=None):
    """Build time-weighted monthly returns from account values and external flows.

    The simulation records values after same-day events.  Removing each external
    flow before comparing with the prior value prevents deposits from becoming
    performance while retaining transaction-fee losses in the return path.
    """
    values = pd.Series(values, dtype=float).dropna().sort_index()
    if values.empty:
        return pd.Series(dtype=float)

    flows = pd.Series(0.0, index=values.index)
    if cash_flows is not None:
        supplied = pd.Series(cash_flows, dtype=float)
        supplied.index = pd.to_datetime(supplied.index).tz_localize(None)
        flows = flows.add(supplied.groupby(level=0).sum(), fill_value=0.0).reindex(values.index, fill_value=0.0)

    step_returns = {}
    previous = float(initial_value) if initial_value is not None else None
    for date, value in values.items():
        if previous is not None:
            if previous <= 0:
                raise RuntimeError("RUN INVALID - non-positive return basis")
            step_returns[date] = (float(value) - float(flows.loc[date])) / previous - 1.0
        previous = float(value)

    returns = pd.Series(step_returns, dtype=float).sort_index()
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    if values.index.max().to_period("M") == now.to_period("M"):
        returns = returns[returns.index.to_period("M") < now.to_period("M")]
    if returns.empty:
        return returns
    monthly = returns.groupby(returns.index.to_period("M")).apply(lambda x: (1.0 + x).prod() - 1.0)
    if initial_value is not None:
        # Keep the established convention that the anchor month supplies the
        # baseline rather than an extra return observation.  Roll allocation
        # fees and any partial-anchor performance into the first subsequent
        # completed-month return so they are charged exactly once.
        if len(monthly) < 2:
            return pd.Series(dtype=float)
        first_factor = 1.0 + float(monthly.iloc[0])
        monthly = monthly.iloc[1:].copy()
        monthly.iloc[0] = first_factor * (1.0 + float(monthly.iloc[0])) - 1.0
    return monthly


def stats_from_values(values, cash_flows=None, initial_value=None):
    monthly_values = _completed_monthly_values(values)
    monthly = _flow_adjusted_monthly_returns(values, cash_flows, initial_value)
    if len(monthly) == 0:
        raise RuntimeError("RUN INVALID — no completed monthly returns available")
    wealth = (1 + monthly).cumprod()
    wealth_path = pd.concat([pd.Series([1.0]), wealth.reset_index(drop=True)], ignore_index=True)
    dd = wealth_path / wealth_path.cummax() - 1
    ann = wealth.iloc[-1] ** (12 / len(monthly)) - 1
    vol = monthly.std() * math.sqrt(12)
    sharpe = monthly.mean() / monthly.std() * math.sqrt(12) if monthly.std() > 0 else np.nan
    dn = monthly[monthly < 0].std()
    sortino = monthly.mean() / dn * math.sqrt(12) if pd.notna(dn) and dn > 0 else np.nan
    return {
        "ann_return": float(ann),
        "ann_vol": float(vol),
        "sharpe": float(sharpe) if pd.notna(sharpe) else None,
        "sortino": float(sortino) if pd.notna(sortino) else None,
        "max_drawdown": float(dd.min()),
        "worst_month": float(monthly.min()),
        "ending_value": float(monthly_values.iloc[-1]),
        "months": int(len(monthly)),
    }


def normalize_target_check(targets, cash_target):
    total = sum(float(v) for v in targets.values()) + float(cash_target)
    if abs(total - 1.0) > 1e-8:
        raise RuntimeError(f"RUN INVALID — targets + cash must sum to 1.0, got {total:.10f}")
    if any(float(v) < 0 for v in targets.values()) or cash_target < 0:
        raise RuntimeError("RUN INVALID — negative target weight")


def load_daily_prices(tickers, start, end=None):
    data = yf.download(
        sorted(set(tickers)),
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    out = {}
    for ticker in sorted(set(tickers)):
        try:
            if len(tickers) == 1 and "Close" in data:
                out[ticker] = data["Close"]
            else:
                out[ticker] = data[ticker]["Close"]
        except Exception:
            pass
    p = pd.DataFrame(out)
    p.index = pd.to_datetime(p.index).tz_localize(None)
    return p.sort_index()


def _first_complete_date(prices, tickers, anchor):
    anchor = pd.Timestamp(anchor)
    p = prices.loc[prices.index >= anchor, tickers]
    complete = p.dropna()
    if complete.empty:
        raise RuntimeError("RUN INVALID — no complete price date on/after anchor")
    return complete.index[0]


def run_anchor_forward(prices, cfg):
    targets = {k: float(v) for k, v in cfg["targets"].items()}
    cash_target = float(cfg.get("cash_target", 0.0))
    normalize_target_check(targets, cash_target)

    anchor = pd.Timestamp(cfg["anchor_date"])
    initial = float(cfg.get("initial_capital", 500))
    monthly = float(cfg.get("monthly_contribution", 0))
    fee = float(cfg.get("fee", FEE_DEFAULT))
    refill = cfg.get("refill_method", "target_gap")
    tickers = list(targets)

    d0 = _first_complete_date(prices, tickers, anchor)
    if (d0 - anchor).days > int(cfg.get("max_anchor_slippage_days", 7)):
        raise RuntimeError(
            f"RUN INVALID — first complete trading date {d0.date()} is too far after anchor {anchor.date()}"
        )

    p = prices.loc[d0:, tickers].ffill().dropna()
    shares = {t: 0.0 for t in tickers}
    cash = initial

    for t, w in targets.items():
        dollars = initial * w
        shares[t] = dollars * (1 - fee) / p.loc[d0, t]
        cash -= dollars

    values = {d0: cash + sum(shares[t] * p.loc[d0, t] for t in tickers)}
    cash_flows = {}
    month_groups = list(p.groupby(p.index.to_period("M")))

    for _, frame in month_groups:
        d = frame.index[-1]
        if d == d0:
            continue
        cash += monthly
        cash_flows[d] = cash_flows.get(d, 0.0) + monthly
        total = cash + sum(shares[t] * p.loc[d, t] for t in tickers)
        floor = cash_target * total
        deploy = max(0.0, cash - floor)

        if deploy > 0 and refill != "cash_only":
            gaps = {t: max(0.0, targets[t] * total - shares[t] * p.loc[d, t]) for t in tickers}
            if refill == "target_gap":
                remaining = deploy
                for t, gap in sorted(gaps.items(), key=lambda kv: kv[1], reverse=True):
                    amt = min(remaining, gap)
                    if amt > 0:
                        shares[t] += amt * (1 - fee) / p.loc[d, t]
                        cash -= amt
                        remaining -= amt
                    if remaining <= 1e-10:
                        break
            elif refill == "proportional":
                gap_sum = sum(gaps.values())
                if gap_sum > 0:
                    for t in tickers:
                        amt = min(deploy * gaps[t] / gap_sum, gaps[t])
                        if amt > 0:
                            shares[t] += amt * (1 - fee) / p.loc[d, t]
                            cash -= amt
            else:
                raise RuntimeError(f"RUN INVALID — unknown refill_method {refill}")

        values[d] = cash + sum(shares[t] * p.loc[d, t] for t in tickers)

    s = pd.Series(values).sort_index()
    completed_values = _completed_monthly_values(s)
    metrics = stats_from_values(s, cash_flows=cash_flows, initial_value=initial)
    result = {
        "test_type": "ANCHOR_FORWARD_THESIS",
        "anchor_date": str(anchor.date()),
        "requested_start": str(anchor.date()),
        "actual_start": str(d0.date()),
        "actual_end": str(completed_values.index[-1].date()),
        "months": metrics["months"],
        "start_reason": "first complete trading date on/after verified historical anchor",
        "information_set": cfg.get(
            "information_set",
            "Only holdings, weights, thesis statements, and rules documented on or before the anchor date.",
        ),
        "bias_classification": (
            "Ex-ante anchor-forward security-selection test when the snapshot is complete and genuinely predates "
            "the measured period. Do not label post-anchor performance as hindsight selection merely because the "
            "test is run later. Bias remains if contemporaneous losers/positions were omitted or later information "
            "was used to alter the frozen snapshot."
        ),
        "targets": targets,
        "cash_target": cash_target,
        "refill_method": refill,
        "metrics": metrics,
    }
    return result


def run_event_dated(prices, cfg):
    anchor = pd.Timestamp(cfg["anchor_date"])
    initial = float(cfg.get("initial_capital", 500))
    fee = float(cfg.get("fee", FEE_DEFAULT))
    exclude_exogenous = bool(cfg.get("exclude_exogenous", False))
    initial_targets = {k: float(v) for k, v in cfg.get("initial_targets", {}).items()}
    cash_target = float(cfg.get("cash_target", 0.0))
    if initial_targets:
        normalize_target_check(initial_targets, cash_target)

    events = sorted(cfg.get("events", []), key=lambda x: x["date"])
    tickers = sorted(set(initial_targets) | {e["ticker"] for e in events if e.get("ticker")})
    if not tickers:
        raise RuntimeError("RUN INVALID — event-dated test has no tickers")

    d0 = _first_complete_date(prices, list(initial_targets) or tickers, anchor)
    p = prices.loc[d0:, tickers].ffill()
    shares = {t: 0.0 for t in tickers}
    cash = initial

    if initial_targets:
        for t, w in initial_targets.items():
            dollars = initial * w
            shares[t] += dollars * (1 - fee) / p.loc[d0, t]
            cash -= dollars

    values = {}
    cash_flows = {}
    applied = []
    event_idx = 0
    for d in p.index:
        while event_idx < len(events) and pd.Timestamp(events[event_idx]["date"]) <= d:
            e = events[event_idx]
            event_idx += 1
            if exclude_exogenous and str(e.get("classification", "")).upper() == "EXOGENOUS":
                applied.append({**e, "status": "EXCLUDED_EXOGENOUS"})
                continue
            kind = str(e.get("type", "")).upper()
            if kind == "CONTRIBUTION":
                amount = float(e["dollars"])
                if amount < 0:
                    raise RuntimeError("RUN INVALID - negative contribution")
                cash += amount
                cash_flows[d] = cash_flows.get(d, 0.0) + amount
                applied.append({
                    **e,
                    "status": "APPLIED",
                    "execution_date": str(d.date()),
                    "requested_dollars": amount,
                    "executed_dollars": amount,
                })
                continue
            ticker = e.get("ticker")
            if ticker not in shares or pd.isna(p.loc[d, ticker]):
                raise RuntimeError(f"RUN INVALID — missing price for event ticker {ticker} on {d.date()}")
            px = float(p.loc[d, ticker])
            if kind == "BUY_DOLLARS":
                requested = float(e["dollars"])
                if requested < 0:
                    raise RuntimeError("RUN INVALID - negative BUY_DOLLARS amount")
                amt = min(requested, cash)
                shares[ticker] += amt * (1 - fee) / px
                cash -= amt
                execution = {
                    "requested_dollars": requested,
                    "executed_dollars": amt,
                    "unfilled_dollars": requested - amt,
                }
            elif kind == "SELL_DOLLARS":
                requested = float(e["dollars"])
                if requested < 0:
                    raise RuntimeError("RUN INVALID - negative SELL_DOLLARS amount")
                amt = min(requested, shares[ticker] * px)
                shares[ticker] -= amt / px
                cash += amt * (1 - fee)
                execution = {
                    "requested_dollars": requested,
                    "executed_dollars": amt,
                    "unfilled_dollars": requested - amt,
                }
            elif kind == "BUY_SHARES":
                requested = float(e["shares"])
                if requested < 0:
                    raise RuntimeError("RUN INVALID - negative BUY_SHARES quantity")
                qty = requested
                gross = qty * px
                fee_dollars = gross * fee
                total_cash = gross + fee_dollars
                if total_cash > cash + 1e-8:
                    raise RuntimeError(f"RUN INVALID — insufficient cash for {ticker} buy on {d.date()}")
                shares[ticker] += qty
                cash -= total_cash
                execution = {
                    "requested_shares": requested,
                    "executed_shares": qty,
                    "unfilled_shares": 0.0,
                    "gross_dollars": gross,
                    "fee_dollars": fee_dollars,
                    "net_cash_change": -total_cash,
                }
            elif kind == "SELL_SHARES":
                requested = float(e["shares"])
                if requested < 0:
                    raise RuntimeError("RUN INVALID - negative SELL_SHARES quantity")
                qty = min(requested, shares[ticker])
                gross = qty * px
                fee_dollars = gross * fee
                net_proceeds = gross - fee_dollars
                shares[ticker] -= qty
                cash += net_proceeds
                execution = {
                    "requested_shares": requested,
                    "executed_shares": qty,
                    "unfilled_shares": requested - qty,
                    "gross_dollars": gross,
                    "fee_dollars": fee_dollars,
                    "net_cash_change": net_proceeds,
                }
            else:
                raise RuntimeError(f"RUN INVALID — unknown event type {kind}")
            requested_amount = execution.get("requested_dollars", execution.get("requested_shares", 0.0))
            executed_amount = execution.get("executed_dollars", execution.get("executed_shares", 0.0))
            if executed_amount <= 1e-12 and requested_amount > 1e-12:
                status = "NOT_EXECUTED"
            elif executed_amount + 1e-12 < requested_amount:
                status = "PARTIAL"
            else:
                status = "APPLIED"
            applied.append({
                **e,
                **execution,
                "status": status,
                "execution_date": str(d.date()),
            })

        total = cash + sum(shares[t] * p.loc[d, t] for t in tickers if pd.notna(p.loc[d, t]))
        values[d] = total

    if event_idx < len(events):
        raise RuntimeError("RUN INVALID - one or more events fall after the available price history")

    s = pd.Series(values).sort_index()
    completed_values = _completed_monthly_values(s)
    metrics = stats_from_values(s, cash_flows=cash_flows, initial_value=initial)
    return {
        "test_type": "EVENT_DATED_SYSTEM",
        "anchor_date": str(anchor.date()),
        "requested_start": str(anchor.date()),
        "actual_start": str(d0.date()),
        "actual_end": str(completed_values.index[-1].date()),
        "months": metrics["months"],
        "start_reason": "verified historical anchor plus timestamped transaction ledger",
        "information_set": cfg.get(
            "information_set",
            "Only transactions/decisions documented by their historical timestamps; later knowledge is not moved backward.",
        ),
        "bias_classification": (
            "Preferred decision-process test when the ledger includes winners, losers, adds, cuts, and exits. "
            "Survivorship bias is materially reduced only if the ledger is complete. Exogenous forced actions may "
            "be excluded only when explicitly documented and the counterfactual is labeled."
        ),
        "exclude_exogenous": exclude_exogenous,
        "events_applied": applied,
        "metrics": metrics,
    }


def self_test():
    idx = pd.bdate_range("2026-03-27", "2026-08-31")
    a = np.linspace(100, 150, len(idx))
    b = np.linspace(100, 90, len(idx))
    prices = pd.DataFrame({"AAA": a, "BBB": b}, index=idx)

    anchor_cfg = {
        "anchor_date": "2026-03-27",
        "targets": {"AAA": 0.6, "BBB": 0.4},
        "cash_target": 0.0,
        "initial_capital": 500,
        "monthly_contribution": 50,
        "refill_method": "target_gap",
    }
    anchor = run_anchor_forward(prices, anchor_cfg)
    assert anchor["test_type"] == "ANCHOR_FORWARD_THESIS"
    assert anchor["metrics"]["ending_value"] > 0

    event_cfg = {
        "anchor_date": "2026-03-27",
        "initial_targets": {"AAA": 0.5, "BBB": 0.5},
        "cash_target": 0.0,
        "initial_capital": 500,
        "events": [
            {"date": "2026-05-01", "type": "SELL_DOLLARS", "ticker": "BBB", "dollars": 50},
            {"date": "2026-05-01", "type": "BUY_DOLLARS", "ticker": "AAA", "dollars": 50},
            {"date": "2026-06-01", "type": "SELL_DOLLARS", "ticker": "AAA", "dollars": 20, "classification": "EXOGENOUS"},
        ],
        "exclude_exogenous": True,
    }
    event = run_event_dated(prices, event_cfg)
    assert event["test_type"] == "EVENT_DATED_SYSTEM"
    assert any(x["status"] == "EXCLUDED_EXOGENOUS" for x in event["events_applied"])
    print(json.dumps({"self_test": "PASS", "anchor": anchor["metrics"], "event": event["metrics"]}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--output", default="macro-backtest/results-historical-validation/results.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.config:
        raise SystemExit("--config is required unless --self-test is used")

    cfg = json.loads(Path(args.config).read_text())
    test_type = cfg["test_type"].upper()
    if test_type == "ANCHOR_FORWARD_THESIS":
        tickers = list(cfg["targets"])
    elif test_type == "EVENT_DATED_SYSTEM":
        tickers = sorted(
            set(cfg.get("initial_targets", {}))
            | {e["ticker"] for e in cfg.get("events", []) if e.get("ticker")}
        )
    else:
        raise RuntimeError(
            "RUN INVALID — historical_validation.py supports ANCHOR_FORWARD_THESIS and EVENT_DATED_SYSTEM; "
            "use the existing engine for COMMON_WINDOW_ARCHITECTURE"
        )

    prices = load_daily_prices(tickers, cfg["anchor_date"], cfg.get("end_date"))
    result = run_anchor_forward(prices, cfg) if test_type == "ANCHOR_FORWARD_THESIS" else run_event_dated(prices, cfg)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
