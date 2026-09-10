import argparse, json, math
from pathlib import Path
import numpy as np, pandas as pd, yfinance as yf

DEFENSE={'RSP':.07,'SGOV':.08,'GLD':.03}
CASH=.01
GROWTH={'NVDA':.155,'ORCL':.05,'AAOI':.05,'LITE':.035,'MU':.105,'MRVL':.04,'QCOM':.095,'VRT':.05,'NBIS':.04,'BE':.025,'GEV':.025,'LEU':.03,'MP':.03,'FCX':.03,'PLTR':.025,'NET':.025}
TARGETS={**DEFENSE,**GROWTH}
BENCH=['SPY','QQQ']
DRIFT=.10
FEE=.0005

assert abs(sum(TARGETS.values())+CASH-1)<1e-9

def rank_hi(s):
    s=pd.Series(s,dtype=float).replace([np.inf,-np.inf],np.nan)
    return s.rank(pct=True).fillna(.5)

def rank_lo(s):
    s=pd.Series(s,dtype=float).replace([np.inf,-np.inf],np.nan)
    return s.rank(pct=True,ascending=False).fillna(.5)

def load_prices(start):
    tickers=list(TARGETS)+BENCH
    x=yf.download(tickers,start=start,auto_adjust=True,progress=False,threads=True,group_by='ticker')
    d={}
    for t in tickers:
        try:d[t]=x[t]['Close']
        except:pass
    p=pd.DataFrame(d)
    p.index=pd.to_datetime(p.index).tz_localize(None)
    return p.resample('ME').last().ffill()

def load_earnings():
    out={}
    for i,t in enumerate(GROWTH,1):
        print(f'earnings {i}/{len(GROWTH)} {t}',flush=True)
        try:
            e=yf.Ticker(t).get_earnings_history()
            if e is None or len(e)==0:
                out[t]=pd.DataFrame(); continue
            e=e.copy(); e.index=pd.to_datetime(e.index).tz_localize(None).normalize(); e=e.sort_index()
            keep=[c for c in ['epsEstimate','epsActual','surprisePercent'] if c in e.columns]
            out[t]=e[keep]
        except Exception:
            out[t]=pd.DataFrame()
    return out

def factors(date,tickers,earnings,prices):
    biz={}; val={}
    for t in tickers:
        e=earnings.get(t,pd.DataFrame()); e=e[e.index<=date] if not e.empty else e
        growth=np.nan; surprise=np.nan; ttm=np.nan
        if not e.empty and 'epsActual' in e:
            a=pd.to_numeric(e.epsActual,errors='coerce').dropna()
            if len(a)>=4: ttm=a.iloc[-4:].sum()
            if len(a)>=8:
                now=a.iloc[-4:].sum(); old=a.iloc[-8:-4].sum(); growth=(now-old)/max(abs(now),abs(old),.25)
            elif len(a)>=5:
                growth=(a.iloc[-1]-a.iloc[-5])/max(abs(a.iloc[-1]),abs(a.iloc[-5]),.25)
        if not e.empty and 'surprisePercent' in e:
            s=pd.to_numeric(e.surprisePercent,errors='coerce').dropna()
            if len(s): surprise=s.iloc[-min(2,len(s)):].mean()/100
        vals=[v for v in [growth,surprise] if pd.notna(v)]
        biz[t]=np.mean(vals) if vals else np.nan
        price=prices.loc[date,t]; val[t]=price/ttm if pd.notna(ttm) and ttm>0 else np.nan
    return rank_hi(biz),rank_lo(val)

def stats(r):
    r=pd.Series(r,dtype=float).dropna(); wealth=(1+r).cumprod(); dd=wealth/wealth.cummax()-1
    ann=wealth.iloc[-1]**(12/len(r))-1; vol=r.std()*math.sqrt(12)
    sharpe=(r.mean()/r.std()*math.sqrt(12)) if r.std()>0 else np.nan
    dn=r[r<0].std(); sortino=(r.mean()/dn*math.sqrt(12)) if pd.notna(dn) and dn>0 else np.nan
    return {'ann_return':ann,'ann_vol':vol,'sharpe':sharpe,'sortino':sortino,'max_drawdown':dd.min(),'worst_month':r.min()}

