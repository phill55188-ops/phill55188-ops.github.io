import json
from pathlib import Path
import pandas as pd

import backtest as bt

OUT = Path('macro-backtest/results-dependency-caps')
OUT.mkdir(parents=True, exist_ok=True)
CAP = 0.10

# Authoritative v10.4 canonical targets before the Silicon Creation / Enablement layer.
CURRENT_V10_4_GROWTH = {
    'NVDA': 0.061,
    'QCOM': 0.061,
    'MU': 0.10,
    'PLTR': 0.05,
    'ADBE': 0.05,
    'ORCL': 0.040666667,
    'NBIS': 0.040666667,
    'NET': 0.040666667,
    'AAOI': 0.040666667,
    'LITE': 0.040666667,
    'MRVL': 0.040666667,
    'VRT': 0.040666667,
    'BE': 0.040666667,
    'GEV': 0.040666667,
    'LEU': 0.040666667,
    'MP': 0.040666667,
    'FCX': 0.040666667,
}

NEW_LAYERS = {
    'materials_fuel': ['MP', 'FCX', 'LEU'],
    'power_infrastructure': ['VRT', 'BE', 'GEV'],
    'silicon_creation_enablement': ['TSM', 'SNPS'],
    'compute': ['NVDA', 'QCOM'],
    'memory': ['MU'],
    'networking_optics': ['AAOI', 'LITE', 'MRVL'],
    'cloud_edge_execution': ['ORCL', 'NBIS', 'NET'],
    'orchestration': ['PLTR', 'ADBE'],
}


def dependency_targets(layers, cap=CAP):
    """Equal-weight the 81% growth sleeve by dependency layer, then equal-weight
    within each layer. Enforce a single-stock cap and redistribute any excess
    across uncapped names in proportion to their uncapped dependency weights.
    """
    layer_weight = 0.81 / len(layers)
    base = {}
    for names in layers.values():
        each = layer_weight / len(names)
        for ticker in names:
            base[ticker] = each

    growth = dict(base)
    for _ in range(100):
        over = {t: max(0.0, growth[t] - cap) for t in growth}
        excess = sum(over.values())
        if excess < 1e-12:
            break
        for t, x in over.items():
            if x > 0:
                growth[t] = cap

        remaining = excess
        while remaining > 1e-12:
            eligible = [t for t in growth if growth[t] < cap - 1e-12]
            if not eligible:
                raise ValueError('Cap is infeasible for this universe.')
            denom = sum(base[t] for t in eligible)
            moved = 0.0
            for t in eligible:
                proposed = remaining * (base[t] / denom)
                headroom = cap - growth[t]
                add = min(proposed, headroom)
                growth[t] += add
                moved += add
            if moved < 1e-14:
                raise RuntimeError('Redistribution stalled.')
            remaining -= moved

    assert abs(sum(growth.values()) - 0.81) < 1e-8, sum(growth.values())
    assert max(growth.values()) <= cap + 1e-8
    return growth, {**bt.DEFENSE, **growth}


