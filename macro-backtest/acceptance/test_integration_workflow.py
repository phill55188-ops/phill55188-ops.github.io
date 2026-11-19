"""Synthetic Git persistence/provider-envelope checks; never contacts a service."""
import copy, importlib.util, json, pathlib, shutil, subprocess, tempfile, unittest
HERE=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('persisted',HERE/'verify_persisted_capture.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PersistedCapture(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
  self.g('init','-q');self.g('config','user.name','Fixture');self.g('config','user.email','fixture@example.invalid')
  (self.repo/'README').write_text('synthetic code only');self.g('add','.');self.g('commit','-qm','code');self.code=self.g('rev-parse','HEAD')
  self.prefix='macro-backtest/results-provenance/123-1/defense';bundle=self.repo/self.prefix;bundle.mkdir(parents=True)
  (bundle/'capture-manifest.json').write_text(json.dumps({'status':'CAPTURED'}));(bundle/'data.bin').write_bytes(b'synthetic fixture')
  self.g('add','.');self.g('commit','-qm','result');self.result=self.g('rev-parse','HEAD')
  self.capture=self.root/'captured';self.capture.mkdir();shutil.copytree(bundle,self.capture/'bundle')
  self.seal={'result_commit':self.result,'bundle_path':self.prefix,'kind':'defense'};self.write_seal()
  self.g('checkout','-q','--detach',self.code)
  self.run={'repository':{'full_name':m.REPO},'head_repository':{'full_name':m.REPO},'id':123,'run_attempt':1,'head_branch':'macro-backtest-v08','head_sha':self.code,'event':'push','status':'completed','conclusion':'success','workflow_id':369746177,'name':'MACRO Defense Mix Test','path':'.github/workflows/macro-defense-mix-test.yml'}
  self.art={'id':321,'name':'macro-capture-123-1','expired':False,'workflow_run':{'id':123,'head_sha':self.code}}
 def tearDown(self):self.tmp.cleanup()
 def g(self,*args):return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.DEVNULL,text=True).strip()
 def write_seal(self):(self.capture/'seal.json').write_text(json.dumps(self.seal))
 def verify(self):return m.verify(self.repo,self.capture,self.run,self.art)
 def reject(self):
  with self.assertRaises(Exception):self.verify()
 def test_positive_actual_git_bytes(self):self.assertEqual(self.verify()['files_verified'],2)
 def test_wrong_repo(self):self.run['repository']['full_name']='other/repo';self.reject()
 def test_fork_head(self):self.run['head_repository']['full_name']='fork/repo';self.reject()
 def test_wrong_branch(self):self.run['head_branch']='main';self.reject()
 def test_unapproved_event(self):self.run['event']='pull_request';self.reject()
 def test_running_not_success(self):self.run['status']='in_progress';self.reject()
 def test_failure_not_success(self):self.run['conclusion']='failure';self.reject()
 def test_workflow_id(self):self.run['workflow_id']=123;self.reject()
 def test_workflow_path(self):self.run['path']='wrong';self.reject()
 def test_checkout_mismatch(self):self.run['head_sha']='a'*40;self.reject()
 def test_wrong_attempt_path(self):self.run['run_attempt']=2;self.reject()
 def test_malicious_result_ref(self):self.seal['result_commit']='HEAD:secret';self.write_seal();self.reject()
 def test_wrong_artifact(self):self.art['name']='other';self.reject()
 def test_expired(self):self.art['expired']=True;self.reject()
 def test_artifact_other_run(self):self.art['workflow_run']['id']=456;self.reject()
 def test_changed_bytes(self):(self.capture/'bundle/data.bin').write_bytes(b'changed');self.reject()
 def test_extra_file(self):(self.capture/'bundle/untracked').write_text('extra');self.reject()
 def test_missing_file(self):(self.capture/'bundle/data.bin').unlink();self.reject()
 def test_symlink(self):
  p=self.capture/'bundle/data.bin';p.unlink();p.symlink_to(self.repo/'README');self.reject()
if __name__=='__main__':unittest.main(verbosity=2)
