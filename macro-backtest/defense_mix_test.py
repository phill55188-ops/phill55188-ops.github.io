import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import backtest as bt

OUT = Path("macro-backtest/results-defense-mix")
OUT.mkdir(parents=True, exist_ok=True)

CASH = 0.01
START_REQUEST = "2024-01-01"

# Canonical v10.29 growth architecture: FN_2_GLOBAL, exact engine weights.
CURRENT_GROWTH = {
    "ADBE": 0.02,
    "SNPS": 0.02,
    "TSM": 0.02,
    "MP": 0.038587521663778164,
    "FCX": 0.038587521663778164,
    "LEU": 0.038587521663778164,
    "VRT": 0.038587521663778164,
    "BE": 0.038587521663778164,
    "GEV": 0.038587521663778164,
    "NVDA": 0.057881282495667256,
    "QCOM": 0.057881282495667256,
    "MU": 0.09488734835355288,
    "LITE": 0.038587521663778164,
    "MRVL": 0.038587521663778164,
    "ORCL": 0.038587521663778164,
    "NBIS": 0.038587521663778164,
    "NET": 0.038587521663778164,
    "PLTR": 0.09488734835355288,
    "FN": 0.02,
}

SCENARIOS = {
    "CURRENT_RSP7": {"RSP": 0.07, "SGOV": 0.08, "GLD": 0.03},
    "EINC7_REPLACES_RSP": {"EINC": 0.07, "SGOV": 0.08, "GLD": 0.03},
    "USAI7_REPLACES_RSP": {"USAI": 0.07, "SGOV": 0.08, "GLD": 0.03},
}

CANDIDATES = ["RSP", "EINC", "USAI"]


def metric_delta(row, base):
    return {
        "ann_return_points_vs_rsp": float((row.ann_return - base.ann_return) * 100),
        "ann_vol_points_vs_rsp": float((row.ann_vol - base.ann_vol) * 100),
        "sharpe_vs_rsp": float(row.sharpe - base.sharpe),
        "sortino_vs_rsp": float(row.sortino - base.sortino),
        "max_drawdown_points_vs_rsp": float((row.max_drawdown - base.max_drawdown) * 100),
        "worst_month_points_vs_rsp": float((row.worst_month - base.worst_month) * 100),
        "ending_value_vs_rsp": float(row.ending_value - base.ending_value),
    }