def main():
    new_growth, new_targets = dependency_targets(NEW_LAYERS, CAP)
    current_targets = {**bt.DEFENSE, **CURRENT_V10_4_GROWTH}

    # Make the existing engine fetch price + earnings history for the expanded
    # universe while preserving its established smart-refill/run mechanics.
    expanded = sorted(set(CURRENT_V10_4_GROWTH) | set(new_growth))
    bt.GROWTH = {t: new_growth.get(t, CURRENT_V10_4_GROWTH.get(t, 0.0)) for t in expanded}
    bt.TARGETS = {**bt.DEFENSE, **bt.GROWTH}

    prices = bt.load_prices('2024-01-01')
    earnings = bt.load_earnings()

    specs = [
        ('CURRENT_V10_4', current_targets, list(CURRENT_V10_4_GROWTH)),
        ('V10_5_TSM_SNPS_DEP_CAP_10', new_targets, list(new_growth)),
    ]

    rows = []
    logs = []
    for name, targets, growth_names in specs:
        n, s, l = bt.run(name, prices, earnings, targets, 'smart', 500, 200, bt.CASH, growth_names)
        rows.append({'strategy': n, **s})
        l['strategy'] = n
        logs.append(l)

    df = pd.DataFrame(rows)
    cur = df.loc[df.strategy == 'CURRENT_V10_4'].iloc[0]
    new = df.loc[df.strategy == 'V10_5_TSM_SNPS_DEP_CAP_10'].iloc[0]

    comparison = {
        'annual_return_change_points': float((new.ann_return - cur.ann_return) * 100),
        'sortino_change': float(new.sortino - cur.sortino),
        'max_drawdown_change_points': float((new.max_drawdown - cur.max_drawdown) * 100),
        'ending_value_change': float(new.ending_value - cur.ending_value),
    }

    target_rows = []
    for ticker, weight in sorted(new_targets.items(), key=lambda kv: kv[1], reverse=True):
        target_rows.append({
            'ticker': ticker,
            'target_weight': weight,
            'target_percent': weight * 100,
            'layer': next((layer for layer, names in NEW_LAYERS.items() if ticker in names), 'defensive'),
        })

    df.to_csv(OUT / 'summary.csv', index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / 'trades.csv', index=False)
    pd.DataFrame(target_rows).to_csv(OUT / 'v10_5_targets.csv', index=False)

    result = {
        'test': 'v10.4 canonical vs v10.5 proposed Silicon Creation / Enablement layer',
        'assumptions': {
            'same_backtest_engine': True,
            'same_smart_refill': True,
            'same_defensive_liquidity_sleeve': 0.19,
            'same_initial_capital': 500,
            'same_monthly_contribution': 200,
            'single_stock_cap': CAP,
            'new_holdings': ['TSM', 'SNPS'],
            'growth_sleeve': 0.81,
        },
        'new_layers': NEW_LAYERS,
        'comparison': comparison,
        'results': df.to_dict(orient='records'),
        'new_targets': new_targets,
        'new_growth_targets': new_growth,
        'limitations': [
            'Current 2026 holdings are held fixed historically, so this tests weighting/universe mechanics rather than stock-selection foresight.',
            'Smart refill uses the established lagged reported-earnings/surprise and trailing historical P/E proxy, not a paid point-in-time forward-estimate database.',
            'The common sample remains constrained by the youngest holding in the portfolio and is short.',
            'Adding TSM and SNPS uses their historical returns even though the decision to add them was made in 2026, so absolute returns contain hindsight/selection bias. Relative comparisons are the useful evidence.',
        ],
    }
    (OUT / 'results.json').write_text(json.dumps(result, indent=2))

    rows_html = ''.join(
        f"<tr><td>{r.strategy}</td><td>{r.ann_return:.1%}</td><td>{r.max_drawdown:.1%}</td><td>{r.sortino:.2f}</td><td>${r.ending_value:,.0f}</td></tr>"
        for r in df.itertuples()
    )
    targets_html = ''.join(
        f"<tr><td>{r['ticker']}</td><td>{r['target_percent']:.2f}%</td><td>{r['layer'].replace('_', ' ')}</td></tr>"
        for r in target_rows
    )
    html = f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>MACRO v10.5 Silicon Layer Test</title><style>body{{font-family:system-ui;background:#0b0d10;color:#eee;max-width:1000px;margin:40px auto;padding:0 20px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}.c{{background:#151a20;padding:18px;border-radius:14px}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:10px;border-bottom:1px solid #333;text-align:right}}td:first-child,th:first-child{{text-align:left}}b{{font-size:24px}}</style><h1>v10.5 Silicon Creation / Enablement Test</h1><p>Same engine · same smart refill · same 19% defense · $500 start · $200/month</p><div class="cards"><div class="c">Annual return change<br><b>{comparison['annual_return_change_points']:+.1f} pts</b></div><div class="c">Sortino change<br><b>{comparison['sortino_change']:+.2f}</b></div><div class="c">Drawdown change<br><b>{comparison['max_drawdown_change_points']:+.1f} pts</b></div><div class="c">Ending value change<br><b>${comparison['ending_value_change']:+,.0f}</b></div></div><h2>Backtest</h2><table><tr><th>Architecture</th><th>Annual return</th><th>Max drawdown</th><th>Sortino</th><th>Ending value</th></tr>{rows_html}</table><h2>Proposed canonical targets</h2><table><tr><th>Ticker</th><th>Target</th><th>Layer</th></tr>{targets_html}</table><p><small>Mechanics comparison only. Today's holdings are tested historically and therefore contain hindsight/selection bias.</small></p>'''
    (OUT / 'index.html').write_text(html)

    print(df.to_string(index=False))
    print('\nCOMPARISON', json.dumps(comparison, indent=2))
    print('\nNEW TARGETS')
    for row in target_rows:
        print(f"{row['ticker']:5s} {row['target_percent']:6.3f}%  {row['layer']}")


if __name__ == '__main__':
    main()
