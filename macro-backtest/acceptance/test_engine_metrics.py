"""Offline source-extracted engine characterization; never imports engine or calls data providers."""
import ast
import math
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

SOURCES = Path(__file__).resolve().parent

def extract(filename, names, extra=None):
    tree = ast.parse((SOURCES / ('fixture-engine-' + filename)).read_text())
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in funcs} == set(names)
    ns = {'pd': pd, 'np': np, 'math': math, 'FEE': .01, 'DRIFT': .10, 'FEE_DEFAULT': .01}
    ns.update(extra or {})
    exec(compile(ast.Module(body=funcs, type_ignores=[]), filename, 'exec'), ns)
    return ns

CORE = extract('backtest.py', ['stats', 'run', '_completed_monthly_last'])
HIST = extract('historical_validation.py', ['stats_from_values','_completed_monthly_values','normalize_target_check','_first_complete_date','run_anchor_forward','run_event_dated'])

class FixedTimestamp(pd.Timestamp):
    @classmethod
    def utcnow(cls):
        return pd.Timestamp('2026-10-25T12:00:00Z')

class PDProxy:
    Timestamp = FixedTimestamp
    def __getattr__(self, name):
        return getattr(pd, name)

class MetricCharacterization(unittest.TestCase):
    def test_metric_known_answers(self):
        r = [.1, -.1, -.2, .05]
        x = CORE['stats'](r)
        mean = sum(r)/4
        sample_sd = math.sqrt(sum((v-mean)**2 for v in r)/3)
        downside_sd = math.sqrt(((-.1+.15)**2 + (-.2+.15)**2))
        self.assertAlmostEqual(x['ann_return'], (1.1*.9*.8*1.05)**3-1)
        self.assertAlmostEqual(x['ann_vol'], sample_sd*math.sqrt(12))
        self.assertAlmostEqual(x['sharpe'], mean/sample_sd*math.sqrt(12))
        self.assertAlmostEqual(x['sortino'], mean/downside_sd*math.sqrt(12))
        self.assertAlmostEqual(x['max_drawdown'], -.28)
        self.assertAlmostEqual(x['worst_month'], -.2)

    def test_drawdown_omits_initial_wealth(self):
        self.assertAlmostEqual(CORE['stats']([-.1,-.1])['max_drawdown'], -.1)
        # Full initial-baseline drawdown would be -.19; characterize, do not alter.

    def test_zero_variance_undefined_ratios(self):
        x=CORE['stats']([0,0,0]); self.assertTrue(math.isnan(x['sharpe'])); self.assertTrue(math.isnan(x['sortino']))

    def test_single_downside_undefined_sortino(self):
        self.assertTrue(math.isnan(CORE['stats']([.1,-.1,.2])['sortino']))

    def test_core_flat_price_contributions_and_fee(self):
        p=pd.DataFrame({'AAA':[100.,100.,100.]},index=pd.to_datetime(['2026-01-31','2026-02-28','2026-03-31']))
        _,s,trades=CORE['run']('FIXTURE',p,{}, {'AAA':1.},'benchmark',100,100,0,['AAA'])
        self.assertEqual(s['months'],2); self.assertAlmostEqual(s['ann_return'],0.)
        self.assertAlmostEqual(s['ending_value'],297.)
        self.assertAlmostEqual(trades.dollars.sum(),200.)
        # Three 1% buy fees lower value from cash contributed=300; return excludes them.

    def test_historical_flat_price_contribution_is_raw_growth(self):
        p=pd.DataFrame({'AAA':[100.,100.,100.]},index=pd.to_datetime(['2026-01-31','2026-02-28','2026-03-31']))
        cfg={'anchor_date':'2026-01-31','targets':{'AAA':1.},'initial_capital':100,'monthly_contribution':100,'fee':.01}
        s=HIST['run_anchor_forward'](p,cfg)['metrics']
        self.assertEqual(s['months'],2); self.assertAlmostEqual(s['ending_value'],297.)
        self.assertAlmostEqual(s['ann_return'],3**6-1)

    def test_event_contribution_is_raw_growth(self):
        p=pd.DataFrame({'AAA':[100.,100.,100.]},index=pd.to_datetime(['2026-01-31','2026-02-28','2026-03-31']))
        cfg={'anchor_date':'2026-01-31','initial_targets':{'AAA':1.},'initial_capital':100,'fee':0,'events':[{'date':'2026-02-28','type':'CONTRIBUTION','dollars':100}]}
        x=HIST['run_event_dated'](p,cfg)
        self.assertAlmostEqual(x['metrics']['ann_return'],2**6-1)
        self.assertEqual(x['events_applied'][0]['status'],'APPLIED')

    def test_historical_no_contributions_flat_prices(self):
        p=pd.DataFrame({'AAA':[100.,100.,100.]},index=pd.to_datetime(['2026-01-31','2026-02-28','2026-03-31']))
        cfg={'anchor_date':'2026-01-31','targets':{'AAA':1.},'initial_capital':100,'monthly_contribution':0,'fee':.01}
        s=HIST['run_anchor_forward'](p,cfg)['metrics']
        self.assertAlmostEqual(s['ann_return'],0); self.assertAlmostEqual(s['ending_value'],99)
        self.assertIsNone(s['sharpe']); self.assertIsNone(s['sortino'])

    def test_historical_no_completed_returns_fails(self):
        with self.assertRaises(RuntimeError): HIST['stats_from_values'](pd.Series([100],index=pd.to_datetime(['2026-01-31'])))

    def test_partial_current_month_excluded(self):
        c=extract('backtest.py',['_completed_monthly_last'],{'pd':PDProxy()})
        h=extract('historical_validation.py',['_completed_monthly_values'],{'pd':PDProxy()})
        s=pd.Series([100,101,102],index=pd.to_datetime(['2026-08-31','2026-09-30','2026-10-24']))
        self.assertEqual(c['_completed_monthly_last'](s).index[-1],pd.Timestamp('2026-09-30'))
        self.assertEqual(h['_completed_monthly_values'](s).index[-1],pd.Timestamp('2026-09-30'))

    def test_stale_partial_prior_month_is_not_detected_by_helper(self):
        c=extract('backtest.py',['_completed_monthly_last'],{'pd':PDProxy()})
        s=pd.Series([100,101],index=pd.to_datetime(['2026-08-31','2026-09-15']))
        self.assertEqual(c['_completed_monthly_last'](s).index[-1],pd.Timestamp('2026-09-30'))

    def test_month_end_day_is_included_by_helper(self):
        class EndTimestamp(FixedTimestamp):
            @classmethod
            def utcnow(cls): return pd.Timestamp('2026-10-31T00:01:00Z')
        proxy=PDProxy(); proxy.Timestamp=EndTimestamp
        c=extract('backtest.py',['_completed_monthly_last'],{'pd':proxy})
        s=pd.Series([100,101],index=pd.to_datetime(['2026-09-30','2026-10-30']))
        self.assertEqual(c['_completed_monthly_last'](s).index[-1],pd.Timestamp('2026-10-31'))

if __name__=='__main__': unittest.main(verbosity=2)