def load_daily_prices(tickers, start):
    x = yf.download(
        sorted(tickers),
        start=start,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    data = {}
    for ticker in sorted(tickers):
        try:
            data[ticker] = x[ticker]["Close"]
        except Exception:
            pass
    p = pd.DataFrame(data)
    p.index = pd.to_datetime(p.index).tz_localize(None)
    return p.sort_index()


def weighted_return_frame(returns, weights):
    cols = [t for t in weights if t in returns.columns]
    missing = sorted(set(weights) - set(cols))
    if missing:
        raise RuntimeError(f"RUN INVALID — missing return columns for: {missing}")
    return sum(returns[t] * weights[t] for t in cols)


def beta(asset, benchmark):
    pair = pd.concat([asset, benchmark], axis=1).dropna()
    if len(pair) < 3 or pair.iloc[:, 1].var() == 0:
        return np.nan
    return pair.iloc[:, 0].cov(pair.iloc[:, 1]) / pair.iloc[:, 1].var()


def downside_corr(asset, benchmark):
    pair = pd.concat([asset, benchmark], axis=1).dropna()
    pair = pair[pair.iloc[:, 1] < 0]
    if len(pair) < 3:
        return np.nan
    return pair.iloc[:, 0].corr(pair.iloc[:, 1])


def downside_capture(asset_monthly, benchmark_monthly):
    pair = pd.concat([asset_monthly, benchmark_monthly], axis=1).dropna()
    pair = pair[pair.iloc[:, 1] < 0]
    if len(pair) == 0:
        return np.nan
    denom = pair.iloc[:, 1].mean()
    if denom == 0:
        return np.nan
    return float(pair.iloc[:, 0].mean() / denom * 100)


def rolling_corr_stats(asset, benchmark):
    pair = pd.concat([asset, benchmark], axis=1).dropna()
    r60 = pair.iloc[:, 0].rolling(60).corr(pair.iloc[:, 1]).dropna()
    r120 = pair.iloc[:, 0].rolling(120).corr(pair.iloc[:, 1]).dropna()
    out = {
        "corr_full": float(pair.iloc[:, 0].corr(pair.iloc[:, 1])),
        "beta_full": float(beta(pair.iloc[:, 0], pair.iloc[:, 1])),
        "downside_corr": float(downside_corr(pair.iloc[:, 0], pair.iloc[:, 1])),
        "rolling_60d_avg": float(r60.mean()) if len(r60) else None,
        "rolling_60d_latest": float(r60.iloc[-1]) if len(r60) else None,
        "rolling_60d_min": float(r60.min()) if len(r60) else None,
        "rolling_60d_max": float(r60.max()) if len(r60) else None,
        "rolling_120d_latest": float(r120.iloc[-1]) if len(r120) else None,
        "observations": int(len(pair)),
    }
    return out


def main():
    assert abs(sum(CURRENT_GROWTH.values()) - 0.81) < 1e-10

    for name, defense in SCENARIOS.items():
        assert abs(sum(defense.values()) - 0.18) < 1e-10, (name, defense)
        assert abs(sum(defense.values()) + sum(CURRENT_GROWTH.values()) + CASH - 1.0) < 1e-10

    # 1) Canonical smart-refill portfolio backtest, same as the prior RSP-replacement run.
    all_defense = set().union(*(set(x) for x in SCENARIOS.values()))
    all_tickers = sorted(set(CURRENT_GROWTH) | all_defense)

    bt.GROWTH = dict(CURRENT_GROWTH)
    bt.TARGETS = {t: 0.01 for t in all_tickers}

    prices = bt.load_prices(START_REQUEST)
    earnings = bt.load_earnings()

    missing = [t for t in all_tickers if t not in prices.columns or prices[t].first_valid_index() is None]
    if missing:
        raise RuntimeError(f"RUN INVALID — missing historical monthly price data for: {missing}")

    common_start = max(prices[t].first_valid_index() for t in all_tickers)
    common_end = min(prices[t].last_valid_index() for t in all_tickers)
    prices = prices.loc[common_start:common_end].copy()

    rows = []
    logs = []
    target_rows = []

    for name, defense in SCENARIOS.items():
        targets = {**defense, **CURRENT_GROWTH}
        n, s, l = bt.run(
            name,
            prices,
            earnings,
            targets,
            "smart",
            500,
            200,
            CASH,
            list(CURRENT_GROWTH),
        )
        rows.append({"strategy": n, **s})
        l["strategy"] = n
        logs.append(l)

        for ticker, weight in targets.items():
            target_rows.append(
                {
                    "strategy": name,
                    "ticker": ticker,
                    "target_weight": weight,
                    "target_percent": weight * 100,
                }
            )

    df = pd.DataFrame(rows).set_index("strategy")
    base = df.loc["CURRENT_RSP7"]
    deltas = {name: metric_delta(df.loc[name], base) for name in df.index}

    # 2) Correlation / stress diagnostic at daily and monthly frequencies.
    stress_tickers = set(CURRENT_GROWTH) | {"RSP", "EINC", "USAI", "SGOV", "GLD", "SPY"}
    daily_prices = load_daily_prices(stress_tickers, START_REQUEST)

    missing_daily = [
        t for t in stress_tickers
        if t not in daily_prices.columns or daily_prices[t].first_valid_index() is None
    ]
    if missing_daily:
        raise RuntimeError(f"RUN INVALID — missing historical daily price data for: {missing_daily}")

    daily_start = max(daily_prices[t].first_valid_index() for t in stress_tickers)
    daily_end = min(daily_prices[t].last_valid_index() for t in stress_tickers)
    daily_prices = daily_prices.loc[daily_start:daily_end].ffill().dropna()

    daily_ret = daily_prices.pct_change().dropna()
    monthly_prices = daily_prices.resample("ME").last().dropna()
    monthly_ret = monthly_prices.pct_change().dropna()

    growth_norm = {t: w / 0.81 for t, w in CURRENT_GROWTH.items()}
    growth_daily = weighted_return_frame(daily_ret, growth_norm)
    growth_monthly = weighted_return_frame(monthly_ret, growth_norm)

    correlation = {}
    for cand in CANDIDATES:
        correlation[cand] = {
            "vs_spy": rolling_corr_stats(daily_ret[cand], daily_ret["SPY"]),
            "vs_growth_sleeve": rolling_corr_stats(daily_ret[cand], growth_daily),
            "monthly_downside_capture_vs_spy": downside_capture(monthly_ret[cand], monthly_ret["SPY"]),
            "monthly_downside_capture_vs_growth_sleeve": downside_capture(monthly_ret[cand], growth_monthly),
        }

    # Fixed-target monthly portfolio proxies isolate only the 7% sleeve substitution.
    portfolio_monthly = {}
    for name, defense in SCENARIOS.items():
        candidate = "RSP" if "RSP" in defense else ("EINC" if "EINC" in defense else "USAI")
        portfolio_monthly[name] = (
            weighted_return_frame(monthly_ret, CURRENT_GROWTH)
            + monthly_ret[candidate] * 0.07
            + monthly_ret["SGOV"] * 0.08
            + monthly_ret["GLD"] * 0.03
        )

    portfolio_proxy = pd.DataFrame(portfolio_monthly).dropna()
    baseline_worst = portfolio_proxy["CURRENT_RSP7"].nsmallest(min(5, len(portfolio_proxy)))

    worst_portfolio_months = []
    for date, rsp_return in baseline_worst.items():
        worst_portfolio_months.append(
            {
                "month": str(date.date()),
                "CURRENT_RSP7": float(portfolio_proxy.loc[date, "CURRENT_RSP7"]),
                "EINC7_REPLACES_RSP": float(portfolio_proxy.loc[date, "EINC7_REPLACES_RSP"]),
                "USAI7_REPLACES_RSP": float(portfolio_proxy.loc[date, "USAI7_REPLACES_RSP"]),
            }
        )

    worst_growth = growth_monthly.nsmallest(min(5, len(growth_monthly)))
    worst_growth_months = []
    for date, growth_return in worst_growth.items():
        worst_growth_months.append(
            {
                "month": str(date.date()),
                "growth_sleeve": float(growth_return),
                "RSP": float(monthly_ret.loc[date, "RSP"]),
                "EINC": float(monthly_ret.loc[date, "EINC"]),
                "USAI": float(monthly_ret.loc[date, "USAI"]),
                "SPY": float(monthly_ret.loc[date, "SPY"]),
            }
        )

    worst_growth_avg = {
        cand: float(monthly_ret.loc[worst_growth.index, cand].mean())
        for cand in CANDIDATES
    }
    worst_growth_positive_months = {
        cand: int((monthly_ret.loc[worst_growth.index, cand] > 0).sum())
        for cand in CANDIDATES
    }

    stress_result = {
        "test": "RSP vs EINC vs USAI correlation and downside-stress diagnostic under canonical v10.29 architecture",
        "method": {
            "canon": "09.30.2026_v.10.29",
            "daily_data_source": "yfinance adjusted close",
            "requested_start": START_REQUEST,
            "common_daily_start": str(daily_start.date()),
            "common_daily_end": str(daily_end.date()),
            "daily_observations": int(len(daily_ret)),
            "growth_sleeve_proxy": "canonical v10.29 growth targets normalized from 81% to 100% within the sleeve",
            "portfolio_monthly_proxy": "fixed canonical target weights; only the 7% RSP/EINC/USAI sleeve changes; 1% operating cash assumed 0% monthly return",
            "rolling_windows": ["60 trading days", "120 trading days"],
            "downside_correlation": "daily correlation conditional on benchmark daily return < 0",
            "downside_capture": "candidate mean monthly return divided by benchmark mean monthly return in benchmark-negative months, x100",
            "beta": "daily covariance(candidate, benchmark) / variance(benchmark)",
        },
        "correlation": correlation,
        "worst_growth_sleeve_months": worst_growth_months,
        "worst_growth_sleeve_month_average_candidate_returns": worst_growth_avg,
        "worst_growth_sleeve_month_positive_counts": worst_growth_positive_months,
        "baseline_portfolio_worst_months_fixed_target_proxy": worst_portfolio_months,
        "limitations": [
            "Correlation is descriptive, not causal, and changes through time.",
            "The daily stress test uses fixed target weights for the growth-sleeve and portfolio proxies; it is a diversification diagnostic, not a replacement for the monthly smart-refill engine.",
            "Current 2026 holdings are applied retrospectively, creating survivorship/selection bias.",
            "The common history is constrained by the newest current holding and any newer ETF history; a short common window can make rolling statistics fragile.",
            "Downside capture is sample-sensitive because the number and severity of negative months are limited.",
            "A lower correlation alone is not sufficient reason to replace RSP; implementation quality, liquidity, cost, holdings, mandate, and persistence across regimes still matter.",
        ],
    }

    df.reset_index().to_csv(OUT / "rsp_replacement_summary.csv", index=False)
    pd.DataFrame(target_rows).to_csv(OUT / "rsp_replacement_targets.csv", index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / "rsp_replacement_trades.csv", index=False)
    portfolio_proxy.reset_index().to_csv(OUT / "correlation_stress_portfolio_monthly.csv", index=False)
    monthly_ret[["RSP", "EINC", "USAI", "SPY"]].assign(
        GROWTH_SLEEVE=growth_monthly
    ).reset_index().to_csv(OUT / "correlation_stress_monthly_returns.csv", index=False)

    combined = {
        "smart_refill_backtest": {
            "common_start": str(common_start.date()),
            "common_end": str(common_end.date()),
            "results": df.reset_index().to_dict(orient="records"),
            "deltas_vs_current_rsp": deltas,
        },
        "stress_test": stress_result,
    }
    (OUT / "correlation_stress_results.json").write_text(json.dumps(combined, indent=2))

    print("CORRELATION STRESS TEST")
    print("MONTHLY ENGINE WINDOW", common_start.date(), "to", common_end.date())
    print("DAILY STRESS WINDOW", daily_start.date(), "to", daily_end.date())
    print("\nSMART-REFILL BACKTEST")
    print(df.to_string())
    print("\nCORRELATION METRICS")
    print(json.dumps(correlation, indent=2))
    print("\nWORST GROWTH-SLEEVE MONTHS")
    print(json.dumps(worst_growth_months, indent=2))
    print("\nBASELINE PORTFOLIO WORST MONTHS")
    print(json.dumps(worst_portfolio_months, indent=2))


if __name__ == "__main__":
    main()
