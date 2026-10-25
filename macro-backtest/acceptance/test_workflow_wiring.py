"""Static wiring contract: no live backtest or provider calls."""
import pathlib, unittest, yaml
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def workflow(path):return yaml.load(path.read_text(),Loader=yaml.BaseLoader)
class Wiring(unittest.TestCase):
 def test_existing_triggers_preserved(self):
  for name in ['macro-defense-mix-test.yml','macro-historical-validation.yml']:
   d=workflow(ROOT/'.github/workflows'/name)
   self.assertEqual(set(d['on']),{'push','workflow_dispatch'})
   self.assertEqual(d['on']['push']['branches'],['macro-backtest-v08'])
 def test_generation_pins_and_captures(self):
  for name in ['macro-defense-mix-test.yml','macro-historical-validation.yml']:
   d=workflow(ROOT/'.github/workflows'/name);steps=next(iter(d['jobs'].values()))['steps']
   checkout=next(x for x in steps if x.get('uses')=='actions/checkout@v4')
   self.assertEqual(checkout['with']['ref'],'${{ github.sha }}')
   text=str(steps)
   self.assertIn('acceptance_runtime.py capture',text)
   self.assertIn('results-provenance/',text)
   self.assertIn('actions/upload-artifact@v4',text)
   self.assertNotIn('acceptance_runtime.py verify',text) # cannot certify own completion
 def test_observer_exact_allowlist(self):
  d=workflow(HERE/'observer-workflow.yml')
  self.assertEqual(set(d['on']),{'workflow_run','pull_request'})
  self.assertEqual(d['on']['pull_request']['branches'],['main'])
  self.assertIn("github.event_name == 'workflow_run'",d['jobs']['completed-run-gate']['if'])
  self.assertEqual(d['on']['workflow_run']['workflows'],['MACRO Defense Mix Test','MACRO Historical Validation'])
  self.assertEqual(d['on']['workflow_run']['branches'],['macro-backtest-v08'])
  self.assertEqual(d['on']['workflow_run']['types'],['completed'])
  self.assertEqual(d['permissions'],{'contents':'read','actions':'read'})
  text=(HERE/'observer-workflow.yml').read_text()
  for needle in ['369746177','374956997','head_repository','SOURCE_ATTEMPT','verify_persisted_capture.py','accept_observed_capture.py']:self.assertIn(needle,text)
  for forbidden in ['workflow_dispatch:', 'schedule:', 'contents: write', 'repository_dispatch', 'yfinance', 'backtest.py capture']:self.assertNotIn(forbidden,text)
 def test_fixture_workflow_cannot_launch_portfolio(self):
  d=workflow(ROOT/'.github/workflows/macro-acceptance-fixtures.yml')
  self.assertEqual(set(d['on']),{'pull_request'})
  self.assertEqual(d['permissions'],{'contents':'read'})
  text=str(d)
  self.assertIn('test_contract.py',text);self.assertIn('test_engine_metrics.py',text);self.assertIn('test_integration',text)
  self.assertNotIn('workflow_dispatch',text);self.assertNotIn('acceptance_runtime.py capture',text)
if __name__=='__main__':unittest.main(verbosity=2)