def run(name,prices,earnings,targets,mode,initial,monthly,cash_target,growth_names):
    tks=list(targets); start=max(prices[t].first_valid_index() for t in tks); p=prices[tks].loc[start:].dropna()
    sh={t:0. for t in tks}; cash=initial; rets=[]; trades=[]; d0=p.index[0]
    for t,w in targets.items():
        dollars=initial*w; sh[t]+=dollars*(1-FEE)/p.loc[d0,t]; cash-=dollars
    prev=cash+sum(sh[t]*p.loc[d0,t] for t in tks)
    for d in p.index[1:]:
        pre=cash+sum(sh[t]*p.loc[d,t] for t in tks); rets.append(pre/prev-1); cash+=monthly
        total=cash+sum(sh[t]*p.loc[d,t] for t in tks)
        for t,w in targets.items():
            v=sh[t]*p.loc[d,t]; wt=v/total
            if wt>w*(1+DRIFT):
                sell=v-w*total; sh[t]-=sell/p.loc[d,t]; cash+=sell*(1-FEE); trades.append((d,t,'SELL',sell))
        total=cash+sum(sh[t]*p.loc[d,t] for t in tks); floor=cash_target*total; deploy=max(0,cash-floor)
        gaps={t:max(0,targets[t]*total-sh[t]*p.loc[d,t]) for t in tks}
        if mode=='proportional':
            g=sum(gaps.values())
            if g>0:
                for t in tks:
                    amt=min(deploy*gaps[t]/g,gaps[t]); sh[t]+=amt*(1-FEE)/p.loc[d,t]; cash-=amt; trades.append((d,t,'BUY',amt))
            order=[]
        elif mode=='benchmark': order=tks
        else:
            for t in [x for x in tks if x not in growth_names]:
                total=cash+sum(sh[x]*p.loc[d,x] for x in tks); floor=cash_target*total; dep=max(0,cash-floor)
                gap=max(0,targets[t]*total-sh[t]*p.loc[d,t]); amt=min(dep,gap)
                if amt>0: sh[t]+=amt*(1-FEE)/p.loc[d,t]; cash-=amt; trades.append((d,t,'BUY',amt))
            total=cash+sum(sh[x]*p.loc[d,x] for x in tks); gaps={t:max(0,targets[t]*total-sh[t]*p.loc[d,t]) for t in growth_names if t in tks}; cand=[t for t,g in gaps.items() if g>1e-8]
            if cand:
                b,v=factors(d,cand,earnings,prices); under={t:gaps[t]/(targets[t]*total) for t in cand}; u=rank_hi(under); score=.5*b+.3*v+.2*u; order=list(score.sort_values(ascending=False).index)
            else: order=[]
        if mode in ('smart','benchmark'):
            for t in order:
                total=cash+sum(sh[x]*p.loc[d,x] for x in tks); floor=cash_target*total; dep=max(0,cash-floor)
                gap=max(0,targets[t]*total-sh[t]*p.loc[d,t]); amt=min(dep,gap)
                if amt>0: sh[t]+=amt*(1-FEE)/p.loc[d,t]; cash-=amt; trades.append((d,t,'BUY',amt))
        prev=cash+sum(sh[t]*p.loc[d,t] for t in tks)
    s=stats(rets); s['ending_value']=prev; s['months']=len(rets); return name,s,pd.DataFrame(trades,columns=['date','ticker','side','dollars'])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--start',default='2024-01-01'); ap.add_argument('--initial',type=float,default=500); ap.add_argument('--monthly',type=float,default=200); ap.add_argument('--output',default='macro-backtest/results'); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True); prices=load_prices(args.start); earnings=load_earnings()
    equal={**DEFENSE,**{t:.81/len(GROWTH) for t in GROWTH}}; nodef={t:w/.81 for t,w in GROWTH.items()}
    runs=[]; logs=[]
    specs=[('V08_SMART',TARGETS,'smart',CASH,list(GROWTH)),('V08_PROPORTIONAL',TARGETS,'proportional',CASH,list(GROWTH)),('EQUAL_GROWTH_SMART',equal,'smart',CASH,list(GROWTH)),('NO_DEFENSE_SMART',nodef,'smart',0,list(GROWTH)),('SPY',{'SPY':1},'benchmark',0,['SPY']),('QQQ',{'QQQ':1},'benchmark',0,['QQQ'])]
    for spec in specs:
        n,s,l=run(spec[0],prices,earnings,spec[1],spec[2],args.initial,args.monthly,spec[3],spec[4]); runs.append({'strategy':n,**s}); l['strategy']=n; logs.append(l)
    df=pd.DataFrame(runs); df.to_csv(out/'summary.csv',index=False); pd.concat(logs,ignore_index=True).to_csv(out/'trades.csv',index=False); s=df.set_index('strategy')
    verdict={'weighting':'YES' if s.loc['V08_SMART','ann_return']>s.loc['EQUAL_GROWTH_SMART','ann_return'] else 'NO','refill':'YES' if s.loc['V08_SMART','ann_return']>s.loc['V08_PROPORTIONAL','ann_return'] else 'NO','defense':'YES' if abs(s.loc['V08_SMART','max_drawdown'])<abs(s.loc['NO_DEFENSE_SMART','max_drawdown']) else 'NO'}
    result={'verdicts':verdict,'summary':df.to_dict(orient='records'),'notes':['Universe held fixed to current v08 holdings; this tests mechanics, not historical stock selection.','Smart refill uses only earnings information available by each simulated month and trailing P/E from historical price / trailing reported EPS.']}; (out/'results.json').write_text(json.dumps(result,indent=2))
    rows=''.join(f"<tr><td>{r['strategy']}</td><td>{r['ann_return']:.1%}</td><td>{r['max_drawdown']:.1%}</td><td>{r['sortino']:.2f}</td><td>${r['ending_value']:,.0f}</td></tr>" for r in runs)
    html=f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>MACRO v08 Backtest</title><style>body{{font-family:system-ui;background:#0b0d10;color:#eee;max-width:900px;margin:40px auto;padding:0 20px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}.c{{background:#151a20;padding:18px;border-radius:14px}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:10px;border-bottom:1px solid #333;text-align:right}}td:first-child,th:first-child{{text-align:left}}b{{font-size:28px}}</style><h1>MACRO v08 Backtest</h1><p>$500 start · $200/month · same holdings</p><div class="cards"><div class="c">Do v08 weights help?<br><b>{verdict['weighting']}</b></div><div class="c">Does smart refill help?<br><b>{verdict['refill']}</b></div><div class="c">Does 19% defense reduce drawdown?<br><b>{verdict['defense']}</b></div></div><table><tr><th>Strategy</th><th>Annual return</th><th>Max drawdown</th><th>Sortino</th><th>Ending value</th></tr>{rows}</table><p><small>Important: current v08 holdings are held fixed historically, so this tests portfolio mechanics, not whether those exact stocks could have been selected with no hindsight.</small></p>'''; (out/'index.html').write_text(html)
    print(df.to_string(index=False)); print('VERDICTS',verdict)
if __name__=='__main__': main()
