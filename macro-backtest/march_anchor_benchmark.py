import json
from pathlib import Path
import historical_validation as hv

CONFIG=Path("macro-backtest/configs/2026-03-27_pre_bull_run_anchor.json")
OUT=Path("macro-backtest/results-historical-validation/march_2026_anchor_benchmarks.json")

def main():
    cfg=json.loads(CONFIG.read_text())
    all_tickers=sorted(set(cfg["targets"])|{"SPY","QQQ"})
    prices=hv.load_daily_prices(all_tickers,cfg["anchor_date"],cfg.get("end_date"))

    portfolio=hv.run_anchor_forward(prices[list(cfg["targets"])],cfg)
    rows={"MARCH_2026_FROZEN_THESIS":portfolio["metrics"]}

    for ticker in ["SPY","QQQ"]:
        bcfg={
            "anchor_date":cfg["anchor_date"],
            "end_date":cfg.get("end_date"),
            "targets":{ticker:1.0},
            "cash_target":0.0,
            "initial_capital":cfg.get("initial_capital",500),
            "monthly_contribution":0,
            "fee":cfg.get("fee",0.0005),
            "refill_method":"cash_only",
            "max_anchor_slippage_days":7,
            "information_set":f"{ticker} benchmark from the same 2026-03-27 anchor with identical fee and no contributions."
        }
        rows[ticker]=hv.run_anchor_forward(prices[[ticker]],bcfg)["metrics"]

    base=rows["MARCH_2026_FROZEN_THESIS"]
    delta={}
    for ticker in ["SPY","QQQ"]:
        b=rows[ticker]
        delta[ticker]={
            "ann_return_points_portfolio_minus_benchmark":(base["ann_return"]-b["ann_return"])*100,
            "ann_vol_points_portfolio_minus_benchmark":(base["ann_vol"]-b["ann_vol"])*100,
            "sharpe_portfolio_minus_benchmark":base["sharpe"]-b["sharpe"],
            "sortino_portfolio_minus_benchmark":base["sortino"]-b["sortino"],
            "max_drawdown_points_portfolio_minus_benchmark":(base["max_drawdown"]-b["max_drawdown"])*100,
            "worst_month_points_portfolio_minus_benchmark":(base["worst_month"]-b["worst_month"])*100,
            "ending_value_portfolio_minus_benchmark":base["ending_value"]-b["ending_value"]
        }

    result={
        "test_type":"ANCHOR_FORWARD_THESIS",
        "anchor_date":cfg["anchor_date"],
        "information_set":"Frozen March 27, 2026 portfolio versus SPY and QQQ from the identical forward-only anchor. No post-anchor portfolio changes or contributions.",
        "bias_classification":"EX-ANTE / ANCHOR-FORWARD for the frozen portfolio snapshot; benchmarks use the same subsequent period.",
        "results":rows,
        "deltas_vs_benchmarks":delta,
        "limitations":[
            f"Only {base['months']} completed monthly return observations are available, so annualized metrics are highly unstable.",
            "The historical snapshot must be complete to preserve the ex-ante classification.",
            "Internal Sortino is methodology-specific."
        ]
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    main()
