"""Synthetic known answers only: no network or portfolio data."""
import importlib.util, math, pathlib, sys, types, unittest
import pandas as pd
P=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(P))
sys.modules.setdefault('yfinance',types.ModuleType('yfinance'))
from performance_metrics import UnitizedPerformance, validate_capital
import backtest as bt
import historical_validation as hv

class PerformanceTests(unittest.TestCase):
 def direct(self,initial=100):
  x=UnitizedPerformance(initial,'2026-01-31');x.initial(initial);return x
 def test_flat_prices_contribution_zero_gain(self):
  x=self.direct();x.contribute(100,100);x.observe('2026-02-28',200);x.contribute(50,200);x.observe('2026-03-31',250)
  p=x.result('2026-04-01');self.assertEqual(p['total_return'],0);self.assertEqual(p['metrics']['ending_value'],250)
 def test_initial_fee_is_loss(self):
  x=UnitizedPerformance(100,'2026-01-31');x.initial(99);x.observe('2026-02-28',99);x.observe('2026-03-31',99)
  p=x.result('2026-04-01');self.assertAlmostEqual(p['total_return'],-.01);self.assertAlmostEqual(p['metrics']['max_drawdown'],-.01);self.assertEqual(len(p['monthly_returns']),2)
 def test_subsequent_fee_is_loss(self):
  x=self.direct();x.contribute(100,100);x.observe('2026-02-28',199);x.observe('2026-03-31',199)
  p=x.result('2026-04-01');self.assertAlmostEqual(p['total_return'],-.005)
 def test_market_growth_with_contribution(self):
  x=self.direct();x.contribute(100,110);x.observe('2026-02-28',210);x.observe('2026-03-31',231)
  self.assertAlmostEqual(x.result('2026-04-01')['total_return'],.21)
 def test_drawdown_initial_baseline(self):
  x=self.direct();x.observe('2026-02-28',90);x.observe('2026-03-31',81)
  self.assertAlmostEqual(x.result('2026-04-01')['metrics']['max_drawdown'],-.19)
 def test_undefined_ratios_null_reason(self):
  x=self.direct();x.observe('2026-02-28',100);x.observe('2026-03-31',100);m=x.result('2026-04-01')['metrics']
  for k in ['sharpe','sortino']:self.assertIsNone(m[k]);self.assertIn(k,m['undefined_reasons'])
 def test_single_interval_vol_null(self):
  x=self.direct();x.observe('2026-02-28',100);m=x.result('2026-03-01')['metrics'];self.assertIsNone(m['ann_vol']);self.assertIn('ann_vol',m['undefined_reasons'])
 def test_partial_period_annualization_actual_days(self):
  x=UnitizedPerformance(100,'2026-01-15');x.initial(100);x.observe('2026-01-31',101);p=x.result('2026-02-01')
  self.assertTrue(p['first_period_partial']);self.assertEqual(p['elapsed_days'],16);self.assertAlmostEqual(p['metrics']['ann_return'],1.01**(365.25/16)-1)
 def test_current_month_excluded(self):
  x=self.direct();x.observe('2026-02-28',100);x.observe('2026-03-02',999);self.assertEqual(x.result('2026-03-03')['metrics']['ending_value'],100)
 def test_invalid_capital_fee_and_withdrawal(self):
  for args in [(0,0,0),(-1,0,0),(100,1,0),(100,1.1,0),(100,0,-1),(100,float('nan'),0)]:
   with self.subTest(args=args):self.assertRaises(ValueError,validate_capital,*args)
  x=self.direct();self.assertRaises(ValueError,x.contribute,1,0)
 def test_core_fee_and_flow_known_answer(self):
  old=bt.FEE;bt.FEE=.01
  try:
   p=pd.DataFrame({'AAA':[100,100,100]},index=pd.to_datetime(['2026-01-31','2026-02-28','2026-03-31']))
   _,s,_=bt.run('synthetic',p,{}, {'AAA':1},'benchmark',100,100,0,['AAA'])
   self.assertLess(s['performance']['total_return'],-.01);self.assertAlmostEqual(s['legacy_metrics']['ann_return'],0);self.assertEqual(s['ending_value'],s['performance']['metrics']['ending_value'])
  finally:bt.FEE=old
 def test_core_no_fee_fixed_single_asset_contribution_invariance(self):
  old=bt.FEE;bt.FEE=0
  try:
   p=pd.DataFrame({'AAA':[100,110,121]},index=pd.to_datetime(['2026-01-31','2026-02-28','2026-03-31']))
   vals=[bt.run('fixture',p,{}, {'AAA':1},'benchmark',100,c,0,['AAA'])[1]['performance']['total_return'] for c in [0,100]]
   self.assertAlmostEqual(vals[0],.21);self.assertAlmostEqual(vals[1],.21)
  finally:bt.FEE=old
 def historical(self,events=None,fee=0):
  p=pd.DataFrame({'AAA':100.},index=pd.bdate_range('2026-01-30','2026-04-30'))
  cfg={'anchor_date':'2026-01-30','initial_capital':100,'fee':fee,'cash_target':0,'initial_targets':{'AAA':1},'events':events or []}
  return hv.run_event_dated(p,cfg)
 def test_historical_contribution_not_performance(self):
  r=self.historical([{'date':'2026-02-02','type':'CONTRIBUTION','dollars':100}]);self.assertAlmostEqual(r['performance']['total_return'],0);self.assertGreater(r['legacy_metrics']['ann_return'],0);self.assertEqual(r['events_applied'][0]['execution_date'],'2026-02-02')
 def test_event_same_date_order_preserved(self):
  contribution={'date':'2026-02-02','type':'CONTRIBUTION','dollars':100};buy={'date':'2026-02-02','type':'BUY_DOLLARS','dollars':100,'ticker':'AAA'}
  a=self.historical([buy,contribution],.01);b=self.historical([contribution,buy],.01)
  self.assertLess(b['performance']['total_return'],a['performance']['total_return']);self.assertEqual(a['events_applied'][0]['type'],'BUY_DOLLARS')
 def test_anchor_flat_contributions_no_gain(self):
  p=pd.DataFrame({'AAA':100.},index=pd.bdate_range('2026-01-30','2026-04-30'));cfg={'anchor_date':'2026-01-30','targets':{'AAA':1},'cash_target':0,'initial_capital':100,'monthly_contribution':100,'fee':0}
  result=hv.run_anchor_forward(p,cfg);self.assertAlmostEqual(result['performance']['total_return'],0);self.assertGreater(result['legacy_metrics']['ann_return'],0)

if __name__=='__main__':unittest.main(verbosity=2)
