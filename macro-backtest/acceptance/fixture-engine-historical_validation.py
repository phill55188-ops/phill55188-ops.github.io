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
    now = pd.Timestamp.utcnow().tz_localize(None).normalize()
    if last_obs.to_period("M") == now.to_period("M"):
        month_end = now + pd.offsets.MonthEnd(0)
        if now < month_end:
            monthly_values = monthly_values[monthly_values.index.to_period("M") < now.to_period("M")]
    return monthly_values

def stats_from_values(values):
    monthly_values = _completed_monthly_values(values)
    monthly = monthly_values.pct_change().dropna()
    if len(monthly) == 0:
        raise RuntimeError("RUN INVALID — no completed monthly returns available")
    wealth = (1 + monthly).cumprod()
    dd = wealth / wealth.cummax() - 1
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
    month_groups = list(p.groupby(p.index.to_period("M")))

    for _, frame in month_groups:
        d = frame.index[-1]
        if d == d0:
            continue
        cash += monthly
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
    result = {
        "test_type": "ANCHOR_FORWARD_THESIS",
        "anchor_date": str(anchor.date()),
        "actual_start": str(d0.date()),
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
        "metrics": stats_from_values(s),
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
                cash += float(e["dollars"])
                applied.append({**e, "status": "APPLIED"})
                continue
            ticker = e.get("ticker")
            if ticker not in shares or pd.isna(p.loc[d, ticker]):
                raise RuntimeError(f"RUN INVALID — missing price for event ticker {ticker} on {d.date()}")
            px = float(p.loc[d, ticker])
            if kind == "BUY_DOLLARS":
                amt = min(float(e["dollars"]), cash)
                shares[ticker] += amt * (1 - fee) / px
                cash -= amt
            elif kind == "SELL_DOLLARS":
                amt = min(float(e["dollars"]), shares[ticker] * px)
                shares[ticker] -= amt / px
                cash += amt * (1 - fee)
            elif kind == "BUY_SHARES":
                qty = float(e["shares"])
                cost = qty * px
                if cost > cash + 1e-8:
                    raise RuntimeError(f"RUN INVALID — insufficient cash for {ticker} buy on {d.date()}")
                shares[ticker] += qty * (1 - fee)
                cash -= cost
            elif kind == "SELL_SHARES":
                qty = min(float(e["shares"]), shares[ticker])
                shares[ticker] -= qty
                cash += qty * px * (1 - fee)
            else:
                raise RuntimeError(f"RUN INVALID — unknown event type {kind}")
            applied.append({**e, "status": "APPLIED", "execution_date": str(d.date())})

        total = cash + sum(shares[t] * p.loc[d, t] for t in tickers if pd.notna(p.loc[d, t]))
        values[d] = total

    s = pd.Series(values).sort_index()
    return {
        "test_type": "EVENT_DATED_SYSTEM",
        "anchor_date": str(anchor.date()),
        "actual_start": str(d0.date()),
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
        "metrics": stats_from_values(s),
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
