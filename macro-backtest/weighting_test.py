import json
from pathlib import Path
import pandas as pd

from backtest import DEFENSE, CASH, GROWTH, load_prices, load_earnings, run

OUT = Path('macro-backtest/results-weighting')
OUT.mkdir(parents=True, exist_ok=True)


def equal_growth():
    per = 0.81 / len(GROWTH)
    return {**DEFENSE, **{t: per for t in GROWTH}}


def capped_growth(cap=0.10):
    """Cap any growth holding at 10%, redistribute excess proportionally to uncapped names."""
    g = dict(GROWTH)
    excess = 0.0
    uncapped = []
    for t, w in list(g.items()):
        if w > cap:
            excess += w - cap
            g[t] = cap
        else:
            uncapped.append(t)
    base = sum(g[t] for t in uncapped)
    for t in uncapped:
        g[t] += excess * (g[t] / base)
    assert abs(sum(g.values()) - 0.81) < 1e-9
    return {**DEFENSE, **g}


def dependency_layer_growth():
    """Split the 81% growth sleeve equally across seven canonical dependency layers, then equally within each layer."""
    layers = {
        'materials_fuel': ['MP', 'FCX', 'LEU'],
        'power_infrastructure': ['VRT', 'BE', 'GEV'],
        'compute': ['NVDA', 'QCOM'],
        'memory': ['MU'],
        'networking_optics': ['AAOI', 'LITE', 'MRVL'],
        'cloud_edge': ['ORCL', 'NBIS', 'NET'],
        'orchestration': ['PLTR'],
    }
    layer_weight = 0.81 / len(layers)
    g = {}
    for names in layers.values():
        each = layer_weight / len(names)
        for t in names:
            g[t] = each
    assert set(g) == set(GROWTH)
    assert abs(sum(g.values()) - 0.81) < 1e-9
    return {**DEFENSE, **g}, layers


def fmt(x):
    return f'{x:.2%}'


def main():
    prices = load_prices('2024-01-01')
    earnings = load_earnings()

    current = {**DEFENSE, **GROWTH}
    equal = equal_growth()
    capped = capped_growth(0.10)
    layered, layers = dependency_layer_growth()

    specs = [
        ('CURRENT_V08', current),
        ('EQUAL_WEIGHT', equal),
        ('CAPPED_10', capped),
        ('DEPENDENCY_LAYER', layered),
    ]

    rows = []
    logs = []
    for name, targets in specs:
        n, s, l = run(name, prices, earnings, targets, 'smart', 500, 200, CASH, list(GROWTH))
        rows.append({'strategy': n, **s})
        l['strategy'] = n
        logs.append(l)

    df = pd.DataFrame(rows).sort_values('ann_return', ascending=False).reset_index(drop=True)
    df.to_csv(OUT / 'summary.csv', index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / 'trades.csv', index=False)

    # Composite score rewards return, downside-adjusted return, and shallower drawdown.
    # Ranks are used only to summarize; the raw metrics remain the primary evidence.
    score = (
        df['ann_return'].rank(pct=True) * 0.40
        + df['sortino'].rank(pct=True) * 0.35
        + (-df['max_drawdown'].abs()).rank(pct=True) * 0.25
    )
    df['composite_score'] = score
    winner_return = df.loc[df['ann_return'].idxmax(), 'strategy']
    winner_sortino = df.loc[df['sortino'].idxmax(), 'strategy']
    winner_drawdown = df.loc[df['max_drawdown'].idxmax(), 'strategy']
    winner_composite = df.loc[df['composite_score'].idxmax(), 'strategy']

    targets_out = {
        'CURRENT_V08': current,
        'EQUAL_WEIGHT': equal,
        'CAPPED_10': capped,
        'DEPENDENCY_LAYER': layered,
    }

    result = {
        'test_window_note': 'All four portfolios use the same current v08 universe, same 19% defensive/liquidity sleeve, same smart refill logic, $500 initial capital, and $200 monthly contributions.',
        'definitions': {
            'CURRENT_V08': 'Current conviction targets from canon v08.',
            'EQUAL_WEIGHT': '81% growth sleeve divided equally across all 16 growth holdings.',
            'CAPPED_10': 'Current conviction weights, but any growth holding above 10% is capped at 10% and the excess is redistributed proportionally across the remaining growth holdings.',
            'DEPENDENCY_LAYER': '81% growth sleeve divided equally across seven dependency layers, then equally among holdings within each layer.',
        },
        'layers': layers,
        'winners': {
            'highest_return': winner_return,
            'best_sortino': winner_sortino,
            'shallowest_drawdown': winner_drawdown,
            'best_composite': winner_composite,
        },
        'summary': df.to_dict(orient='records'),
        'targets': targets_out,
        'limitations': [
            'Current 2026 holdings are held fixed historically, so this tests weighting mechanics, not stock-selection foresight.',
            'Smart refill uses lagged reported earnings/surprise and trailing historical P/E as the point-in-time proxy for the current forward-estimate ranking rule.',
            'The common sample is constrained by the youngest current holding and is therefore short.',
        ],
    }
    (OUT / 'results.json').write_text(json.dumps(result, indent=2))

    rows_html = ''.join(
        f"<tr><td>{r.strategy}</td><td>{r.ann_return:.1%}</td><td>{r.max_drawdown:.1%}</td><td>{r.sortino:.2f}</td><td>${r.ending_value:,.0f}</td><td>{r.composite_score:.2f}</td></tr>"
        for r in df.itertuples()
    )
    html = f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>MACRO v08 Weighting Test</title><style>body{{font-family:system-ui;background:#0b0d10;color:#eee;max-width:950px;margin:40px auto;padding:0 20px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}.c{{background:#151a20;padding:18px;border-radius:14px}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:10px;border-bottom:1px solid #333;text-align:right}}td:first-child,th:first-child{{text-align:left}}b{{font-size:22px}}</style><h1>MACRO v08 Weighting Comparison</h1><p>Same holdings · same smart refill · same 19% defense · $500 start · $200/month</p><div class="cards"><div class="c">Highest return<br><b>{winner_return}</b></div><div class="c">Best downside efficiency<br><b>{winner_sortino}</b></div><div class="c">Shallowest drawdown<br><b>{winner_drawdown}</b></div><div class="c">Best combined result<br><b>{winner_composite}</b></div></div><table><tr><th>Weighting</th><th>Annual return</th><th>Max drawdown</th><th>Sortino</th><th>Ending value</th><th>Score</th></tr>{rows_html}</table><p><small>This is a mechanics test using today's v08 universe historically. It is not proof that these exact stocks could have been selected without hindsight.</small></p>'''
    (OUT / 'index.html').write_text(html)
    print(df.to_string(index=False))
    print(json.dumps(result['winners'], indent=2))


if __name__ == '__main__':
    main()
