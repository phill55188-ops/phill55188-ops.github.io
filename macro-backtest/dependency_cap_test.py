import json
from pathlib import Path
import pandas as pd

from backtest import DEFENSE, CASH, GROWTH, load_prices, load_earnings, run
from weighting_test import dependency_layer_growth

OUT = Path('macro-backtest/results-dependency-caps')
OUT.mkdir(parents=True, exist_ok=True)
CAPS = [0.065, 0.075, 0.085, 0.10]


def cap_and_redistribute(full_targets, cap):
    """Apply a single-stock cap to dependency-layer growth weights.

    Excess from capped names is redistributed iteratively across uncapped growth
    names in proportion to their original dependency-layer weights. This keeps
    the dependency design as intact as possible while enforcing the cap.
    """
    base = {t: full_targets[t] for t in GROWTH}
    g = dict(base)

    # Iterative water-filling with original dependency weights as redistribution weights.
    for _ in range(50):
        over = {t: max(0.0, g[t] - cap) for t in g}
        excess = sum(over.values())
        if excess < 1e-12:
            break
        for t, x in over.items():
            if x > 0:
                g[t] = cap
        eligible = [t for t in g if g[t] < cap - 1e-12]
        if not eligible:
            raise ValueError(f'Cap {cap:.2%} is too low to allocate the 81% growth sleeve.')
        remaining_excess = excess
        # redistribute proportional to original dependency weights, respecting remaining headroom
        while remaining_excess > 1e-12:
            eligible = [t for t in eligible if g[t] < cap - 1e-12]
            if not eligible:
                raise ValueError(f'Cap {cap:.2%} is infeasible.')
            denom = sum(base[t] for t in eligible)
            moved = 0.0
            for t in list(eligible):
                proposed = remaining_excess * (base[t] / denom)
                headroom = cap - g[t]
                add = min(proposed, headroom)
                g[t] += add
                moved += add
            if moved < 1e-14:
                raise RuntimeError('Redistribution stalled')
            remaining_excess -= moved

    assert abs(sum(g.values()) - 0.81) < 1e-8, sum(g.values())
    assert max(g.values()) <= cap + 1e-8
    return {**DEFENSE, **g}


def main():
    prices = load_prices('2024-01-01')
    earnings = load_earnings()

    dependency, layers = dependency_layer_growth()
    current = {**DEFENSE, **GROWTH}

    specs = [('CURRENT_V08', current), ('DEPENDENCY_UNCAPPED', dependency)]
    targets_out = {'CURRENT_V08': current, 'DEPENDENCY_UNCAPPED': dependency}

    for cap in CAPS:
        name = f'DEP_CAP_{cap*100:.1f}'.replace('.', '_')
        t = cap_and_redistribute(dependency, cap)
        specs.append((name, t))
        targets_out[name] = t

    rows = []
    logs = []
    for name, targets in specs:
        n, s, l = run(name, prices, earnings, targets, 'smart', 500, 200, CASH, list(GROWTH))
        rows.append({'strategy': n, **s})
        l['strategy'] = n
        logs.append(l)

    df = pd.DataFrame(rows)
    # Composite rewards return, downside-adjusted return, and shallower drawdown.
    df['composite_score'] = (
        df['ann_return'].rank(pct=True) * 0.40
        + df['sortino'].rank(pct=True) * 0.35
        + (-df['max_drawdown'].abs()).rank(pct=True) * 0.25
    )
    df = df.sort_values('composite_score', ascending=False).reset_index(drop=True)

    df.to_csv(OUT / 'summary.csv', index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / 'trades.csv', index=False)

    winner = df.iloc[0]['strategy']
    result = {
        'test': 'Dependency-layer weighting with single-stock caps',
        'assumptions': {
            'same_holdings': True,
            'same_smart_refill': True,
            'defensive_liquidity_sleeve': 0.19,
            'initial_capital': 500,
            'monthly_contribution': 200,
            'caps_tested': CAPS,
        },
        'method': 'Start with equal weight across seven dependency layers, equal within each layer, then cap any growth stock and redistribute excess across uncapped growth names in proportion to their original dependency-layer weights.',
        'layers': layers,
        'winner': winner,
        'results': df.to_dict(orient='records'),
        'targets': targets_out,
        'limitations': [
            'Current 2026 holdings are held fixed historically, so this tests weighting mechanics, not stock-selection foresight.',
            'Smart refill uses lagged reported earnings/surprise and trailing historical P/E as the point-in-time proxy for the current forward-estimate ranking rule.',
            'The common sample is constrained by the youngest current holding and is only about 23 months.',
        ],
    }
    (OUT / 'results.json').write_text(json.dumps(result, indent=2))

    rows_html = ''.join(
        f"<tr><td>{r.strategy}</td><td>{r.ann_return:.1%}</td><td>{r.max_drawdown:.1%}</td><td>{r.sortino:.2f}</td><td>${r.ending_value:,.0f}</td><td>{r.composite_score:.2f}</td></tr>"
        for r in df.itertuples()
    )
    html = f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>MACRO Dependency Cap Test</title><style>body{{font-family:system-ui;background:#0b0d10;color:#eee;max-width:950px;margin:40px auto;padding:0 20px}}.c{{background:#151a20;padding:18px;border-radius:14px;display:inline-block}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:10px;border-bottom:1px solid #333;text-align:right}}td:first-child,th:first-child{{text-align:left}}b{{font-size:24px}}</style><h1>Dependency + Single-Stock Cap Test</h1><p>Same holdings · same refill · same 19% defense · only cap changes</p><div class="c">Best overall<br><b>{winner}</b></div><table><tr><th>Weighting</th><th>Annual return</th><th>Max drawdown</th><th>Sortino</th><th>Ending value</th><th>Score</th></tr>{rows_html}</table><p><small>Current v08 universe held fixed historically. Mechanics test, not proof of stock-selection foresight.</small></p>'''
    (OUT / 'index.html').write_text(html)

    print(df.to_string(index=False))
    print('\nWINNER', winner)
    for name, t in targets_out.items():
        if name.startswith('DEP_'):
            print('\n', name, 'largest growth weights:', sorted(((k,v) for k,v in t.items() if k in GROWTH), key=lambda x:x[1], reverse=True)[:6])


if __name__ == '__main__':
    main()
