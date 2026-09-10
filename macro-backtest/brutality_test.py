import math
import os
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

from backtest import DEFENSE, CASH, GROWTH, load_earnings, run

# Isolate yfinance cache so concurrent GitHub workflows cannot lock the same sqlite DB.
try:
    yf.set_tz_cache_location('/tmp/yf-cache-brutality')
except Exception:
    pass

START = '2024-01-01'
INITIAL = 500
MONTHLY = 200
CAP = 0.10
BENCH = ['RSP','SGOV','GLD']

LAYERS = {
    'materials_fuel': ['MP','FCX','LEU'],
    'power_infrastructure': ['VRT','BE','GEV'],
    'compute': ['NVDA','QCOM'],
    'memory': ['MU'],
    'networking_optics': ['AAOI','LITE','MRVL'],
    'cloud_edge': ['ORCL','NBIS','NET'],
    'orchestration': ['PLTR'],
}

SCENARIOS = {
    'ALL_NAMES': set(),
    'REMOVE_PLTR': {'PLTR'},
    'REMOVE_MU': {'MU'},
    'REMOVE_PLTR_MU': {'PLTR','MU'},
}


def load_prices(active_growth):
    tickers = list(DEFENSE) + list(active_growth)
    series = {}
    for i, t in enumerate(tickers, 1):
        print(f'price {i}/{len(tickers)} {t}', flush=True)
        x = yf.download(t, start=START, auto_adjust=True, progress=False, threads=False)
        if x is None or x.empty:
            raise RuntimeError(f'No price data for {t}')
        if isinstance(x.columns, pd.MultiIndex):
            c = x['Close'][t] if t in x['Close'].columns else x['Close'].iloc[:,0]
        else:
            c = x['Close']
        series[t] = c
    p = pd.DataFrame(series)
    p.index = pd.to_datetime(p.index).tz_localize(None)
    return p.resample('ME').last().ffill()


def normalize_current(active_growth):
    # Preserve current v08 relative conviction weights among remaining names,
    # then renormalize the growth sleeve back to 81%.
    base = {t: GROWTH[t] for t in active_growth}
    s = sum(base.values())
    g = {t: 0.81 * w / s for t, w in base.items()}
    return {**DEFENSE, **g}


def dependency_base(active_growth):
    # Remove empty layers, then split 81% equally across remaining active layers,
    # and equally among names inside each surviving layer.
    active_layers = {}
    for lname, names in LAYERS.items():
        kept = [t for t in names if t in active_growth]
        if kept:
            active_layers[lname] = kept
    lw = 0.81 / len(active_layers)
    g = {}
    for names in active_layers.values():
        each = lw / len(names)
        for t in names:
            g[t] = each
    return g, active_layers


def cap_and_redistribute(g, cap=CAP):
    base = dict(g)
    out = dict(g)
    for _ in range(100):
        over = {t: max(0.0, out[t] - cap) for t in out}
        excess = sum(over.values())
        if excess < 1e-12:
            break
        for t, x in over.items():
            if x > 0:
                out[t] = cap
        remaining = excess
        while remaining > 1e-12:
            eligible = [t for t in out if out[t] < cap - 1e-12]
            if not eligible:
                raise ValueError(f'Cap {cap:.1%} infeasible for {len(out)} names')
            denom = sum(base[t] for t in eligible)
            moved = 0.0
            for t in eligible:
                proposed = remaining * base[t] / denom
                add = min(proposed, cap - out[t])
                out[t] += add
                moved += add
            if moved < 1e-14:
                raise RuntimeError('redistribution stalled')
            remaining -= moved
    if abs(sum(out.values()) - 0.81) > 1e-8:
        raise RuntimeError(f'bad growth sum {sum(out.values())}')
    return out


def main():
    earnings_all = load_earnings()
    rows = []

    for scenario, removed in SCENARIOS.items():
        active = [t for t in GROWTH if t not in removed]
        prices = load_prices(active)
        earnings = {t: earnings_all.get(t, pd.DataFrame()) for t in active}

        current = normalize_current(active)
        dep_raw, active_layers = dependency_base(active)
        dep_cap = {**DEFENSE, **cap_and_redistribute(dep_raw, CAP)}

        for label, targets in [('V08_NORMALIZED', current), ('DEPENDENCY_CAP_10', dep_cap)]:
            n, s, log = run(
                f'{scenario}__{label}', prices, earnings, targets,
                'smart', INITIAL, MONTHLY, CASH, active
            )
            rows.append({
                'scenario': scenario,
                'removed': ','.join(sorted(removed)) if removed else 'none',
                'strategy': label,
                'active_growth_names': len(active),
                'active_layers': len(active_layers),
                **s,
            })

    df = pd.DataFrame(rows)
    print('\n=== BRUTALITY TEST RESULTS ===')
    print(df[['scenario','strategy','ann_return','max_drawdown','sortino','ending_value','months']].to_string(index=False))

    print('\n=== DEPENDENCY EDGE BY SCENARIO ===')
    for scenario in SCENARIOS:
        sub = df[df.scenario == scenario].set_index('strategy')
        dep = sub.loc['DEPENDENCY_CAP_10']
        cur = sub.loc['V08_NORMALIZED']
        print(
            f"{scenario}: return edge={dep.ann_return-cur.ann_return:+.2%}, "
            f"drawdown improvement={abs(cur.max_drawdown)-abs(dep.max_drawdown):+.2%}, "
            f"Sortino edge={dep.sortino-cur.sortino:+.3f}, "
            f"ending-value edge=${dep.ending_value-cur.ending_value:+,.2f}"
        )

    out = Path('macro-backtest/results-brutality')
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out/'summary.csv', index=False)

if __name__ == '__main__':
    main()
