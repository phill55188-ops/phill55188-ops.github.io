import json
from pathlib import Path
import pandas as pd
import backtest as bt
from defense_mix_test import CURRENT_GROWTH, load_daily_prices, weighted_return_frame, rolling_corr_stats, downside_capture

OUT=Path("macro-backtest/results-defense-mix")
OUT.mkdir(parents=True,exist_ok=True)
CANDS=["RSP","EINC","AMLP","MLPX","MLPA","TPYP"]
FRAC={"RSP":True,"EINC":False,"AMLP":True,"MLPX":True,"MLPA":True,"TPYP":True}
START="2024-01-01"; CASH=0.01

def main():
    tickers=sorted(set(CURRENT_GROWTH)|{"SGOV","GLD"}|set(CANDS))
    bt.GROWTH=dict(CURRENT_GROWTH); bt.TARGETS={t:0.01 for t in tickers}
    p=bt.load_prices(START); e=bt.load_earnings()
    miss=[t for t in tickers if t not in p.columns or p[t].first_valid_index() is None]
    if miss: raise RuntimeError(f"RUN INVALID missing monthly data {miss}")
    start=max(p[t].first_valid_index() for t in tickers); end=min(p[t].last_valid_index() for t in tickers)
    p=p.loc[start:end]
    rows=[]
    for t in CANDS:
        targets={t:0.07,"SGOV":0.08,"GLD":0.03,**CURRENT_GROWTH}
        n,s,_=bt.run(t+"7",p,e,targets,"smart",500,200,CASH,list(CURRENT_GROWTH))
        rows.append({"candidate":t,"fractionable":FRAC[t],**s})
    d=load_daily_prices(set(tickers)|{"SPY"},START)
    ds=max(d[t].first_valid_index() for t in set(tickers)|{"SPY"})
    de=min(d[t].last_valid_index() for t in set(tickers)|{"SPY"})
    d=d.loc[ds:de].ffill().dropna(); dr=d.pct_change().dropna(); mr=d.resample("ME").last().pct_change().dropna()
    gw={t:w/0.81 for t,w in CURRENT_GROWTH.items()}
    gd=weighted_return_frame(dr,gw); gm=weighted_return_frame(mr,gw)
    corr={}
    for t in CANDS:
        corr[t]={
            "fractionable":FRAC[t],
            "vs_spy":rolling_corr_stats(dr[t],dr["SPY"]),
            "vs_growth":rolling_corr_stats(dr[t],gd),
            "downside_capture_spy":downside_capture(mr[t],mr["SPY"]),
            "downside_capture_growth":downside_capture(mr[t],gm)
        }
    worst=gm.nsmallest(min(5,len(gm)))
    stress={t:{"avg_return_worst_growth_months":float(mr.loc[worst.index,t].mean()),"positive_count":int((mr.loc[worst.index,t]>0).sum())} for t in CANDS}
    result={"canon":"10.01.2026_v.10.33","monthly_window":[str(start.date()),str(end.date())],"daily_window":[str(ds.date()),str(de.date())],"results":rows,"correlation":corr,"worst_growth_stress":stress}
    (OUT/"fractional_diversifier_results.json").write_text(json.dumps(result,indent=2))
    pd.DataFrame(rows).to_csv(OUT/"fractional_diversifier_summary.csv",index=False)
    print(pd.DataFrame(rows).to_string(index=False)); print(json.dumps(corr,indent=2)); print(json.dumps(stress,indent=2))
if __name__=="__main__": main()
