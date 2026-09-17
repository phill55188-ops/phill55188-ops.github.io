import json
from pathlib import Path
import pandas as pd

import backtest as bt

OUT = Path('macro-backtest/results-dependency-caps')
OUT.mkdir(parents=True, exist_ok=True)
CAP = 0.10

V08_LAYERS = {
    'materials_fuel': ['MP', 'FCX', 'LEU'],
    'power_infrastructure': ['VRT', 'BE', 'GEV'],
    'compute': ['NVDA', 'QCOM'],
    'memory': ['MU'],
    'networking_optics': ['AAOI', 'LITE', 'MRVL'],
    'cloud_edge_execution': ['ORCL', 'NBIS', 'NET'],
    'orchestration': ['PLTR'],
}

V10_4_LAYERS = {
    'materials_fuel': ['MP', 'FCX', 'LEU'],
    'power_infrastructure': ['VRT', 'BE', 'GEV'],
    'compute': ['NVDA', 'QCOM'],
    'memory': ['MU'],
    'networking_optics': ['AAOI', 'LITE', 'MRVL'],
    'cloud_edge_execution': ['ORCL', 'NBIS', 'NET'],
    'orchestration': ['PLTR', 'ADBE'],
}

V10_5_LAYERS = {
    'materials_fuel': ['MP', 'FCX', 'LEU'],
    'power_infrastructure': ['VRT', 'BE', 'GEV'],
    'silicon_creation_enablement': ['TSM', 'SNPS'],
    'compute': ['NVDA', 'QCOM'],
    'memory': ['MU'],
    'networking_optics': ['AAOI', 'LITE', 'MRVL'],
    'cloud_edge_execution': ['ORCL', 'NBIS', 'NET'],
    'orchestration': ['PLTR', 'ADBE'],
}

CONFIGS = {
    'V08_DEP_CAP_10': V08_LAYERS,
    'V10_4_DEP_CAP_10': V10_4_LAYERS,
    'V10_5_DEP_CAP_10': V10_5_LAYERS,
}


