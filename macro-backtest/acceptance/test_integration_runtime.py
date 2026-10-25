"""Synthetic runtime integration tests. No provider calls or real portfolio."""
import copy, datetime as dt, importlib.util, json, os, pathlib, subprocess, tempfile, unittest
P=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('runtime',P/'acceptance_runtime.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
CONTRACT=pathlib.Path(os.environ.get('MACRO_ACCEPTANCE_CONTRACT_DIR',str(P)))

class RuntimeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.bundle=self.root/'macro-backtest/results-provenance/123-1/defense';self.bundle.mkdir(parents=True)
  self.g('init','-q');self.g('config','user.name','Fixture');self.g('config','user.email','fixture@example.invalid');(self.root/'source.txt').write_text('synthetic');self.g('add','.');self.g('commit','-qm','source');self.code=self.g('rev-parse','HEAD')
  self.identity={'repository':r.REPOSITORY,'branch':'macro-backtest-v08','code_commit':self.code,'workflow_path':'.github/workflows/macro-defense-mix-test.yml','workflow_run_id':123,'workflow_run_attempt':1}
  self.provider={'id':123,'run_attempt':1,'repository':{'full_name':r.REPOSITORY},'path':self.identity['workflow_path'],'head_sha':self.code,'head_branch':'macro-backtest-v08','status':'completed','conclusion':'success','html_url':f'https://github.com/{r.REPOSITORY}/actions/runs/123'}
  def save(name,value):
   p=self.bundle/name;p.parent.mkdir(exist_ok=True);r.dump(p,value);return {'path':name,'sha256':r.sha(p.read_bytes())}
  config=save('config.json',{'scenario_id':'FIXTURE','test_type':'COMMON_WINDOW_ARCHITECTURE','requested_start':'2026-06-01'})
  data=save('inputs.json',{'synthetic':True})
  raw=save('output/raw.json',{'results':[{'strategy':'FIXTURE','ann_return':.1,'ann_vol':.2,'sharpe':.5,'sortino':None,'max_drawdown':-.1,'worst_month':-.05,'ending_value':120.,'months':3}]})
  months=['2026-07-31','2026-08-31','2026-09-30']
  call={'scenario_id':'FIXTURE','config':config,'data':[data],'actual_start':'2026-06-30','requested_start':'2026-06-01','return_month_ends':months,'test_type':'COMMON_WINDOW_ARCHITECTURE','data_coverage':[{'path':'inputs.json','retrieved_at':'2026-10-24T00:00:00Z','months':[{'month_end':x,'last_observation':x,'expected_last_session':x,'calendar_source':'synthetic calendar'} for x in months]}]}
  self.manifest={'format':'macro-capture-1','status':'CAPTURED','execution':self.identity,'bundle_path':self.bundle.relative_to(self.root).as_posix(),'files':[config,data],'outputs':[raw],'calls':[call]}
  r.dump(self.bundle/'capture-manifest.json',self.manifest);self.g('add','.');self.g('commit','-qm','synthetic captured result');self.result_commit=self.g('rev-parse','HEAD')
  self.records=r.prepare_common(self.bundle,self.result_commit,self.root/'acceptance')
 def tearDown(self):self.tmp.cleanup()
 def g(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],text=True).strip()
 def verify(self):return r.verify_bundle(self.bundle,self.provider,self.records,CONTRACT,self.result_commit)
 def test_end_to_end_supplied_completed_run(self):self.assertEqual(self.verify()['status'],'ACCEPTED')
 def test_pending_provider_rejected(self):self.provider['status']='in_progress';self.assertRaises(ValueError,self.verify)
 def test_failed_provider_rejected(self):self.provider['conclusion']='failure';self.assertRaises(ValueError,self.verify)
 def test_wrong_provider_code(self):self.provider['head_sha']='f'*40;self.assertRaises(ValueError,self.verify)
 def test_wrong_provider_run(self):self.provider['id']=456;self.assertRaises(ValueError,self.verify)
 def test_wrong_provider_attempt(self):self.provider['run_attempt']=2;self.assertRaises(ValueError,self.verify)
 def test_wrong_provider_repo(self):self.provider['repository']['full_name']='other/repo';self.assertRaises(ValueError,self.verify)
 def test_capture_hash_mutation(self):(self.bundle/'inputs.json').write_text('{}');self.assertRaises(ValueError,self.verify)
 def test_unpersisted_raw_mutation(self):
  raw=self.bundle/'output/raw.json';v=r.load(raw);v['results'][0]['ann_return']=.2;r.dump(raw,v);self.manifest['outputs'][0]['sha256']=r.sha(raw.read_bytes());r.dump(self.bundle/'capture-manifest.json',self.manifest);self.records=r.prepare_common(self.bundle,self.result_commit,self.root/'acceptance');self.assertRaises(ValueError,self.verify)
 def test_missing_sidecars(self):self.records=[];self.assertRaises(ValueError,self.verify)
 def test_missing_scenario(self):
  self.manifest['calls'].append({**self.manifest['calls'][0],'scenario_id':'NOT_COVERED'});r.dump(self.bundle/'capture-manifest.json',self.manifest);self.assertRaises(ValueError,self.verify)
 def test_wrong_sidecar_input(self):
  v=r.load(self.records[0]);v['inputs']['data'][0]['sha256']='a'*64;r.dump(self.records[0],v);self.assertRaises(ValueError,self.verify)
 def test_wrong_sidecar_dates(self):
  v=r.load(self.records[0]);v['return_month_ends'][0]='2026-07-30';r.dump(self.records[0],v);self.assertRaises(ValueError,self.verify)
 def test_coverage_observation_override_rejected(self):
  v=r.load(self.records[0]);v['data_coverage'][0]['months'][0]['last_observation']='2026-07-30';r.dump(self.records[0],v)
  with self.assertRaisesRegex(ValueError,'coverage differs'):self.verify()
 def test_coverage_calendar_override_rejected(self):
  v=r.load(self.records[0]);v['data_coverage'][0]['months'][0]['calendar_source']='invented override';r.dump(self.records[0],v)
  with self.assertRaisesRegex(ValueError,'coverage differs'):self.verify()
 def test_coverage_path_override_rejected(self):
  v=r.load(self.records[0]);v['data_coverage'][0]['path']='inputs.json';r.dump(self.records[0],v)
  with self.assertRaisesRegex(ValueError,'coverage differs'):self.verify()
 def test_historical_not_invented(self):
  self.manifest['calls'][0]['test_type']='ANCHOR_FORWARD_THESIS';r.dump(self.bundle/'capture-manifest.json',self.manifest);self.assertRaises(ValueError,r.prepare_common,self.bundle,self.result_commit,self.root/'acceptance')
 def test_historical_supplied_only_manifest_rejected(self):
  self.manifest['calls'][0]['test_type']='ANCHOR_FORWARD_THESIS';r.dump(self.bundle/'capture-manifest.json',self.manifest)
  self.g('add','.');self.g('commit','-qm','historical fixture');self.result_commit=self.g('rev-parse','HEAD')
  v=r.load(self.records[0]);v['identity']['test_type']='ANCHOR_FORWARD_THESIS';r.dump(self.records[0],v)
  with self.assertRaisesRegex(ValueError,'historical evidence transport missing'):self.verify()
 def historical_fixture(self,kind='ANCHOR_FORWARD_THESIS'):
  evidence=self.root/'public-evidence.txt';evidence.write_text('SYNTHETIC PUBLIC FIXTURE: historical reviewed record, not real user history')
  digest=r.sha(evidence.read_bytes());item={'source_ref':'fixture:public-record','source_version':'synthetic-v1','bounded_sha256':digest,'known_at':'2026-06-01','effective_date':'2026-06-01','applied_date':None,'classification':'ANCHOR','check':'PASS','event_sha256':None}
  event={'date':'2026-07-02','type':'BUY_DOLLARS','ticker':'SYNTHETIC','dollars':5}
  items=[item]
  if kind=='EVENT_DATED_SYSTEM':items.append({**item,'known_at':'2026-07-01','effective_date':'2026-07-02','applied_date':'2026-07-02','classification':'EVENT','event_sha256':r.sha(json.dumps(event,sort_keys=True,separators=(',',':')).encode())})
  history={'status':'COMPLETE','scope':'Synthetic reviewed public evidence only','missing_items':[],'items':items}
  transport={'visibility':'PUBLIC_REVIEWED','reviewer_assertion':'Fixture author asserts public synthetic bytes; not source truth authentication','information_set':'Synthetic frozen public fixture','historical_evidence':history,'sources':[{'path':'public-evidence.txt','sha256':digest,'source_ref':'fixture:public-record','source_version':'synthetic-v1'}]}
  r.dump(self.root/'public-history.json',transport);self.g('add','.');self.g('commit','-qm','public synthetic source');self.code=self.g('rev-parse','HEAD')
  bundle=self.root/'macro-backtest/results-provenance/123-1/historical'
  env={'GITHUB_REPOSITORY':r.REPOSITORY,'GITHUB_REF_NAME':'macro-backtest-v08','GITHUB_SHA':self.code,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
  cap=r.Capture(self.root,bundle,'macro-backtest/historical_validation.py',[],env,historical_evidence='public-history.json')
  config=cap.config({'test_type':kind,'information_set':transport['information_set'],'anchor_date':'2026-06-01','events':[event] if kind=='EVENT_DATED_SYSTEM' else []})
  data=cap.save_bytes('inputs.json',b'{"synthetic":true}','engine-prices');call=copy.deepcopy(self.manifest['calls'][0]);call.update(scenario_id='historical_single_run',test_type=kind,config=config,data=[data]);cap.manifest['calls']=[call]
  raw={'metrics':{'ann_return':.1,'ann_vol':.2,'sharpe':.5,'sortino':None,'max_drawdown':-.1,'worst_month':-.05,'ending_value':120.,'months':3},'test_type':kind}
  if kind=='EVENT_DATED_SYSTEM':raw['events_applied']=[{**event,'status':'APPLIED','execution_date':'2026-07-02'}]
  output=self.root/'historical-output';output.mkdir();r.dump(output/'raw.json',raw);cap.finish(output)
  self.bundle=bundle;self.manifest=cap.manifest;self.provider.update(head_sha=self.code,path='.github/workflows/macro-historical-validation.yml')
  self.g('add','.');self.g('commit','-qm','historical captured synthetic result');self.result_commit=self.g('rev-parse','HEAD');self.records=r.prepare_historical(self.bundle,self.result_commit,self.root/'historical-acceptance')
 def test_historical_anchor_positive(self):
  self.historical_fixture();self.assertEqual(self.verify()['status'],'ACCEPTED')
 def test_historical_event_positive(self):
  self.historical_fixture('EVENT_DATED_SYSTEM');self.assertEqual(self.verify()['status'],'ACCEPTED')
 def test_historical_source_tampered(self):
  self.historical_fixture();(self.bundle/'historical-source-000.bin').write_bytes(b'changed');self.assertRaises(ValueError,self.verify)
 def test_historical_supplied_manifest_override(self):
  self.historical_fixture();v=r.load(self.records[0]);v['inputs']['historical_manifest']['path']='other.json';r.dump(self.records[0],v);self.assertRaises(ValueError,self.verify)
 def test_historical_known_date_override(self):
  self.historical_fixture();v=r.load(self.records[0]);v['historical_evidence']['items'][0]['known_at']='2026-12-01';r.dump(self.records[0],v);self.assertRaises(ValueError,self.verify)
 def test_historical_config_override(self):
  self.historical_fixture();v=r.load(self.records[0]);v['inputs']['config']['sha256']='f'*64;r.dump(self.records[0],v);self.assertRaises(ValueError,self.verify)
 def historical_recapture(self,mutation=None,untracked=False):
  self.historical_fixture();t=r.load(self.root/'public-history.json')
  if mutation:mutation(t)
  if untracked:
   (self.root/'untracked-source.txt').write_text('not tracked');t['sources'][0]['path']='untracked-source.txt'
  r.dump(self.root/'public-history.json',t);self.g('add','public-history.json');self.g('commit','-qm','changed fixture transport')
  code=self.g('rev-parse','HEAD');env={'GITHUB_REPOSITORY':r.REPOSITORY,'GITHUB_REF_NAME':'macro-backtest-v08','GITHUB_SHA':code,'GITHUB_RUN_ID':'124','GITHUB_RUN_ATTEMPT':'1'}
  return r.Capture(self.root,self.root/'macro-backtest/results-provenance/124-1/historical','macro-backtest/historical_validation.py',[],env,historical_evidence='public-history.json')
 def test_historical_private_marker_rejected(self):
  with self.assertRaisesRegex(ValueError,'public reviewed'):self.historical_recapture(lambda t:t.update(visibility='PRIVATE'))
 def test_historical_no_reviewer_rejected(self):
  with self.assertRaisesRegex(ValueError,'reviewer assertion'):self.historical_recapture(lambda t:t.update(reviewer_assertion=''))
 def test_historical_untracked_source_rejected(self):
  with self.assertRaisesRegex(ValueError,'must be tracked'):self.historical_recapture(untracked=True)
 def test_historical_source_ref_mismatch_rejected(self):
  with self.assertRaisesRegex(ValueError,'reference coverage'):self.historical_recapture(lambda t:t['sources'][0].update(source_version='different'))
 def test_historical_absolute_path_rejected(self):
  with self.assertRaisesRegex(ValueError,'relative without traversal'):self.historical_recapture(lambda t:t['sources'][0].update(path=str(self.root/'public-evidence.txt')))
 def test_historical_traversal_rejected(self):
  with self.assertRaisesRegex(ValueError,'relative without traversal'):self.historical_recapture(lambda t:t['sources'][0].update(path='../'+self.root.name+'/public-evidence.txt'))
 def test_historical_symlink_rejected(self):
  def mutate(t):
   (self.root/'linked-source').symlink_to(self.root/'public-evidence.txt');t['sources'][0]['path']='linked-source'
  with self.assertRaisesRegex(ValueError,'symlinks prohibited'):self.historical_recapture(mutate)
 def test_historical_duplicate_identity_rejected(self):
  def mutate(t):t['sources'].append({**t['sources'][0],'path':'another-path'})
  with self.assertRaisesRegex(ValueError,'duplicate historical source identity'):self.historical_recapture(mutate)
 def test_capture_failed(self):self.manifest['status']='FAILED';r.dump(self.bundle/'capture-manifest.json',self.manifest);self.assertRaises(ValueError,self.verify)
 def test_price_calendar_coverage(self):
  import pandas as pd
  class Calendar:
   name='SYNTHETIC'
   def sessions_in_range(self,start,end):return pd.to_datetime(['2026-09-29','2026-09-30'])
  frame=pd.DataFrame({('AAA','Close'):[10.,11.]},index=pd.to_datetime(['2026-09-29','2026-09-30']))
  x=r.price_coverage(frame,['AAA'],['2026-09-30'],'2026-10-01T00:00:00Z','data',Calendar());self.assertEqual(x['months'][0]['last_observation'],'2026-09-30')
  self.assertRaises(ValueError,r.price_coverage,frame.iloc[:1],['AAA'],['2026-09-30'],'2026-10-01T00:00:00Z','data',Calendar())

 def test_actual_capture_with_stubbed_provider(self):
  import types,sys
  from unittest.mock import patch
  import pandas as pd
  folder=self.root/'macro-backtest';folder.mkdir(exist_ok=True)
  (folder/'backtest.py').write_text("import pandas as pd\nFEE=.0005\nDRIFT=.10\ndef run(name,prices,earnings,targets,mode,initial,monthly,cash_target,growth_names):\n return name,{'ann_return':.1,'ann_vol':.2,'sharpe':.5,'sortino':None,'max_drawdown':-.1,'worst_month':-.05,'ending_value':120.,'months':3},pd.DataFrame()\n")
  (folder/'defense_mix_test.py').write_text("import json\nfrom pathlib import Path\nimport yfinance as yf\nimport backtest as bt\nSTART_REQUEST='2026-06-01'\ndef main():\n raw=yf.download(['AAA']);prices=raw['AAA'][['Close']].rename(columns={'Close':'AAA'});name,metrics,_=bt.run('FIXTURE',prices,{}, {'AAA':1.},'benchmark',100,0,0,['AAA']);out=Path('macro-backtest/test-output');out.mkdir(exist_ok=True);(out/'raw.json').write_text(json.dumps({'results':[{'strategy':name,**metrics}]}))\n")
  self.g('add','.');self.g('commit','-qm','synthetic harness')
  frame=pd.DataFrame({('AAA','Close'):[10.,11.,10.,12.]},index=pd.to_datetime(['2026-06-30','2026-07-31','2026-08-31','2026-09-30']))
  fake=types.ModuleType('yfinance');fake.download=lambda *a,**k:frame
  class Ticker:
   def get_earnings_history(self,*a,**k):return pd.DataFrame()
  fake.Ticker=Ticker
  env={'GITHUB_REPOSITORY':r.REPOSITORY,'GITHUB_REF_NAME':'macro-backtest-v08','GITHUB_SHA':self.g('rev-parse','HEAD'),'GITHUB_RUN_ID':'789','GITHUB_RUN_ATTEMPT':'1'}
  bundle=folder/'results-provenance/789-1/defense'
  def coverage(raw,tickers,months,retrieved,path):return {'path':path,'retrieved_at':retrieved,'months':[{'month_end':m,'last_observation':m,'expected_last_session':m,'calendar_source':'synthetic calendar'} for m in months]}
  prior=sys.modules.pop('backtest',None);old=os.getcwd()
  try:
   os.chdir(self.root)
   with patch.dict(sys.modules,{'yfinance':fake}),patch.object(r,'price_coverage',coverage):r.Capture(self.root,bundle,'macro-backtest/defense_mix_test.py',[],env).run(folder/'test-output')
  finally:
   os.chdir(old);sys.modules.pop('backtest',None)
   if prior is not None:sys.modules['backtest']=prior
  m=r.load(bundle/'capture-manifest.json');self.assertEqual(m['status'],'CAPTURED');self.assertEqual(m['calls'][0]['return_month_ends'],['2026-07-31','2026-08-31','2026-09-30'])
  cfg=r.load(bundle/m['calls'][0]['config']['path']);self.assertEqual(cfg['fee'],.0005);self.assertEqual(cfg['drift'],.10);self.assertTrue(m['outputs']);self.assertIn('python',m['runtime_versions'])

if __name__=='__main__':unittest.main(verbosity=2)
