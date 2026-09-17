import json
from itertools import product
from pathlib import Path

import pandas as pd

import backtest as bt
import dependency_cap_test as dct

OUT = Path('macro-backtest/results-dependency-caps')
OUT.mkdir(parents=True, exist_ok=True)

# Canon rules: 81% growth sleeve, 19% defense, 10% single-name cap,
# and 2% permanent minimum strategic position.
GROWTH_SLEEVE = 0.81
CAP = 0.10
MIN_POSITION = 0.02
WEIGHT_GRID = [0.02, 0.03, 0.04, 0.05]
RETURN_TOLERANCE_POINTS = 5.0
SATELLITES = ['ADBE', 'TSM', 'SNPS']


def satellite_overlay_targets(base_growth, satellite_weights):
    """Preserve the v08 dependency architecture and treat ADBE/TSM/SNPS as
    explicit satellite allocations instead of giving each new dependency an
    automatically equal layer.

    The satellites reserve their fixed weights first. The remaining growth
    sleeve is distributed across the original v08 growth names in proportion
    to their dependency-model weights. This tests whether the new thesis names
    can be included without mechanically diluting every established layer as
    aggressively as the equal-layer v10.5 construction.
    """
    reserved = sum(satellite_weights.values())
    if reserved >= GROWTH_SLEEVE:
        raise ValueError('Satellite weights consume the entire growth sleeve.')

    scale = (GROWTH_SLEEVE - reserved) / GROWTH_SLEEVE
    growth = {ticker: weight * scale for ticker, weight in base_growth.items()}
    growth.update(satellite_weights)

    if abs(sum(growth.values()) - GROWTH_SLEEVE) > 1e-10:
        raise AssertionError(sum(growth.values()))
    if max(growth.values()) > CAP + 1e-10:
        raise AssertionError(f'10% cap breached: {max(growth.values())}')
    if min(satellite_weights.values()) < MIN_POSITION - 1e-10:
        raise AssertionError('Satellite below permanent 2% minimum.')

    return growth, {**bt.DEFENSE, **growth}