def dependency_targets(layers, cap=CAP):
    """Equal-weight the 81% growth sleeve by dependency layer, then equal-weight
    within each layer. Enforce a single-stock cap and redistribute excess across
    uncapped names in proportion to their original dependency weights.
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
    built = {}
    all_growth = set()
    for name, layers in CONFIGS.items():
        growth, targets = dependency_targets(layers, CAP)
        built[name] = {'layers': layers, 'growth': growth, 'targets': targets}
        all_growth.update(growth)

    # Fetch one expanded dataset, then run each portfolio through the exact same
    # engine/refill rules. All three universes share NBIS, the youngest holding,
    # so bt.run resolves to the same common start window for every configuration.
    union_growth = sorted(all_growth)
    bt.GROWTH = {t: 0.01 for t in union_growth}
    bt.TARGETS = {**bt.DEFENSE, **bt.GROWTH}

    prices = bt.load_prices('2024-01-01')
    earnings = bt.load_earnings()

    rows = []
    logs = []
    for name in CONFIGS:
        spec = built[name]
        n, s, l = bt.run(
            name,
            prices,
            earnings,
            spec['targets'],
            'smart',
            500,
            200,
            bt.CASH,
            list(spec['growth']),
        )
        rows.append({'strategy': n, **s})
        l['strategy'] = n
        logs.append(l)

    df = pd.DataFrame(rows)
    df['composite_score'] = (
        df['ann_return'].rank(pct=True) * 0.40
        + df['sortino'].rank(pct=True) * 0.35
        + (-df['max_drawdown'].abs()).rank(pct=True) * 0.25
    )
    df = df.sort_values('composite_score', ascending=False).reset_index(drop=True)

    winner_return = df.loc[df['ann_return'].idxmax(), 'strategy']
    winner_sortino = df.loc[df['sortino'].idxmax(), 'strategy']
    winner_drawdown = df.loc[df['max_drawdown'].idxmax(), 'strategy']
    winner_composite = df.loc[df['composite_score'].idxmax(), 'strategy']

    targets_out = {name: built[name]['targets'] for name in CONFIGS}
    layers_out = {name: built[name]['layers'] for name in CONFIGS}

    target_rows = []
    for name in CONFIGS:
        reverse_layer = {
            ticker: layer
            for layer, names in built[name]['layers'].items()
            for ticker in names
        }
        for ticker, weight in sorted(built[name]['targets'].items(), key=lambda kv: kv[1], reverse=True):
            target_rows.append({
                'strategy': name,
                'ticker': ticker,
                'target_weight': weight,
                'target_percent': weight * 100,
                'layer': reverse_layer.get(ticker, 'defensive'),
            })

    df.to_csv(OUT / 'controlled_three_config_summary.csv', index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / 'controlled_three_config_trades.csv', index=False)
    pd.DataFrame(target_rows).to_csv(OUT / 'controlled_three_config_targets.csv', index=False)

    result = {
        'test': 'Controlled dependency-layer + 10% cap comparison: v08 vs v10.4 (+ADBE) vs v10.5 (+TSM + SNPS)',
        'assumptions': {
            'same_backtest_engine': True,
            'same_price_dataset': True,
            'same_smart_refill': True,
            'same_defensive_liquidity_sleeve': 0.19,
            'same_initial_capital': 500,
            'same_monthly_contribution': 200,
            'same_single_stock_cap': CAP,
            'same_growth_sleeve': 0.81,
            'same_common_window': True,
            'only_change': 'holdings/layer structure',
        },
        'winners': {
            'highest_return': winner_return,
            'best_sortino': winner_sortino,
            'shallowest_drawdown': winner_drawdown,
            'best_composite': winner_composite,
        },
        'results': df.to_dict(orient='records'),
        'layers': layers_out,
        'targets': targets_out,
        'limitations': [
            'Current holdings are applied retrospectively, so this is a portfolio mechanics/universe comparison rather than proof that each stock could have been selected without hindsight.',
            'Smart refill uses lagged reported earnings/surprise and trailing historical P/E as a point-in-time proxy for the current forward-estimate ranking rule.',
            'The common sample is constrained by NBIS and remains short at roughly 23 months.',
            'Absolute annualized returns from a short high-growth sample should not be treated as expected future returns; relative differences are the useful evidence.',
        ],
    }
    (OUT / 'controlled_three_config_results.json').write_text(json.dumps(result, indent=2))

    rows_html = ''.join(
        f"<tr><td>{r.strategy}</td><td>{r.ann_return:.1%}</td><td>{r.ann_vol:.1%}</td><td>{r.max_drawdown:.1%}</td><td>{r.sortino:.2f}</td><td>${r.ending_value:,.0f}</td><td>{r.composite_score:.2f}</td></tr>"
        for r in df.itertuples()
    )
    html = f'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>MACRO Controlled 3-Config Test</title><style>body{{font-family:system-ui;background:#0b0d10;color:#eee;max-width:1050px;margin:40px auto;padding:0 20px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}.c{{background:#151a20;padding:18px;border-radius:14px}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:10px;border-bottom:1px solid #333;text-align:right}}td:first-child,th:first-child{{text-align:left}}b{{font-size:20px}}</style><h1>Controlled Dependency Architecture Test</h1><p>Same dates · same engine · same smart refill · same 19% defense · same 10% cap · $500 start · $200/month</p><div class="cards"><div class="c">Highest return<br><b>{winner_return}</b></div><div class="c">Best Sortino<br><b>{winner_sortino}</b></div><div class="c">Shallowest drawdown<br><b>{winner_drawdown}</b></div><div class="c">Best composite<br><b>{winner_composite}</b></div></div><table><tr><th>Configuration</th><th>Annual return</th><th>Volatility</th><th>Max drawdown</th><th>Sortino</th><th>Ending value</th><th>Score</th></tr>{rows_html}</table><p><small>Only holdings/layer structure changes. Absolute returns are hindsight-biased; use relative differences as evidence.</small></p>'''
    (OUT / 'controlled_three_config.html').write_text(html)

    print(df.to_string(index=False))
    print('\nWINNERS', json.dumps(result['winners'], indent=2))
    for name in CONFIGS:
        print(f'\n{name} TARGETS')
        for t, w in sorted(built[name]['targets'].items(), key=lambda kv: kv[1], reverse=True):
            print(f'{t:5s} {w*100:6.3f}%')


if __name__ == '__main__':
    main()
