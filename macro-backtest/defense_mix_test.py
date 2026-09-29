import json
from pathlib import Path

import pandas as pd

import backtest as bt
import orchestration_split_test as ost

OUT = Path("macro-backtest/results-defense-mix")
OUT.mkdir(parents=True, exist_ok=True)

CASH = 0.01

SCENARIOS = {
    "CURRENT_RSP7_SGOV8_GLD3": {"RSP": 0.07, "SGOV": 0.08, "GLD": 0.03},
    "GLD2_SGOV9_RSP7": {"RSP": 0.07, "SGOV": 0.09, "GLD": 0.02},
    "GLD2_RSP8_SGOV8": {"RSP": 0.08, "SGOV": 0.08, "GLD": 0.02},
    "GLD1_SGOV9_RSP8": {"RSP": 0.08, "SGOV": 0.09, "GLD": 0.01},
    "GLD5_SGOV7_RSP6": {"RSP": 0.06, "SGOV": 0.07, "GLD": 0.05},
}

def main():
    current_growth, _ = ost.current_overlay_targets()

    assert abs(sum(current_growth.values()) - 0.81) < 1e-10
    for name, defense in SCENARIOS.items():
        assert abs(sum(defense.values()) - 0.18) < 1e-10, (name, defense)
        assert abs(sum(defense.values()) + sum(current_growth.values()) + CASH - 1.0) < 1e-10

    all_tickers = sorted(set(current_growth) | {"RSP", "SGOV", "GLD"})
    bt.GROWTH = dict(current_growth)
    bt.TARGETS = {t: 0.01 for t in all_tickers}

    prices = bt.load_prices("2024-01-01")
    earnings = bt.load_earnings()

    rows = []
    logs = []
    target_rows = []

    for name, defense in SCENARIOS.items():
        targets = {**defense, **current_growth}
        n, s, l = bt.run(
            name,
            prices,
            earnings,
            targets,
            "smart",
            500,
            200,
            CASH,
            list(current_growth),
        )
        rows.append({"strategy": n, **s})
        l["strategy"] = n
        logs.append(l)

        for ticker, weight in targets.items():
            target_rows.append({
                "strategy": name,
                "ticker": ticker,
                "target_weight": weight,
                "target_percent": weight * 100,
            })

    df = pd.DataFrame(rows).set_index("strategy")
    base = df.loc["CURRENT_RSP7_SGOV8_GLD3"]

    deltas = {}
    for name in df.index:
        r = df.loc[name]
        deltas[name] = {
            "ann_return_points_vs_current": float((r.ann_return - base.ann_return) * 100),
            "ann_vol_points_vs_current": float((r.ann_vol - base.ann_vol) * 100),
            "sharpe_vs_current": float(r.sharpe - base.sharpe),
            "sortino_vs_current": float(r.sortino - base.sortino),
            "max_drawdown_points_vs_current": float((r.max_drawdown - base.max_drawdown) * 100),
            "worst_month_points_vs_current": float((r.worst_month - base.worst_month) * 100),
            "ending_value_vs_current": float(r.ending_value - base.ending_value),
        }

    ranked = df.reset_index().sort_values(
        ["ann_return", "sortino", "max_drawdown"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    df.reset_index().to_csv(OUT / "defense_mix_summary.csv", index=False)
    pd.DataFrame(target_rows).to_csv(OUT / "defense_mix_targets.csv", index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / "defense_mix_trades.csv", index=False)

    result = {
        "test": "Current v10.22 defensive-mix comparison",
        "method": {
            "canon": "09.28.2026_v.10.22",
            "growth_architecture": "current dependency backbone + ADBE/TSM/SNPS 2% strategic-starter overlay",
            "growth_sleeve": 0.81,
            "defense_assets_total": 0.18,
            "cash_target": CASH,
            "total_defensive_liquidity": 0.19,
            "same_engine": True,
            "same_smart_refill": True,
            "same_price_dataset": True,
            "same_common_window": True,
            "same_initial_capital": 500,
            "same_monthly_contribution": 200,
            "start_request": "2024-01-01",
            "only_change": "RSP/SGOV/GLD target split",
        },
        "scenarios": SCENARIOS,
        "results": df.reset_index().to_dict(orient="records"),
        "deltas_vs_current": deltas,
        "ranking_by_annual_return_then_sortino_then_drawdown": ranked["strategy"].tolist(),
        "limitations": [
            "Current 2026 holdings are applied retrospectively, so survivorship/selection bias remains.",
            "The common sample is constrained by the newest holding history and is short; absolute annualized returns are not forward forecasts.",
            "Smart refill uses lagged reported earnings/surprise and trailing historical P/E as a proxy for the live forward-estimate ranking rule.",
            "The engine's Sortino is the system's simplified internal variant and should only be compared within this engine unless outside methodology matches.",
        ],
    }
    (OUT / "defense_mix_results.json").write_text(json.dumps(result, indent=2))

    print("DEFENSE MIX TARGETS")
    for name, defense in SCENARIOS.items():
        print(name, defense)
    print("\nRESULTS")
    print(df.to_string())
    print("\nDELTAS VS CURRENT")
    print(json.dumps(deltas, indent=2))
    print("\nRANKING")
    print(ranked[["strategy", "ann_return", "ann_vol", "sharpe", "sortino", "max_drawdown", "worst_month", "ending_value"]].to_string(index=False))

if __name__ == "__main__":
    main()
