"""Offline primary reporting: conflicting legacy values cannot drive verdicts."""
import ast,importlib.util,json,pathlib,sys,tempfile,types,unittest
from unittest.mock import patch
import pandas as pd
HERE=pathlib.Path(__file__).resolve().parent;ENGINE=HERE.parent
class Presentation(unittest.TestCase):
 def load_core(self):
  sys.path.insert(0,str(ENGINE))
  try:
   with patch.dict(sys.modules,{'yfinance':types.ModuleType('yfinance')}):
    spec=importlib.util.spec_from_file_location('presentation_core',ENGINE/'backtest.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
  finally:sys.path.remove(str(ENGINE))
 def test_primary_main_verdicts_ignore_conflicting_legacy(self):
  bt=self.load_core()
  def fake(name,*args):
   corrected={'ann_return':.2 if name=='V08_SMART' else .1,'ann_vol':.1,'sharpe':1.,'sortino':None,'max_drawdown':-.1 if name=='V08_SMART' else -.2,'worst_month':-.01,'ending_value':120.,'months':3,'undefined_reasons':{'sortino':'no negative intervals'}}
   legacy={**corrected,'ann_return':-.5 if name=='V08_SMART' else .9,'max_drawdown':-.8 if name=='V08_SMART' else -.01}
   return name,{**legacy,'legacy_metrics':legacy,'performance':{'metric_convention':'unitized_fee_inclusive_twr_v1','metrics':corrected}},pd.DataFrame({'cash':[0.]})
  with tempfile.TemporaryDirectory() as tmp,patch.object(bt,'run',fake),patch.object(bt,'load_prices',lambda *a:None),patch.object(bt,'load_earnings',lambda:None),patch.object(sys,'argv',['backtest','--output',tmp,'--initial','123','--monthly','0']):
   bt.main();root=pathlib.Path(tmp);result=json.loads((root/'results.json').read_text());self.assertEqual(result['verdicts'],{'weighting':'YES','refill':'YES','defense':'YES'});self.assertEqual(result['summary'][0]['ann_return'],-.5);self.assertEqual(result['primary_summary'][0]['ann_return'],.2)
   self.assertEqual(pd.read_csv(root/'summary.csv').iloc[0]['ann_return'],.2);html=(root/'index.html').read_text();self.assertIn('$123 start',html);self.assertIn('$0/month',html);self.assertIn('undefined',html)
 def test_no_legacy_fallback(self):
  bt=self.load_core()
  with self.assertRaises(KeyError):bt.performance_rows([{'strategy':'fixture','ann_return':999}])
 def test_defense_primary_dataframe_and_undefined_delta(self):
  source=(ENGINE/'defense_mix_test.py').read_text();self.assertIn('pd.DataFrame(bt.performance_rows(rows))',source);self.assertNotIn('pd.DataFrame(rows)',source)
  tree=ast.parse(source);f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='metric_delta');ns={'pd':pd};exec(compile(ast.Module(body=[f],type_ignores=[]),'delta','exec'),ns)
  r=pd.Series({'ann_return':.1,'ann_vol':.2,'sharpe':None,'sortino':None,'max_drawdown':-.1,'worst_month':-.1,'ending_value':100});d=ns['metric_delta'](r,r);self.assertIsNone(d['sharpe_vs_rsp']);self.assertIsNone(d['sortino_vs_rsp'])
 def test_historical_metric_paths_explicit(self):
  source=(ENGINE/'historical_validation.py').read_text();self.assertEqual(source.count('"primary_metric_path": "performance.metrics"'),2);self.assertIn('"anchor": anchor["performance"]["metrics"]',source)
if __name__=='__main__':unittest.main(verbosity=2)
