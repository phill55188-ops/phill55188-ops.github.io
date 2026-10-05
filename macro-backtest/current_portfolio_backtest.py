import json
from pathlib import Path
import pandas as pd
import backtest as bt
from defense_mix_test import CURRENT_GROWTH

OUT=Path("macro-backtest/results-current-portfolio")
OUT.mkdir(parents=True,exist_ok=True)

CANON="10.04.2026_v.10.38"
REQUESTED_START="2024-01-01"
CASH=0.01
DEFENSE={"TPYP":0.07,"SGOV":0.08,"GLD":0.03}
TARGETS={**DEFENSE,**CURRENT_GROWTH}

def main():
    assert abs(sum(CURRENT_GROWTH.values())-0.81)<1e-10
    assert abs(sum(DEFENSE.values())-0.18)<1e-10
    assert abs(sum(TARGETS.values())+CASH-1.0)<1e-10

    bt.GROWTH=dict(CURRENT_GROWTH)
    bt.TARGETS=dict(TARGETS)
    prices=bt.load_prices(REQUESTED_START)
    earnings=bt.load_earnings()

    missing=[t for t in TARGETS if t not in prices.columns or prices[t].first_valid_index() is None]
    if missing:
        raise RuntimeError(f"RUN INVALID — missing historical monthly data: {missing}")

    common_start=max(prices[t].first_valid_index() for t in TARGETS)
    common_end=min(prices[t].last_valid_index() for t in TARGETS)

    required=list(TARGETS)+["SPY","QQQ"]
    missing_bench=[t for t in required if t not in prices.columns or prices[t].first_valid_index() is None]
    if missing_bench:
        raise RuntimeError(f"RUN INVALID — missing benchmark data: {missing_bench}")

    p=prices.loc[common_start:common_end,required].copy()

    specs=[
        ("CURRENT_CANON_V10_38",TARGETS,"smart",CASH,list(CURRENT_GROWTH)),
        ("SPY",{"SPY":1.0},"benchmark",0.0,["SPY"]),
        ("QQQ",{"QQQ":1.0},"benchmark",0.0,["QQQ"]),
    ]

    rows=[]; logs=[]
    for spec in specs:
        n,s,l=bt.run(spec[0],p,earnings,spec[1],spec[2],500,200,spec[3],spec[4])
        rows.append({"strategy":n,**s})
        l["strategy"]=n; logs.append(l)

    df=pd.DataFrame(rows)
    base=df.set_index("strategy").loc["CURRENT_CANON_V10_38"]
    deltas={}
    for b in ["SPY","QQQ"]:
        r=df.set_index("strategy").loc[b]
        deltas[b]={
            "ann_return_points_portfolio_minus_benchmark":float((base.ann_return-r.ann_return)*100),
            "ann_vol_points_portfolio_minus_benchmark":float((base.ann_vol-r.ann_vol)*100),
            "sharpe_portfolio_minus_benchmark":float(base.sharpe-r.sharpe),
            "sortino_portfolio_minus_benchmark":float(base.sortino-r.sortino),
            "max_drawdown_points_portfolio_minus_benchmark":float((base.max_drawdown-r.max_drawdown)*100),
            "worst_month_points_portfolio_minus_benchmark":float((base.worst_month-r.worst_month)*100),
            "ending_value_portfolio_minus_benchmark":float(base.ending_value-r.ending_value),
        }

    first_dates={t:str(prices[t].first_valid_index().date()) for t in TARGETS}
    constraining=[t for t,d in first_dates.items() if d==str(common_start.date())]

    result={
        "canon":CANON,
        "test_type":"COMMON_WINDOW_ARCHITECTURE",
        "information_set":"Current v10.37 canonical target architecture applied retrospectively for mechanics/allocation comparison. Same monthly window and contribution assumptions used for portfolio, SPY, and QQQ.",
        "requested_start":REQUESTED_START,
        "actual_start":str(common_start.date()),
        "actual_end":str(common_end.date()),
        "start_reason":"first common monthly observation available across every current canonical holding",
        "constraining_series":constraining,
        "bias_classification":"RETROSPECTIVE SELECTION / SURVIVORSHIP EXPOSURE — current 2026 universe is projected backward. Use this test for mechanics/relative architecture, not proof that today's universe was selectable at the start.",
        "controls":{
            "initial_capital":500,
            "monthly_contribution":200,
            "fee":bt.FEE,
            "drift_threshold":bt.DRIFT,
            "cash_target":CASH,
            "growth_sleeve":0.81,
            "defensive_assets":0.18,
            "price_data":"adjusted monthly-last yfinance data",
            "refill":"canonical smart-refill proxy for portfolio; benchmark buy-and-hold/refill through same engine",
        },
        "targets":TARGETS,
        "results":df.to_dict(orient="records"),
        "deltas_vs_benchmarks":deltas,
        "limitations":[
            "Current 2026 holdings are applied retrospectively, creating survivorship/selection bias.",
            "The common sample is constrained by the newest current holding(s); absolute annualized returns are not forward forecasts.",
            "Smart refill uses lagged reported earnings/surprise and trailing historical P/E proxies for some live forward-estimate inputs.",
            "Internal Sortino is methodology-specific and intended for within-engine comparison.",
        ],
    }
    (OUT/"current_portfolio_results.json").write_text(json.dumps(result,indent=2))
    df.to_csv(OUT/"current_portfolio_summary.csv",index=False)
    pd.concat(logs,ignore_index=True).to_csv(OUT/"current_portfolio_trades.csv",index=False)
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    main()
