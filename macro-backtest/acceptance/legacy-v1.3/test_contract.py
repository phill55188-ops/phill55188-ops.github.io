"""Synthetic offline contracts, not workflow authentication or live backtests."""
import copy, datetime, hashlib, importlib.util, json, pathlib, tempfile, unittest
P=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('validator',P/'validate-backtest-result.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
NOW=datetime.date(2026,10,25)
class ContractTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def save(self,path,value):
  b=json.dumps(value,sort_keys=True).encode();(self.root/path).write_bytes(b);return {'path':path,'sha256':hashlib.sha256(b).hexdigest()}
 def fixture(self,kind='COMMON_WINDOW_ARCHITECTURE'):
  historical=kind!='COMMON_WINDOW_ARCHITECTURE';repo='phill55188-ops/phill55188-ops.github.io'
  identity={'repository':repo,'branch':'macro-backtest-v08','code_commit':'a'*40,'workflow_path':'.github/workflows/macro-historical-validation.yml' if historical else '.github/workflows/macro-defense-mix-test.yml','workflow_run_id':123,'workflow_run_attempt':1,'test_type':kind,'information_set':'synthetic frozen information set'}
  metrics={'ann_return':0.1,'ann_vol':0.2,'sharpe':0.5,'sortino':0.7,'max_drawdown':-0.1,'worst_month':-0.05,'ending_value':123,'months':3,'undefined_reasons':{}}
  history={'status':'COMPLETE' if historical else 'NOT_APPLICABLE','scope':'synthetic evidence only','missing_items':[],'items':[]}
  if historical:history['items'].append({'source_ref':'fixture:anchor','source_version':'1','bounded_sha256':'b'*64,'known_at':'2026-06-01','effective_date':'2026-06-01','applied_date':None,'classification':'ANCHOR','check':'PASS','event_sha256':None})
  if kind=='EVENT_DATED_SYSTEM':history['items'].append({'source_ref':'fixture:event','source_version':'2','bounded_sha256':'c'*64,'known_at':'2026-07-01','effective_date':'2026-07-02','applied_date':'2026-07-02','classification':'EVENT','check':'PASS','event_sha256':None})
  event={'date':'2026-07-02','type':'BUY_DOLLARS','ticker':'SYNTHETIC','dollars':5}
  if kind=='EVENT_DATED_SYSTEM':history['items'][1]['event_sha256']=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  rawmetrics={k:x for k,x in metrics.items() if k!='undefined_reasons'}
  raw={'metrics':rawmetrics,'test_type':kind} if historical else {'summary':[{'strategy':'synthetic',**rawmetrics}]}
  if kind=='EVENT_DATED_SYSTEM':raw['events_applied']=[{**event,'status':'APPLIED','execution_date':'2026-07-02'}]
  artifact={'kind':'git_file','id':repo+'@'+'d'*40+':raw.json','result_commit':'d'*40,**self.save('raw.json',raw)}
  r={'schema_version':'1.3','scenario_id':'historical_single_run' if historical else 'synthetic','status':'COMPLETE','limitations':['synthetic fixture; no remote authentication'],'identity':identity,'requested_start':'2026-06-01','actual_start':'2026-06-30','actual_end':'2026-09-30','checked_as_of':'2026-10-25','anchor_date':'2026-06-01' if historical else None,'start_reason':'fixture','bias_classification':'synthetic','return_month_ends':['2026-07-31','2026-08-31','2026-09-30'],'metrics':metrics,'metric_convention':'historical_value_pct_change_v1' if historical else 'core_pre_contribution_v1','inputs':{'config':self.save('config.json',{'fixture':True,**({'events':[event]} if kind=='EVENT_DATED_SYSTEM' else {})}),'data':[self.save('data.json',[1,2,3])],'historical_manifest':self.save('history.json',history)},'historical_evidence':history,'artifact':artifact,'trade_authority':False}
  r['data_coverage']=[{'path':'data.json','retrieved_at':'2026-10-24T00:00:00Z','months':[{'month_end':d,'last_observation':d,'expected_last_session':d,'calendar_source':'synthetic calendar'} for d in r['return_month_ends']]}]
  q={'identity':copy.deepcopy(identity),'status':'completed','conclusion':'success','artifact':copy.deepcopy(artifact),'receipt_source':'fixture:github-not-called','verified_at':'2026-10-25T00:00:00Z','inputs':copy.deepcopy(r['inputs'])}
  return r,q
 def reject(self,r,q):
  with self.assertRaises(Exception):v.validate(r,q,self.root,NOW)
 def raw_update(self,r,q,func):
  raw=json.loads((self.root/'raw.json').read_text());func(raw);info=self.save('raw.json',raw);r['artifact'].update(info);q['artifact'].update(info)
 def history_update(self,r,q):
  r['inputs']['historical_manifest']=self.save('history.json',r['historical_evidence']);q['inputs']=copy.deepcopy(r['inputs'])
 def test_positive_all_three(self):
  for kind in ['COMMON_WINDOW_ARCHITECTURE','ANCHOR_FORWARD_THESIS','EVENT_DATED_SYSTEM']:
   with self.subTest(kind=kind):
    r,q=self.fixture(kind);self.assertEqual(v.validate(r,q,self.root,NOW)['contract'],'PASS')
 def test_empty_rejected(self):self.reject({}, {})
 def test_missing_metric(self):
  r,q=self.fixture();del r['metrics']['ann_return'];self.reject(r,q)
 def test_invalid_type(self):
  r,q=self.fixture();r['identity']['test_type']='BACKTEST';self.reject(r,q)
 def test_type_array(self):
  r,q=self.fixture();r['identity']['test_type']=['COMMON_WINDOW_ARCHITECTURE'];self.reject(r,q)
 def test_null_needs_reason(self):
  r,q=self.fixture();r['metrics']['sortino']=None;self.raw_update(r,q,lambda x:x['summary'][0].update(sortino=None));self.reject(r,q)
 def test_null_with_reason_passes(self):
  r,q=self.fixture();r['metrics']['sortino']=None;r['metrics']['undefined_reasons']['sortino']='Fewer than two negative observations';self.raw_update(r,q,lambda x:x['summary'][0].update(sortino=None));self.assertEqual(v.validate(r,q,self.root,NOW)['contract'],'PASS')
 def test_extraneous_null_reason(self):
  r,q=self.fixture();r['metrics']['undefined_reasons']['sortino']='reason';self.reject(r,q)
 def test_nonfinite(self):
  for value in [float('nan'),float('inf'),float('-inf')]:
   r,q=self.fixture();r['metrics']['ann_return']=value;self.reject(r,q)
 def test_bad_calendar_date(self):
  r,q=self.fixture();r['actual_end']='2026-02-30';self.reject(r,q)
 def test_month_count(self):
  r,q=self.fixture();r['metrics']['months']=2;self.raw_update(r,q,lambda x:x['summary'][0].update(months=2));self.reject(r,q)
 def test_month_not_end(self):
  r,q=self.fixture();r['return_month_ends'][0]='2026-07-30';self.reject(r,q)
 def test_duplicate_months(self):
  r,q=self.fixture();r['return_month_ends'][0]='2026-08-31';self.reject(r,q)
 def test_unsorted_months(self):
  r,q=self.fixture();r['return_month_ends'][:2]=reversed(r['return_month_ends'][:2]);self.reject(r,q)
 def test_future_month(self):
  r,q=self.fixture();r['actual_end']='2026-10-31';r['return_month_ends'][-1]='2026-10-31';self.reject(r,q)
 def test_future_asof(self):
  r,q=self.fixture();r['checked_as_of']='2026-11-01';self.reject(r,q)
 def test_start_after_end(self):
  r,q=self.fixture();r['actual_start']='2026-10-01';self.reject(r,q)
 def test_anchor_leak(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');r['historical_evidence']['items'][0]['known_at']='2026-06-02';self.history_update(r,q);self.reject(r,q)
 def test_anchor_missing(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');r['anchor_date']=None;self.reject(r,q)
 def test_event_backdated(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');r['historical_evidence']['items'][1]['applied_date']='2026-07-01';self.history_update(r,q);self.reject(r,q)
 def test_future_evidence(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');r['historical_evidence']['items'][1]['known_at']='2026-12-01';self.history_update(r,q);self.reject(r,q)
 def test_cross_run(self):
  r,q=self.fixture();q['identity']['workflow_run_id']=124;self.reject(r,q)
 def test_attempt_mismatch(self):
  r,q=self.fixture();q['identity']['workflow_run_attempt']=2;self.reject(r,q)
 def test_code_mismatch(self):
  r,q=self.fixture();q['identity']['code_commit']='f'*40;self.reject(r,q)
 def test_info_mismatch(self):
  r,q=self.fixture();q['identity']['information_set']='other';self.reject(r,q)
 def test_artifact_mismatch(self):
  r,q=self.fixture();q['artifact']['sha256']='f'*64;self.reject(r,q)
 def test_bad_artifact_id(self):
  r,q=self.fixture();r['artifact']['id']=q['artifact']['id']='other';self.reject(r,q)
 def test_failed_workflow(self):
  r,q=self.fixture();q['conclusion']='failure';self.reject(r,q)
 def test_wrong_workflow(self):
  r,q=self.fixture();r['identity']['workflow_path']=q['identity']['workflow_path']='unknown';self.reject(r,q)
 def test_wrong_metric_convention(self):
  r,q=self.fixture();r['metric_convention']='historical_value_pct_change_v1';self.reject(r,q)
 def test_raw_metric_mismatch(self):
  r,q=self.fixture();self.raw_update(r,q,lambda x:x['summary'][0].update(ann_return=0.99));self.reject(r,q)
 def test_raw_missing_nullable_metric(self):
  r,q=self.fixture();r['metrics']['sortino']=None;r['metrics']['undefined_reasons']['sortino']='undefined';self.raw_update(r,q,lambda x:x['summary'][0].pop('sortino'));self.reject(r,q)
 def test_raw_infinity_not_null(self):
  r,q=self.fixture();r['metrics']['sortino']=None;r['metrics']['undefined_reasons']['sortino']='undefined';self.raw_update(r,q,lambda x:x['summary'][0].update(sortino=float('inf')));self.reject(r,q)
 def test_scenario_mismatch(self):
  r,q=self.fixture();r['scenario_id']='another';self.reject(r,q)
 def test_raw_type_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');self.raw_update(r,q,lambda x:x.update(test_type='EVENT_DATED_SYSTEM'));self.reject(r,q)
 def test_data_digest(self):
  r,q=self.fixture();(self.root/'data.json').write_text('changed');self.reject(r,q)
 def test_raw_digest(self):
  r,q=self.fixture();(self.root/'raw.json').write_text('{}');self.reject(r,q)
 def test_config_digest(self):
  r,q=self.fixture();(self.root/'config.json').write_text('{}');self.reject(r,q)
 def test_path_escape(self):
  r,q=self.fixture();r['inputs']['config']['path']='../config.json';self.reject(r,q)
 def test_history_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');r['historical_evidence']['scope']='changed';self.reject(r,q)
 def test_incomplete(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');r['status']='INCOMPLETE';r['historical_evidence']['status']='INCOMPLETE';r['historical_evidence']['missing_items']=['losers'];self.history_update(r,q);self.reject(r,q)
 def test_trade_authority(self):
  r,q=self.fixture();r['trade_authority']=True;self.reject(r,q)
 def test_stale_partial_month(self):
  r,q=self.fixture();r['data_coverage'][0]['months'][0]['last_observation']='2026-07-15';self.reject(r,q)
 def test_missing_coverage_month(self):
  r,q=self.fixture();r['data_coverage'][0]['months'].pop();self.reject(r,q)
 def test_wrong_coverage_dataset(self):
  r,q=self.fixture();r['data_coverage'][0]['path']='other.json';self.reject(r,q)
 def test_future_retrieved(self):
  r,q=self.fixture();r['data_coverage'][0]['retrieved_at']='2026-10-26T00:00:00Z';self.reject(r,q)
 def test_legacy_nan_ratio_passes(self):
  r,q=self.fixture();r['metrics']['sortino']=None;r['metrics']['undefined_reasons']['sortino']='Fewer than two negative observations';self.raw_update(r,q,lambda x:x['summary'][0].update(sortino=float('nan')));self.assertEqual(v.validate(r,q,self.root,NOW)['contract'],'PASS')
 def test_raw_nan_nonratio_rejected(self):
  r,q=self.fixture();self.raw_update(r,q,lambda x:x['summary'][0].update(ann_return=float('nan')));self.reject(r,q)
 def test_raw_anchor_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');self.raw_update(r,q,lambda x:x.update(anchor_date='2026-05-01'));self.reject(r,q)
 def test_raw_start_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');self.raw_update(r,q,lambda x:x.update(actual_start='2026-06-02'));self.reject(r,q)
 def test_raw_info_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');self.raw_update(r,q,lambda x:x.update(information_set='different information set'));self.reject(r,q)
 def test_future_receipt_time(self):
  r,q=self.fixture();q['verified_at']='2026-10-26T00:00:00Z';self.reject(r,q)
 def test_retrieval_before_data_end(self):
  r,q=self.fixture();r['data_coverage'][0]['retrieved_at']='2026-09-01T00:00:00Z';self.reject(r,q)
 def test_raw_boolean_not_numeric(self):
  r,q=self.fixture();r['metrics']['sharpe']=1.0;self.raw_update(r,q,lambda x:x['summary'][0].update(sharpe=True));self.reject(r,q)
 def test_config_anchor_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');r['inputs']['config']=self.save('config.json',{'anchor_date':'2026-05-01'});q['inputs']=copy.deepcopy(r['inputs']);self.reject(r,q)
 def test_config_type_mismatch(self):
  r,q=self.fixture('ANCHOR_FORWARD_THESIS');r['inputs']['config']=self.save('config.json',{'test_type':'EVENT_DATED_SYSTEM'});q['inputs']=copy.deepcopy(r['inputs']);self.reject(r,q)
 def test_event_missing_applied_date(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');r['historical_evidence']['items'][1]['applied_date']=None;self.history_update(r,q);self.reject(r,q)
 def test_receipt_inputs_mismatch(self):
  r,q=self.fixture();r['inputs']['config']=self.save('config.json',{'changed':True});self.reject(r,q)
 def test_event_raw_ledger_missing(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');self.raw_update(r,q,lambda x:x.update(events_applied=[]));self.reject(r,q)
 def test_event_config_ledger_missing(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');r['inputs']['config']=self.save('config.json',{'events':[]});q['inputs']=copy.deepcopy(r['inputs']);self.reject(r,q)
 def test_event_raw_fingerprint_mismatch(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');self.raw_update(r,q,lambda x:x['events_applied'][0].update(dollars=6));self.reject(r,q)
 def test_event_raw_execution_date_mismatch(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');self.raw_update(r,q,lambda x:x['events_applied'][0].update(execution_date='2026-07-03'));self.reject(r,q)
 def test_event_raw_status_mismatch(self):
  r,q=self.fixture('EVENT_DATED_SYSTEM');self.raw_update(r,q,lambda x:x['events_applied'][0].update(status='QUEUED'));self.reject(r,q)
 def excluded_fixture(self,documented=True):
  r,q=self.fixture('EVENT_DATED_SYSTEM')
  event={'date':'2026-07-02','type':'SELL_DOLLARS','ticker':'SYNTHETIC','dollars':5}
  if documented:event['classification']='EXOGENOUS'
  h=r['historical_evidence']['items'][1];h['classification']='EXOGENOUS';h['applied_date']=None;h['event_sha256']=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  r['inputs']['config']=self.save('config.json',{'events':[event],'exclude_exogenous':True})
  self.history_update(r,q);self.raw_update(r,q,lambda x:x.update(events_applied=[{**event,'status':'EXCLUDED_EXOGENOUS'}]))
  return r,q
 def test_documented_exogenous_exclusion_passes(self):
  r,q=self.excluded_fixture();self.assertEqual(v.validate(r,q,self.root,NOW)['contract'],'PASS')
 def test_undocumented_exogenous_exclusion_rejected(self):
  r,q=self.excluded_fixture(False);self.reject(r,q)
if __name__=='__main__':unittest.main(verbosity=2)
