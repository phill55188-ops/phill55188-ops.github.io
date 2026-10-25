"""Synthetic completed-run orchestration, including immutable Git-backed evidence."""
import importlib.util,json,pathlib,shutil,sys,unittest
HERE=pathlib.Path(__file__).resolve().parent

def module(name,filename):
 spec=importlib.util.spec_from_file_location(name,HERE/filename);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
rtests=module('runtime_fixtures','test_integration_runtime.py')
check=module('persisted_fixture','verify_persisted_capture.py')
observer=module('observed_fixture','accept_observed_capture.py')
class ObserverOrchestration(unittest.TestCase):
 def setUp(self):
  self.f=rtests.RuntimeTests('test_end_to_end_supplied_completed_run');self.f.setUp()
  f=self.f;self.job=f.root/'job';self.job.mkdir();self.capture=self.job/'captured';self.capture.mkdir();shutil.copytree(f.bundle,self.capture/'bundle')
  (self.capture/'seal.json').write_text(json.dumps({'result_commit':f.result_commit,'bundle_path':f.manifest['bundle_path'],'kind':'defense'}))
  self.run={**f.provider,'head_repository':{'full_name':rtests.r.REPOSITORY},'event':'push','workflow_id':369746177,'name':'MACRO Defense Mix Test'}
  self.art={'id':321,'name':'macro-capture-123-1','expired':False,'workflow_run':{'id':123,'head_sha':f.code}}
  f.g('checkout','-q','--detach',f.code)
  (self.job/'provider-run.json').write_text(json.dumps(self.run));(self.job/'artifact.json').write_text(json.dumps(self.art))
  self.proof=check.verify(f.root,self.capture,self.run,self.art);(self.job/'proof.json').write_text(json.dumps(self.proof))
 def tearDown(self):self.f.tearDown()
 def evaluate(self):return observer.evaluate(self.f.root,self.capture,self.job/'provider-run.json',self.job/'proof.json',self.job/'gate-result.json')
 def test_completed_observer_positive(self):
  self.assertEqual(self.evaluate(),0)
  value=json.loads((self.job/'gate-result.json').read_text());self.assertEqual(value['status'],'ACCEPTED');self.assertTrue(value['provider_workflow_checked']);self.assertTrue(list((self.job/'acceptance-records').glob('result-*.json')))
 def test_forged_proof_rejected_and_recorded(self):
  self.proof['files_verified']=0;(self.job/'proof.json').write_text(json.dumps(self.proof))
  self.assertEqual(self.evaluate(),1);self.assertEqual(json.loads((self.job/'gate-result.json').read_text())['status'],'INCOMPLETE_OR_REJECTED')
if __name__=='__main__':unittest.main(verbosity=2)
