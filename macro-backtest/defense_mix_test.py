import json
from pathlib import Path

import pandas as pd

import backtest as bt
import orchestration_split_test as ost

OUT = Path("macro-backtest/results-defense-mix")
OUT.mkdir(parents=True, exist_ok=True)

GROWTH_SLEEVE = 0.81
CASH = 0.01
SATELLITES = {"ADBE", "TSM", "SNPS"}
FN_GRID = [0.02, 0.03, 0.04, 0.05]


def direct_fn_replacement(current_growth):
    growth = dict(current_growth)
    aaoi_weight = growth.pop("AAOI")
    growth["FN"] = aaoi_weight
    assert abs(sum(growth.values()) - GROWTH_SLEEVE) < 1e-10
    return growth


def global_reweight(base_fn, fn_weight):
    growth = {}
    for t in SATELLITES:
        growth[t] = base_fn[t]

    backbone = [t for t in base_fn if t not in SATELLITES and t != "FN"]
    available = GROWTH_SLEEVE - sum(growth.values()) - fn_weight
    denom = sum(base_fn[t] for t in backbone)
    scale = available / denom

    for t in backbone:
        growth[t] = base_fn[t] * scale
    growth["FN"] = fn_weight

    assert abs(sum(growth.values()) - GROWTH_SLEEVE) < 1e-10
    assert max(growth.values()) <= 0.10 + 1e-10
    return growth


def optics_reweight(base_fn, fn_weight):
    growth = dict(base_fn)
    network_total = base_fn["FN"] + base_fn["LITE"] + base_fn["MRVL"]
    remaining = network_total - fn_weight
    if remaining <= 0:
        raise ValueError("FN weight consumes the networking/optics sleeve.")
    lite_mrvl_total = base_fn["LITE"] + base_fn["MRVL"]
    growth["FN"] = fn_weight
    growth["LITE"] = remaining * base_fn["LITE"] / lite_mrvl_total
    growth["MRVL"] = remaining * base_fn["MRVL"] / lite_mrvl_total

    assert abs(sum(growth.values()) - GROWTH_SLEEVE) < 1e-10
    assert max(growth.values()) <= 0.10 + 1e-10
    return growth