def main():
    base_growth, base_targets = dct.dependency_targets(dct.V08_LAYERS, CAP)

    # Build all pre-declared, coarse weight combinations. The grid is deliberately
    # coarse (2/3/4/5%) to reduce false precision and discourage overfitting.
    specs = [('V08_BENCHMARK', base_growth, base_targets, 0.0, 0.0, 0.0)]
    for adbe, tsm, snps in product(WEIGHT_GRID, repeat=3):
        satellites = {'ADBE': adbe, 'TSM': tsm, 'SNPS': snps}
        growth, targets = satellite_overlay_targets(base_growth, satellites)
        name = f'SAT_A{int(adbe*100)}_T{int(tsm*100)}_S{int(snps*100)}'
        specs.append((name, growth, targets, adbe, tsm, snps))

    all_growth = sorted(set(base_growth) | set(SATELLITES))
    bt.GROWTH = {ticker: 0.01 for ticker in all_growth}
    bt.TARGETS = {**bt.DEFENSE, **bt.GROWTH}

    prices = bt.load_prices('2024-01-01')
    earnings = bt.load_earnings()

    rows = []
    logs = []
    for name, growth, targets, adbe, tsm, snps in specs:
        n, s, l = bt.run(
            name,
            prices,
            earnings,
            targets,
            'smart',
            500,
            200,
            bt.CASH,
            list(growth),
        )
        rows.append({
            'strategy': n,
            'ADBE_weight': adbe,
            'TSM_weight': tsm,
            'SNPS_weight': snps,
            'satellite_total': adbe + tsm + snps,
            **s,
        })
        l['strategy'] = n
        logs.append(l)

    df = pd.DataFrame(rows)
    benchmark = df.loc[df.strategy == 'V08_BENCHMARK'].iloc[0]
    df['return_gap_points_vs_v08'] = (df['ann_return'] - benchmark.ann_return) * 100
    df['drawdown_change_points_vs_v08'] = (df['max_drawdown'] - benchmark.max_drawdown) * 100
    df['vol_change_points_vs_v08'] = (df['ann_vol'] - benchmark.ann_vol) * 100
    df['qualifies_within_5pts'] = df['return_gap_points_vs_v08'] >= -RETURN_TOLERANCE_POINTS

    candidates = df[df.strategy != 'V08_BENCHMARK'].copy()
    top_return = candidates.sort_values(
        ['ann_return', 'sortino', 'max_drawdown'], ascending=[False, False, False]
    ).iloc[0]
    top_sharpe = candidates.sort_values(
        ['sharpe', 'ann_return'], ascending=[False, False]
    ).iloc[0]
    top_sortino = candidates.sort_values(
        ['sortino', 'ann_return'], ascending=[False, False]
    ).iloc[0]

    qualifying = candidates[candidates.qualifies_within_5pts].copy()
    if len(qualifying):
        best_qualifying_sortino = qualifying.sort_values(
            ['sortino', 'ann_return'], ascending=[False, False]
        ).iloc[0]
        best_qualifying_return = qualifying.sort_values(
            ['ann_return', 'sortino'], ascending=[False, False]
        ).iloc[0]
    else:
        best_qualifying_sortino = None
        best_qualifying_return = None

    # Save complete grid plus concise shortlists.
    ordered = df.sort_values(
        ['ann_return', 'sortino', 'max_drawdown'], ascending=[False, False, False]
    ).reset_index(drop=True)
    ordered.to_csv(OUT / 'satellite_weight_grid_full.csv', index=False)
    pd.concat(logs, ignore_index=True).to_csv(OUT / 'satellite_weight_grid_trades.csv', index=False)
    candidates.sort_values('ann_return', ascending=False).head(12).to_csv(
        OUT / 'satellite_weight_top12_return.csv', index=False
    )

    def row_dict(row):
        if row is None:
            return None
        return {
            'strategy': row.strategy,
            'ADBE_percent': float(row.ADBE_weight * 100),
            'TSM_percent': float(row.TSM_weight * 100),
            'SNPS_percent': float(row.SNPS_weight * 100),
            'satellite_total_percent': float(row.satellite_total * 100),
            'ann_return': float(row.ann_return),
            'ann_vol': float(row.ann_vol),
            'sharpe': float(row.sharpe),
            'sortino': float(row.sortino),
            'max_drawdown': float(row.max_drawdown),
            'worst_month': float(row.worst_month),
            'ending_value': float(row.ending_value),
            'return_gap_points_vs_v08': float(row.return_gap_points_vs_v08),
            'drawdown_change_points_vs_v08': float(row.drawdown_change_points_vs_v08),
        }

    top12 = candidates.sort_values(
        ['ann_return', 'sortino'], ascending=[False, False]
    ).head(12)

    result = {
        'test': 'ADBE + TSM + SNPS satellite-weight sensitivity around the v08 dependency architecture',
        'method': {
            'base': 'V08 dependency-layer + 10% cap portfolio',
            'satellite_weights_tested_each': [2, 3, 4, 5],
            'number_of_satellite_combinations': int(len(candidates)),
            'growth_sleeve': GROWTH_SLEEVE,
            'defensive_sleeve': 0.19,
            'minimum_position': MIN_POSITION,
            'single_stock_cap': CAP,
            'funding_method': 'reserve satellite weights, then scale original v08 growth targets pro-rata into the remaining 81% growth sleeve',
            'same_engine': True,
            'same_smart_refill': True,
            'same_price_dataset': True,
            'same_common_window': True,
            'same_initial_capital': 500,
            'same_monthly_contribution': 200,
        },
        'benchmark': row_dict(benchmark),
        'best_satellite_return': row_dict(top_return),
        'best_satellite_sharpe': row_dict(top_sharpe),
        'best_satellite_sortino': row_dict(top_sortino),
        'within_5_return_points_count': int(len(qualifying)),
        'best_within_5pts_return': row_dict(best_qualifying_return),
        'best_within_5pts_sortino': row_dict(best_qualifying_sortino),
        'top12_by_return': [row_dict(row) for _, row in top12.iterrows()],
        'limitations': [
            'The grid is intentionally coarse and pre-declared; it is a sensitivity test, not a fine-grained historical optimizer.',
            'ADBE, TSM, and SNPS are applied retrospectively even though the present theses were formed in 2026, so results contain hindsight/selection bias.',
            'ADBE historical weakness is part of the tested history and cannot evaluate a future comeback thesis that has not yet occurred.',
            'Smart refill uses lagged reported earnings/surprise and trailing historical P/E as a proxy for the live forward-estimate ranking rule.',
            'The common sample remains short and constrained by NBIS; absolute annualized returns are not expected future returns.',
        ],
    }
    (OUT / 'satellite_weight_test_results.json').write_text(json.dumps(result, indent=2))

    print('V08 BENCHMARK')
    print(pd.DataFrame([row_dict(benchmark)]).to_string(index=False))
    print('\nTOP 12 SATELLITE CONFIGURATIONS BY RETURN')
    display_cols = [
        'strategy', 'ADBE_weight', 'TSM_weight', 'SNPS_weight', 'ann_return',
        'ann_vol', 'sharpe', 'sortino', 'max_drawdown',
        'return_gap_points_vs_v08', 'ending_value'
    ]
    print(top12[display_cols].to_string(index=False))
    print(f'\nWithin {RETURN_TOLERANCE_POINTS:.0f} return points of v08: {len(qualifying)} / {len(candidates)}')
    print('\nBEST RETURN', json.dumps(row_dict(top_return), indent=2))
    print('\nBEST SHARPE', json.dumps(row_dict(top_sharpe), indent=2))
    print('\nBEST SORTINO', json.dumps(row_dict(top_sortino), indent=2))
    print('\nBEST WITHIN 5 PTS RETURN', json.dumps(row_dict(best_qualifying_return), indent=2))
    print('\nBEST WITHIN 5 PTS SORTINO', json.dumps(row_dict(best_qualifying_sortino), indent=2))


if __name__ == '__main__':
    main()
