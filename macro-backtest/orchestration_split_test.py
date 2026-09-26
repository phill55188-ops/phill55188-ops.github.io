import json
from pathlib import Path

import pandas as pd

import backtest as bt
import dependency_cap_test as dct
import satellite_weight_test as swt

OUT = Path("macro-backtest/results-orchestration")
OUT.mkdir(parents=True, exist_ok=True)

GROWTH_SLEEVE = 0.81
DEFENSE_SLEEVE = 0.19
SATELLITES = {"ADBE": 0.02, "TSM": 0.02, "SNPS": 0.02}


def current_overlay_targets():
    base_growth, _ = dct.dependency_targets(dct.V08_LAYERS, dct.CAP)
    growth, targets = swt.satellite_overlay_targets(base_growth, SATELLITES)
    return growth, targets


def fixed_orchestration_targets(current_growth):
    """Alternative architecture:
    - Orchestration layer is fixed at 10% total: PLTR 8%, ADBE 2%.
    - TSM and SNPS remain fixed 2% strategic starters.
    - All remaining legacy-backbone names preserve their relative weights and
      are scaled pro-rata to fill the rest of the 81% growth sleeve.
    """
    growth = dict(current_growth)
    growth["PLTR"] = 0.08
    growth["ADBE"] = 0.02
    growth["TSM"] = 0.02
    growth["SNPS"] = 0.02

    fixed = {"PLTR", "ADBE", "TSM", "SNPS"}
    legacy = [t for t in growth if t not in fixed]
    legacy_target_total = GROWTH_SLEEVE - sum(growth[t] for t in fixed)
    legacy_current_total = sum(current_growth[t] for t in legacy)
    scale = legacy_target_total / legacy_current_total

    for t in legacy:
        growth[t] = current_growth[t] * scale

    assert abs(sum(growth.values()) - GROWTH_SLEEVE) < 1e-10, sum(growth.values())
    assert abs(growth["PLTR"] + growth["ADBE"] - 0.10) < 1e-10
    assert abs(growth["ADBE"] - 0.02) < 1e-10
    assert abs(growth["TSM"] - 0.02) < 1e-10
    assert abs(growth["SNPS"] - 0.02) < 1e-10
    assert max(growth.values()) <= 0.10 + 1e-10
    return growth, {**bt.DEFENSE, **growth}


def main():
    current_growth, current_targets = current_overlay_targets()
    fixed_growth, fixed_targets = fixed_orchestration_targets(current_growth)

    specs = [
        ("CURRENT_OVERLAY_PLTR_9_2593_ADBE_2", current_growth, current_targets),
        ("FIXED_ORCH_10_PLTR_8_ADBE_2", fixed_growth, fixed_targets),
    ]

    all_growth = sorted(set(current_growth) | set(fixed_growth))
    bt.GROWTH = {ticker: 0.01 for ticker in all_growth}
    bt.TARGETS = {**bt.DEFENSE, **bt.GROWTH}
    prices = bt.load_prices("2024-01-01")
    earnings = bt.load_earnings()

    rows = []
    logs = []
    for name, growth, targets in specs:
        n, s, l = bt.run(
            name,
            prices,
            earnings,
            targets,
            "smart",
            500,
            200,
            bt.CASH,
            list(growth),
        )
        rows.append({"strategy": n, **s})
        l["strategy"] = n
        logs.append(l)

    df = pd.DataFrame(rows).set_index("strategy")
    current = df.loc["CURRENT_OVERLAY_PLTR_9_2593_ADBE_2"]
    fixed = df.loc["FIXED_ORCH_10_PLTR_8_ADBE_2"]

    delta = {
        "ann_return_points_fixed_minus_current": float((fixed.ann_return - current.ann_return) * 100),
        "ann_vol_points_fixed_minus_current": float((fixed.ann_vol - current.ann_vol) * 100),
        "sharpe_fixed_minus_current": float(fixed.sharpe - current.sharpe),
        "sortino_fixed_minus_current": float(fixed.sortino - current.sortino),
        "max_drawdown_points_fixed_minus_current": float((fixed.max_drawdown - current.max_drawdown) * 100),
        "worst_month_points_fixed_minus_current": float((fixed.worst_month - current.worst_month) * 100),
        "ending_value_fixed_minus_current": float(fixed.ending_value - current.ending_value),
    }

    target_rows = []
    for name, growth, targets in specs:
        for ticker, weight in sorted(targets.items(), key=lambda kv: kv[1], reverse=True):
            target_rows.append({
                "strategy": name,
                "ticker": ticker,
                "target_weight": weight,
                "target_percent": weight * 100,
            })

    df.reset_index().to_csv(OUT / "orchestration_split_summary.csv", index=False)
    pd.DataFrame(target_rows).to_csv(OUT / "orchestration_split_targets.csv", index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / "orchestration_split_trades.csv", index=False)

    result = {
        "test": "Current v10.16 overlay vs fixed 10% orchestration-layer allocation",
        "method": {
            "current": "ADBE/TSM/SNPS each 2%; original v08 growth backbone scaled pro-rata into remaining 75% growth sleeve",
            "alternative": "PLTR 8% + ADBE 2% = fixed 10% orchestration layer; TSM and SNPS remain 2% each; all other legacy backbone names scaled pro-rata to preserve 81% growth sleeve",
            "same_engine": True,
            "same_smart_refill": True,
            "same_price_dataset": True,
            "same_common_window": True,
            "same_initial_capital": 500,
            "same_monthly_contribution": 200,
            "same_defensive_sleeve": DEFENSE_SLEEVE,
            "same_growth_sleeve": GROWTH_SLEEVE,
            "same_single_stock_cap": 0.10,
            "only_architectural_change": "reduce total orchestration allocation from 11.2593% to 10.0% by moving PLTR from ~9.2593% to 8.0%; redistribute released 1.2593% pro-rata across the non-orchestration legacy backbone"
        },
        "results": df.reset_index().to_dict(orient="records"),
        "delta_fixed_minus_current": delta,
        "targets": {
            "current": current_targets,
            "fixed_orchestration_10": fixed_targets,
        },
        "limitations": [
            "Current 2026 holdings are applied retrospectively, so survivorship/selection bias remains.",
            "Smart refill uses lagged reported earnings/surprise and trailing historical P/E as a proxy for the live forward-estimate ranking rule.",
            "The common sample is constrained by NBIS and is short; absolute annualized returns are not expected future returns.",
            "This comparison is intended to isolate allocation architecture, not forecast PLTR or ADBE."
        ],
    }
    (OUT / "orchestration_split_results.json").write_text(json.dumps(result, indent=2))

    print("TARGET CHECK")
    print(f"Current PLTR: {current_growth['PLTR']*100:.4f}%")
    print(f"Current ADBE: {current_growth['ADBE']*100:.4f}%")
    print(f"Current orchestration total: {(current_growth['PLTR']+current_growth['ADBE'])*100:.4f}%")
    print(f"Fixed PLTR: {fixed_growth['PLTR']*100:.4f}%")
    print(f"Fixed ADBE: {fixed_growth['ADBE']*100:.4f}%")
    print(f"Fixed orchestration total: {(fixed_growth['PLTR']+fixed_growth['ADBE'])*100:.4f}%")
    print("\nRESULTS")
    print(df.to_string())
    print("\nFIXED MINUS CURRENT")
    print(json.dumps(delta, indent=2))


if __name__ == "__main__":
    main()