def main():
    current_growth, _ = ost.current_overlay_targets()
    assert "AAOI" in current_growth
    assert abs(sum(current_growth.values()) - GROWTH_SLEEVE) < 1e-10

    base_fn = direct_fn_replacement(current_growth)
    aaoi_weight = current_growth["AAOI"]

    specs = [("BASE_AAOI_CURRENT", current_growth)]
    specs.append(("FN_DIRECT_LAYER_EQ", base_fn))
    for w in FN_GRID:
        if abs(w - aaoi_weight) > 1e-8:
            specs.append((f"FN_{int(w*100)}_GLOBAL", global_reweight(base_fn, w)))
            specs.append((f"FN_{int(w*100)}_OPTICS", optics_reweight(base_fn, w)))

    all_growth = sorted(set().union(*(set(g) for _, g in specs)))
    bt.GROWTH = {ticker: 0.01 for ticker in all_growth}
    bt.TARGETS = {**bt.DEFENSE, **bt.GROWTH}

    prices = bt.load_prices("2024-01-01")
    earnings = bt.load_earnings()

    rows = []
    logs = []
    target_rows = []

    for name, growth in specs:
        targets = {**bt.DEFENSE, **growth}
        assert abs(sum(targets.values()) + CASH - 1.0) < 1e-10

        n, s, l = bt.run(
            name,
            prices,
            earnings,
            targets,
            "smart",
            500,
            200,
            CASH,
            list(growth),
        )
        rows.append({"strategy": n, **s})
        l["strategy"] = n
        logs.append(l)

        for ticker, weight in sorted(targets.items(), key=lambda kv: kv[1], reverse=True):
            target_rows.append({
                "strategy": name,
                "ticker": ticker,
                "target_weight": weight,
                "target_percent": weight * 100,
            })

    df = pd.DataFrame(rows).set_index("strategy")
    base = df.loc["BASE_AAOI_CURRENT"]
    direct = df.loc["FN_DIRECT_LAYER_EQ"]

    deltas_base = {}
    deltas_direct = {}
    for name in df.index:
        r = df.loc[name]
        deltas_base[name] = {
            "ann_return_points": float((r.ann_return - base.ann_return) * 100),
            "ann_vol_points": float((r.ann_vol - base.ann_vol) * 100),
            "sharpe": float(r.sharpe - base.sharpe),
            "sortino": float(r.sortino - base.sortino),
            "max_drawdown_points": float((r.max_drawdown - base.max_drawdown) * 100),
            "worst_month_points": float((r.worst_month - base.worst_month) * 100),
            "ending_value": float(r.ending_value - base.ending_value),
        }
        deltas_direct[name] = {
            "ann_return_points": float((r.ann_return - direct.ann_return) * 100),
            "ann_vol_points": float((r.ann_vol - direct.ann_vol) * 100),
            "sharpe": float(r.sharpe - direct.sharpe),
            "sortino": float(r.sortino - direct.sortino),
            "max_drawdown_points": float((r.max_drawdown - direct.max_drawdown) * 100),
            "worst_month_points": float((r.worst_month - direct.worst_month) * 100),
            "ending_value": float(r.ending_value - direct.ending_value),
        }

    fn_df = df.drop(index="BASE_AAOI_CURRENT").copy()
    fn_df["composite_score"] = (
        fn_df["ann_return"].rank(pct=True) * 0.40
        + fn_df["sortino"].rank(pct=True) * 0.35
        + (-fn_df["max_drawdown"].abs()).rank(pct=True) * 0.25
    )
    ranked = fn_df.sort_values(
        ["composite_score", "ann_return", "sortino", "max_drawdown"],
        ascending=[False, False, False, False],
    )
    winner = ranked.index[0]

    df.reset_index().to_csv(OUT / "fn_allocation_summary.csv", index=False)
    pd.DataFrame(target_rows).to_csv(OUT / "fn_allocation_targets.csv", index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / "fn_allocation_trades.csv", index=False)

    result = {
        "test": "AAOI-to-FN replacement allocation sensitivity under canonical v10.26 architecture",
        "method": {
            "canon": "09.30.2026_v.10.26",
            "growth_sleeve": GROWTH_SLEEVE,
            "defense": bt.DEFENSE,
            "cash_target": CASH,
            "same_engine": True,
            "same_smart_refill": True,
            "same_price_dataset": True,
            "same_initial_capital": 500,
            "same_monthly_contribution": 200,
            "start_request": "2024-01-01",
            "satellites_fixed": {"ADBE": 0.02, "TSM": 0.02, "SNPS": 0.02},
            "fn_weights_tested": [2, 3, round(aaoi_weight * 100, 4), 4, 5],
            "global_method": "Fix FN target; preserve ADBE/TSM/SNPS at 2% each; scale all other dependency-backbone names pro-rata.",
            "optics_method": "Fix FN target; preserve every non-optics target; keep total FN+LITE+MRVL networking/optics sleeve unchanged and split the remainder between LITE and MRVL in their existing ratio.",
            "direct_method": "Replace AAOI with FN one-for-one at AAOI's existing canonical target; all other targets unchanged.",
            "composite": "40% annual-return percentile + 35% internal-Sortino percentile + 25% shallow-drawdown percentile, matching the existing dependency architecture test convention.",
        },
        "results": df.reset_index().to_dict(orient="records"),
        "deltas_vs_aaoi_current": deltas_base,
        "deltas_vs_fn_direct": deltas_direct,
        "fn_composite_ranking": ranked.reset_index()[["strategy", "composite_score", "ann_return", "ann_vol", "sharpe", "sortino", "max_drawdown", "worst_month", "ending_value", "months"]].to_dict(orient="records"),
        "winner": winner,
        "winner_targets": dict(specs[[n for n, _ in specs].index(winner)][1]),
        "all_targets": {name: growth for name, growth in specs},
        "limitations": [
            "Current 2026 holdings are applied retrospectively, creating survivorship/selection bias.",
            "The common sample remains constrained by the newest holding history and is short; absolute annualized returns are not forward forecasts.",
            "Smart refill uses lagged reported earnings/surprise and trailing historical P/E as a proxy for the live forward-estimate ranking rule.",
            "The engine's internal Sortino is methodology-specific and is only valid for within-engine comparison.",
            "FN is a currently selected replacement candidate applied retrospectively; this test can compare allocation mechanics but cannot prove that FN would have been selected historically without hindsight.",
            "A narrow historical winner should not override the dependency architecture unless improvements are broad enough to survive judgment outside this sample."
        ],
    }
    (OUT / "fn_allocation_results.json").write_text(json.dumps(result, indent=2))

    print("FN ALLOCATION TEST")
    print(df.to_string())
    print("\nFN COMPOSITE RANKING")
    print(ranked.to_string())
    print("\nWINNER", winner)
    print("\nWINNER TARGETS")
    for t, w in sorted(result["winner_targets"].items(), key=lambda kv: kv[1], reverse=True):
        print(f"{t:5s} {w*100:7.4f}%")


if __name__ == "__main__":
    main()
