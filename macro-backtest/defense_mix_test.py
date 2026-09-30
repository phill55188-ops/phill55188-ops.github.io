import json
from pathlib import Path

import pandas as pd

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


def main():
    assert abs(sum(CURRENT_GROWTH.values()) - 0.81) < 1e-10

    for name, defense in SCENARIOS.items():
        assert abs(sum(defense.values()) - 0.18) < 1e-10, (name, defense)
        assert abs(sum(defense.values()) + sum(CURRENT_GROWTH.values()) + CASH - 1.0) < 1e-10

    all_defense = set().union(*(set(x) for x in SCENARIOS.values()))
    all_tickers = sorted(set(CURRENT_GROWTH) | all_defense)

    # load_prices reads bt.TARGETS; include every scenario ticker so all three
    # portfolios are forced onto one common historical window.
    bt.GROWTH = dict(CURRENT_GROWTH)
    bt.TARGETS = {t: 0.01 for t in all_tickers}

    prices = bt.load_prices(START_REQUEST)
    earnings = bt.load_earnings()

    missing = [t for t in all_tickers if t not in prices.columns or prices[t].first_valid_index() is None]
    if missing:
        raise RuntimeError(f"RUN INVALID — missing historical price data for: {missing}")

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
    ranking = (
        df.reset_index()
        .sort_values(
            ["ann_return", "sortino", "max_drawdown"],
            ascending=[False, False, False],
        )
        .reset_index(drop=True)
    )

    df.reset_index().to_csv(OUT / "rsp_replacement_summary.csv", index=False)
    pd.DataFrame(target_rows).to_csv(OUT / "rsp_replacement_targets.csv", index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / "rsp_replacement_trades.csv", index=False)

    result = {
        "test": "RSP 7% replacement sensitivity under canonical v10.29 architecture",
        "method": {
            "canon": "09.30.2026_v.10.29",
            "growth_architecture": "FN_2_GLOBAL canonical v10.29 exact engine targets",
            "growth_sleeve": 0.81,
            "defense_assets_total": 0.18,
            "cash_target": CASH,
            "baseline": "RSP 7% + SGOV 8% + GLD 3%",
            "scenario_1": "EINC 7% + SGOV 8% + GLD 3%",
            "scenario_2": "USAI 7% + SGOV 8% + GLD 3%",
            "only_change": "replace the 7% RSP sleeve one-for-one with EINC or USAI",
            "same_engine": True,
            "same_smart_refill": True,
            "same_price_dataset": True,
            "same_common_window": True,
            "same_initial_capital": 500,
            "same_monthly_contribution": 200,
            "same_fee": bt.FEE,
            "same_drift_threshold": bt.DRIFT,
            "start_request": START_REQUEST,
            "common_start": str(common_start.date()),
            "common_end": str(common_end.date()),
        },
        "scenarios": SCENARIOS,
        "results": df.reset_index().to_dict(orient="records"),
        "deltas_vs_current_rsp": deltas,
        "ranking_by_annual_return_then_sortino_then_drawdown": ranking["strategy"].tolist(),
        "limitations": [
            "Current 2026 holdings are applied retrospectively, so survivorship/selection bias remains.",
            "The common sample is forced to begin only when RSP, EINC, USAI, and every current v10.29 holding all have usable data; a recent ETF inception can materially shorten the test.",
            "Absolute annualized returns are not forward forecasts.",
            "Smart refill uses lagged reported earnings/surprise and trailing historical P/E as a proxy for the live forward-estimate ranking rule.",
            "The engine's Sortino is the system's simplified internal variant and should only be compared within this engine unless outside methodology matches.",
            "A narrow historical win does not prove a superior future defensive/diversification sleeve.",
        ],
    }
    (OUT / "rsp_replacement_results.json").write_text(json.dumps(result, indent=2))

    print("RSP REPLACEMENT TEST")
    print("COMMON WINDOW", common_start.date(), "to", common_end.date())
    print(df.to_string())
    print("\nDELTAS VS CURRENT RSP")
    print(json.dumps(deltas, indent=2))
    print("\nRANKING")
    print(
        ranking[
            [
                "strategy",
                "ann_return",
                "ann_vol",
                "sharpe",
                "sortino",
                "max_drawdown",
                "worst_month",
                "ending_value",
                "months",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
