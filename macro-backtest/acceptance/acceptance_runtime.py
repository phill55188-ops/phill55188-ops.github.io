"""Two-phase Macro evidence capture and post-workflow acceptance. No formula changes.
Capture is used only by an already-authorized generation workflow. Verify never
runs the engine, imports snapshots, contacts providers or invents a run receipt.
"""
import argparse, datetime as dt, hashlib, importlib.util, importlib.metadata, json, math, os, pickle, runpy, shutil, subprocess, sys, time
from pathlib import Path

REPOSITORY='phill55188-ops/phill55188-ops.github.io'
HARNESS={
 'macro-backtest/defense_mix_test.py':('.github/workflows/macro-defense-mix-test.yml','COMMON_WINDOW_ARCHITECTURE'),
 'macro-backtest/historical_validation.py':('.github/workflows/macro-historical-validation.yml',None),
}

def sha(data):return hashlib.sha256(data).hexdigest()
def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
def load(path):
    def bad(x):raise ValueError('nonfinite JSON '+x)
    return json.loads(Path(path).read_text(),parse_constant=bad)
def require(value,msg):
    if not value:raise ValueError(msg)
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()
def relative(path,root):
    p=Path(path).resolve();require(p.is_relative_to(root),'outside allowed evidence root');return p.relative_to(root).as_posix()
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()

def runtime_versions():
    values={'python':sys.version.split()[0]}
    for name in ['numpy','pandas','yfinance','exchange-calendars','jsonschema']:
        try:values[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:values[name]='NOT_INSTALLED'
    return values

def provider_receipt(run,manifest):
    """Check a real API response supplied by the workflow; never infer success."""
    identity=manifest['execution']
    require(run.get('status')=='completed' and run.get('conclusion')=='success','generation workflow not completed successfully')
    require(run.get('id')==identity['workflow_run_id'],'wrong provider run')
    require(run.get('run_attempt')==identity['workflow_run_attempt'],'wrong provider attempt')
    require(run.get('repository',{}).get('full_name')==REPOSITORY,'wrong provider repository')
    require(run.get('path')==identity['workflow_path'],'wrong provider workflow')
    require(run.get('head_sha')==identity['code_commit'],'provider head differs from executed code')
    require(run.get('head_branch')==identity['branch'],'wrong provider branch')
    require(run.get('html_url')==f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}",'unexpected provider URL')
    return run['html_url']

class Capture:
    def __init__(self,root,bundle,harness,argv,env=None,historical_evidence=None):
        self.root=Path(root).resolve();self.bundle=Path(bundle).resolve();self.env=dict(os.environ if env is None else env)
        require(harness in HARNESS,'unsupported harness: explicit review required')
        require(not self.bundle.exists(),'run bundle already exists; never overwrite an attempt')
        require(self.env.get('GITHUB_REPOSITORY')==REPOSITORY,'unexpected repository')
        require(self.env.get('GITHUB_REF_NAME')=='macro-backtest-v08','capture only authoritative branch')
        commit=git(self.root,'rev-parse','HEAD')
        require(commit==self.env.get('GITHUB_SHA'),'checkout must equal triggering commit; pin checkout to github.sha')
        require(not git(self.root,'status','--porcelain','--untracked-files=no'),'tracked source edits invalidate provenance')
        for n,arg in enumerate(argv):
            if arg=='--config' or arg.startswith('--config='):
                require(arg!='--config' or n+1<len(argv),'missing config path')
                value=argv[n+1] if arg=='--config' else arg.split('=',1)[1]
                cfg=relative(self.root/value,self.root);require(git(self.root,'ls-files','--',cfg)==cfg,'historical config must be tracked public repository input')
            if arg=='--output' or arg.startswith('--output='):
                require(arg!='--output' or n+1<len(argv),'missing output path')
                value=argv[n+1] if arg=='--output' else arg.split('=',1)[1];relative(self.root/value,self.root)
        self.bundle.mkdir(parents=True);self.started=time.time_ns();self.counter=0
        self.manifest={'format':'macro-capture-1','runtime_versions':runtime_versions(),'status':'CAPTURING','started_at':utc(),'execution':{'repository':REPOSITORY,'branch':'macro-backtest-v08','code_commit':commit,'workflow_path':HARNESS[harness][0],'workflow_run_id':int(self.env['GITHUB_RUN_ID']),'workflow_run_attempt':int(self.env['GITHUB_RUN_ATTEMPT'])},'bundle_path':relative(self.bundle,self.root),'harness':harness,'argv':argv,'files':[],'calls':[],'outputs':[],'limitations':['Capture manifest is not workflow success or financial acceptance.','Pickle snapshots are opaque evidence; never load untrusted pickle.']}
        if historical_evidence:
            require(harness.endswith('historical_validation.py'),'historical evidence only for historical harness')
            self.manifest['historical_transport']=capture_history(self,historical_evidence)
    def save_bytes(self,name,data,kind,metadata=None):
        path=self.bundle/name;require(not path.exists(),'duplicate capture path');path.write_bytes(data)
        item={'path':name,'sha256':sha(data),'kind':kind,'captured_at':utc(),'metadata':metadata or {}}
        self.manifest['files'].append(item);return {'path':name,'sha256':item['sha256']}
    def snapshot(self,kind,value,metadata=None):
        self.counter+=1;return self.save_bytes(f'{self.counter:04d}-{kind}.pickle',pickle.dumps(value,protocol=5),kind,metadata)
    def config(self,value):
        self.counter+=1;return self.save_bytes(f'{self.counter:04d}-config.json',(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode(),'config')
    def finish(self,output):
        output=Path(output).resolve();require(output.is_relative_to(self.root),'output outside checkout')
        for path in sorted(output.rglob('*')):
            if path.is_file() and path.stat().st_mtime_ns>=self.started:
                name='output/'+path.relative_to(output).as_posix();target=self.bundle/name;target.parent.mkdir(parents=True,exist_ok=True);data=path.read_bytes();target.write_bytes(data)
                self.manifest['outputs'].append({'path':name,'sha256':sha(data),'source_path':relative(path,self.root)})
        require(self.manifest['outputs'],'no freshly written output captured')
        self.manifest['status']='CAPTURED';self.manifest['finished_at']=utc();dump(self.bundle/'capture-manifest.json',self.manifest)
    def run(self,output):
        """Instrument values at engine boundaries, without changing computations."""
        import yfinance as yf
        original_download=yf.download;original_earnings=yf.Ticker.get_earnings_history
        def download(*args,**kwargs):
            value=original_download(*args,**kwargs);self._provider_prices=value;self._provider_retrieved_at=utc();self.snapshot('provider-prices',value,{'args':repr(args),'kwargs':repr(kwargs)});return value
        def earnings(ticker,*args,**kwargs):
            value=original_earnings(ticker,*args,**kwargs);self.snapshot('provider-earnings',value,{'ticker':str(getattr(ticker,'ticker','unknown'))});return value
        yf.download=download;yf.Ticker.get_earnings_history=earnings
        oldargv=sys.argv[:];oldcwd=os.getcwd();os.chdir(self.root);sys.path.insert(0,str(self.root/'macro-backtest'))
        try:
            import backtest as bt
            original_run=bt.run
            def run(name,prices,earnings,targets,mode,initial,monthly,cash_target,growth_names):
                cfg={'scenario_id':name,'test_type':'COMMON_WINDOW_ARCHITECTURE','targets':targets,'mode':mode,'initial':initial,'monthly':monthly,'cash_target':cash_target,'growth_names':growth_names,'requested_start':self.requested_start,'fee':bt.FEE,'drift':bt.DRIFT}
                config=self.config(cfg);data=self.snapshot('engine-inputs',{'prices':prices,'earnings':earnings})
                tks=list(targets);start=max(prices[t].first_valid_index() for t in tks);p=prices[tks].loc[start:].dropna()
                result=original_run(name,prices,earnings,targets,mode,initial,monthly,cash_target,growth_names)
                months=[str(x.date()) for x in p.index[1:]]
                coverage=price_coverage(self._provider_prices,tks,months,self._provider_retrieved_at,data['path'])
                self.manifest['calls'].append({'scenario_id':name,'config':config,'data':[data],'actual_start':str(p.index[0].date()),'requested_start':self.requested_start,'return_month_ends':months,'data_coverage':[coverage],'test_type':'COMMON_WINDOW_ARCHITECTURE'})
                return result
            bt.run=run
            ns=runpy.run_path(str(self.root/self.manifest['harness']),run_name='capture_target');g=ns['main'].__globals__;self.requested_start=ns.get('START_REQUEST')
            if self.manifest['harness'].endswith('defense_mix_test.py'):require(self.requested_start,'missing requested historical start')
            if self.manifest['harness'].endswith('historical_validation.py'):
                for key,kind in [('run_anchor_forward','ANCHOR_FORWARD_THESIS'),('run_event_dated','EVENT_DATED_SYSTEM')]:
                    original=g[key]
                    def wrap(prices,cfg,original=original,kind=kind):
                        config=self.config(cfg);data=self.snapshot('engine-prices',prices)
                        result=original(prices,cfg)
                        coverage=price_coverage(self._provider_prices,list(prices.columns),self._historical_dates,self._provider_retrieved_at,data['path'])
                        self.manifest['calls'].append({'scenario_id':'historical_single_run','config':config,'data':[data],'actual_start':result['actual_start'],'requested_start':cfg['anchor_date'],'test_type':kind,'return_month_ends':self._historical_dates,'data_coverage':[coverage]})
                        return result
                    g[key]=wrap
                original_stats=g['stats_from_values'];completed=g['_completed_monthly_values']
                def stats(values):
                    self.snapshot('engine-values',values);monthly=completed(values).pct_change().dropna();self._historical_dates=[str(x.date()) for x in monthly.index];return original_stats(values)
                g['stats_from_values']=stats
            sys.argv=[self.manifest['harness'],*self.manifest['argv']];ns['main']();self.finish(output)
        except Exception:
            self.manifest['status']='FAILED';self.manifest['finished_at']=utc();dump(self.bundle/'capture-manifest.json',self.manifest);raise
        finally:
            yf.download=original_download;yf.Ticker.get_earnings_history=original_earnings;sys.argv=oldargv;os.chdir(oldcwd)
            if 'bt' in locals():bt.run=original_run
            sys.path.pop(0)


def public_source_path(root,path):
    require(isinstance(path,str) and path,'historical source path required')
    parts=Path(path).parts
    require(not Path(path).is_absolute() and '..' not in parts,'historical source path must be relative without traversal')
    current=root
    for part in parts:
        current=current/part
        require(not current.is_symlink(),'historical source symlinks prohibited')
    return relative(current,root)

def capture_history(capture,transport_path):
    """Opt-in reviewed PUBLIC bytes already tracked at code commit; no discovery/upload."""
    root=capture.root;code=capture.manifest['execution']['code_commit']
    def original(path):
        rel=public_source_path(root,path)
        require(git(root,'ls-files','--',rel)==rel,'historical source must be tracked')
        data=(root/rel).read_bytes()
        committed=subprocess.check_output(['git','-C',str(root),'show',code+':'+rel])
        require(data==committed,'historical source differs from code commit')
        return rel,data
    rel,data=original(transport_path);t=json.loads(data)
    require(t.get('visibility')=='PUBLIC_REVIEWED','historical transport not explicitly public reviewed')
    require(isinstance(t.get('reviewer_assertion'),str) and t['reviewer_assertion'].strip(),'public source reviewer assertion required')
    require(isinstance(t.get('information_set'),str) and t['information_set'].strip(),'historical information set required')
    h=t['historical_evidence'];require(h['status']=='COMPLETE' and not h['missing_items'],'historical evidence incomplete')
    refs={(x['source_ref'],x['source_version'],x['bounded_sha256']) for x in h['items']}
    require(refs,'historical source references missing')
    sources=t['sources'];require(len(sources)==len({x['path'] for x in sources}),'duplicate historical source paths')
    require(len(sources)==len({(x['source_ref'],x['source_version'],x['sha256']) for x in sources}),'duplicate historical source identity')
    require(refs=={(x['source_ref'],x['source_version'],x['sha256']) for x in sources},'historical source reference coverage mismatch')
    transport=capture.save_bytes('historical-transport.json',data,'public-historical-transport',{'source_path':rel})
    saved=[]
    for i,item in enumerate(sources):
        source_path,b=original(item['path']);require(sha(b)==item['sha256'],'historical source digest mismatch')
        saved.append({**item,'source_path':source_path,'captured':capture.save_bytes(f'historical-source-{i:03d}.bin',b,'public-historical-source')})
    evidence=capture.save_bytes('historical-evidence.json',(json.dumps(h,sort_keys=True,allow_nan=False)+'\n').encode(),'historical-evidence')
    return {'transport':transport,'source_path':rel,'sources':saved,'evidence':evidence,'information_set':t['information_set']}

def verify_history(root,bundle,m,captured):
    h=m.get('historical_transport');require(h,'historical evidence transport missing; cannot accept supplied-only manifest')
    def retained(info):
        require(captured.get(info['path'])==info['sha256'],'historical evidence not persisted in capture')
        return (bundle/info['path']).read_bytes()
    code=m['execution']['code_commit']
    require(public_source_path(root,h['source_path'])==h['source_path'],'noncanonical historical transport path')
    transport=retained(h['transport']);require(transport==subprocess.check_output(['git','-C',str(root),'show',code+':'+h['source_path']]),'historical transport not from executed source commit')
    t=json.loads(transport);require(t.get('visibility')=='PUBLIC_REVIEWED','historical transport not public reviewed')
    require(isinstance(t.get('reviewer_assertion'),str) and t['reviewer_assertion'].strip(),'public source reviewer assertion required')
    require(t['information_set']==h['information_set'],'historical transport information set mismatch')
    evidence=json.loads(retained(h['evidence']));require(evidence==t['historical_evidence'],'historical transport evidence mismatch')
    require(len(t['sources'])==len(h['sources']),'historical source coverage mismatch')
    require(len(t['sources'])==len({x['path'] for x in t['sources']})==len({(x['source_ref'],x['source_version'],x['sha256']) for x in t['sources']}),'duplicate historical source mapping')
    refs={(x['source_ref'],x['source_version'],x['bounded_sha256']) for x in evidence['items']}
    require(refs=={(x['source_ref'],x['source_version'],x['sha256']) for x in t['sources']},'historical source references mismatch')
    for orig,item in zip(t['sources'],h['sources']):
        require(public_source_path(root,orig['path'])==orig['path'],'noncanonical historical source path')
        require(all(item[k]==v for k,v in orig.items()) and item['source_path']==orig['path'],'historical source mapping mismatch')
        b=retained(item['captured']);require(sha(b)==orig['sha256'],'historical source bytes mismatch')
        require(b==subprocess.check_output(['git','-C',str(root),'show',code+':'+item['source_path']]),'historical source differs from executed source commit')
    return h

def verify_bundle(bundle,run,record_paths,contract_dir,result_commit):
    """Post-success gate. Sidecars must be prepared from inspected evidence.
    No self-signed receipt substitutes for the independently fetched provider run.
    """
    bundle=Path(bundle).resolve();m=load(bundle/'capture-manifest.json');require(m['status']=='CAPTURED','capture incomplete')
    root=evidence_root(bundle,m);prefix=m['bundle_path']
    def pref(info):return {'path':prefix+'/'+info['path'],'sha256':info['sha256']}
    source=provider_receipt(run,m)
    require(git(root,'rev-parse',result_commit+'^{commit}')==result_commit,'invalid persisted commit')
    persisted_manifest=subprocess.check_output(['git','-C',str(root),'show',result_commit+':'+prefix+'/capture-manifest.json'])
    require(persisted_manifest==(bundle/'capture-manifest.json').read_bytes(),'capture manifest differs from persisted commit')
    subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',m['execution']['code_commit'],result_commit],check=True)
    captured={x['path']:x['sha256'] for x in m['files']+m['outputs']}
    for path,digest in captured.items():
        p=(bundle/path).resolve();require(p.is_relative_to(bundle),'capture path escape');require(sha(p.read_bytes())==digest,'captured bytes changed: '+path)
        persisted=subprocess.check_output(['git','-C',str(root),'show',result_commit+':'+prefix+'/'+path]);require(sha(persisted)==digest,'captured input/output not in persisted commit: '+path)
    require(record_paths,'missing acceptance sidecars; no default COMPLETE result')
    contract_dir=Path(contract_dir).resolve();spec=importlib.util.spec_from_file_location('macro_contract',contract_dir/'validate-backtest-result.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    outputs=[];covered=[]
    for path in record_paths:
        r=load(path);ident=r['identity'];require(all(ident.get(k)==v for k,v in m['execution'].items()),'sidecar runtime identity mismatch')
        calls=[c for c in m['calls'] if c['scenario_id']==r['scenario_id'] and c['test_type']==ident['test_type']];require(len(calls)==1,'scenario capture missing or ambiguous');call=calls[0]
        if ident['test_type']!='COMMON_WINDOW_ARCHITECTURE':
            h=verify_history(root,bundle,m,captured)
            require(r['inputs']['historical_manifest']==pref(h['evidence']),'historical manifest differs from captured evidence')
            require(ident['information_set']==h['information_set'],'historical information set differs from captured evidence')
        require(r['inputs']['config']==pref(call['config']) and r['inputs']['data']==[pref(x) for x in call['data']],'sidecar not bound to actual engine inputs')
        require(r['requested_start']==call['requested_start'] and r['actual_start']==call['actual_start'] and r['return_month_ends']==call['return_month_ends'],'sidecar temporal labels differ from engine observations')
        expected_coverage=[{**x,'path':prefix+'/'+x['path']} for x in call['data_coverage']]
        require(r['data_coverage']==expected_coverage,'sidecar data coverage differs from captured observations')
        require(r['artifact']['kind']=='git_file' and r['artifact']['result_commit']==result_commit,'wrong persisted output commit')
        rawpath=r['artifact']['path'];require(rawpath.startswith(prefix+'/'),'raw output outside captured bundle');localpath=rawpath[len(prefix)+1:]
        require(localpath in captured and r['artifact']['sha256']==captured[localpath],'raw output not captured')
        require(git(root,'rev-parse',result_commit+'^{commit}')==result_commit,'invalid persisted commit')
        persisted=subprocess.check_output(['git','-C',str(root),'show',result_commit+':'+rawpath]);require(sha(persisted)==r['artifact']['sha256'],'persisted Git output differs')
        receipt={'identity':ident,'inputs':r['inputs'],'status':run['status'],'conclusion':run['conclusion'],'artifact':r['artifact'],'receipt_source':source,'verified_at':utc()}
        result=module.validate(r,receipt,root);outputs.append({'scenario_id':r['scenario_id'],'result':result,'receipt':receipt});covered.append(r['scenario_id'])
    require(sorted(covered)==sorted(c['scenario_id'] for c in m['calls']),'some captured scenarios are not accepted')
    return {'status':'ACCEPTED','provider_workflow_checked':True,'capture_manifest_sha256':sha((bundle/'capture-manifest.json').read_bytes()),'results':outputs,'trade_authority':False}

def evidence_root(bundle,manifest):
    parts=Path(manifest['bundle_path']).parts
    require(parts and '..' not in parts and not Path(manifest['bundle_path']).is_absolute(),'invalid bundle path')
    root=Path(bundle).resolve()
    for _ in parts:root=root.parent
    require((root/manifest['bundle_path']).resolve()==Path(bundle).resolve(),'bundle location mismatch')
    return root

def price_coverage(raw,tickers,months,retrieved_at,path,calendar=None):
    """Actual daily observations checked against declared US exchange sessions."""
    import pandas as pd
    if calendar is None:
        import exchange_calendars as xc
        calendar=xc.get_calendar('XNYS',start=months[0][:7]+'-01',end=months[-1])
    rows=[]
    for month in months:
        date=pd.Timestamp(month);start=date.replace(day=1)
        sessions=calendar.sessions_in_range(start,date);require(len(sessions),'calendar month has no sessions');expected=str(sessions[-1].date())
        observed=[]
        for ticker in tickers:
            if (ticker,'Close') in raw.columns:series=raw[(ticker,'Close')]
            elif ('Close',ticker) in raw.columns:series=raw[('Close',ticker)]
            elif len(tickers)==1 and 'Close' in raw.columns:series=raw['Close']
            else:raise ValueError('missing raw close series '+ticker)
            series=series.dropna().copy();series.index=pd.to_datetime(series.index).tz_localize(None);series=series[(series.index>=start)&(series.index<=date)]
            require(len(series),'empty raw month for '+ticker);observed.append(str(series.index[-1].date()))
        require(all(x==expected for x in observed),'stale/incomplete raw month '+month)
        rows.append({'month_end':month,'last_observation':expected,'expected_last_session':expected,'calendar_source':'exchange_calendars:XNYS; US-equity-session assumption; '+str(getattr(calendar,'name','XNYS'))})
    return {'path':path,'retrieved_at':retrieved_at,'months':rows}

def prepare_common(bundle,result_commit,output_dir):
    return prepare_records(bundle,result_commit,output_dir,False)

def prepare_historical(bundle,result_commit,output_dir):
    return prepare_records(bundle,result_commit,output_dir,True)

def prepare_records(bundle,result_commit,output_dir,historical=False):
    """Generate sidecars only from captured public retrospective configuration.
    Historical approval/evidence is deliberately not inferred by this operation.
    """
    bundle=Path(bundle).resolve();m=load(bundle/'capture-manifest.json');require(m['status']=='CAPTURED','capture incomplete');root=evidence_root(bundle,m);prefix=m['bundle_path']
    require(m['calls'] and all((c['test_type']!='COMMON_WINDOW_ARCHITECTURE')==historical for c in m['calls']),'historical manifests must be supplied from genuine reviewed evidence')
    out=Path(output_dir).resolve();require(out.is_relative_to(root),'sidecars outside checkout');out.mkdir(parents=True,exist_ok=True)
    history={'status':'NOT_APPLICABLE','scope':'Retrospective captured public engine configuration; not historical thesis/event evidence.','missing_items':[],'items':[]}
    dump(out/'historical-manifest.json',history);h={'path':relative(out/'historical-manifest.json',root),'sha256':sha((out/'historical-manifest.json').read_bytes())}
    info='Retrospective public engine configuration captured for this exact run; current-canon alignment is not independently verified.'
    if historical:
        transport=verify_history(root,bundle,m,{x['path']:x['sha256'] for x in m['files']+m['outputs']})
        h={**transport['evidence'],'path':prefix+'/'+transport['evidence']['path']}
        history=load(bundle/transport['evidence']['path']);info=transport['information_set']
        dump(out/'historical-manifest.json',history)
    records=[]
    for i,call in enumerate(m['calls']):
        matches=[]
        for raw in m['outputs']:
            if not raw['path'].endswith('.json'):continue
            payload=json.loads((bundle/raw['path']).read_text())
            if not isinstance(payload,dict):continue
            candidates=payload.get('summary',[])+payload.get('results',[])+payload.get('smart_refill_backtest',{}).get('results',[])
            if historical and 'metrics' in payload:candidates=[{**payload['metrics'],'strategy':'historical_single_run'}]
            for metric in candidates:
                if metric.get('strategy')==call['scenario_id']:matches.append((raw,metric))
        require(len(matches)==1,'raw scenario missing/ambiguous '+call['scenario_id']);raw,metric=matches[0]
        names=['ann_return','ann_vol','sharpe','sortino','max_drawdown','worst_month','ending_value','months'];metrics={k:metric[k] for k in names};metrics['undefined_reasons']={}
        for name in ['sharpe','sortino']:
            if metrics[name] is None or isinstance(metrics[name],float) and math.isnan(metrics[name]):
                metrics[name]=None;metrics['undefined_reasons'][name]='Engine reported undefined ratio; denominator unavailable or zero under its documented sample-deviation convention.'
        artpath=prefix+'/'+raw['path'];identity={**m['execution'],'test_type':call['test_type'],'information_set':info}
        def pref(x):return {'path':prefix+'/'+x['path'],'sha256':x['sha256']}
        coverage=[{**x,'path':prefix+'/'+x['path']} for x in call['data_coverage']]
        record={'schema_version':'1.3','scenario_id':call['scenario_id'],'status':'COMPLETE','limitations':['Retrospective selection/survivorship exposure; not a current-canon portfolio claim.','Core return statistics exclude contemporaneous trading fees; ending value includes fees.','No trade authority; provider completion independently checked in downstream gate.'],'identity':identity,'requested_start':call['requested_start'],'actual_start':call['actual_start'],'actual_end':call['return_month_ends'][-1],'checked_as_of':dt.datetime.now(dt.timezone.utc).date().isoformat(),'anchor_date':None,'start_reason':'Captured first common valid observation across actual scenario tickers','bias_classification':'RETROSPECTIVE SELECTION / SURVIVORSHIP EXPOSURE','return_month_ends':call['return_month_ends'],'metrics':metrics,'metric_convention':'core_pre_contribution_v1','inputs':{'config':pref(call['config']),'data':[pref(x) for x in call['data']],'historical_manifest':h},'historical_evidence':history,'artifact':{'kind':'git_file','id':f'{REPOSITORY}@{result_commit}:{artpath}','result_commit':result_commit,'path':artpath,'sha256':raw['sha256']},'data_coverage':coverage,'trade_authority':False}
        if historical:
            record.update(anchor_date=call['requested_start'],metric_convention='historical_value_pct_change_v1',bias_classification='HISTORICAL EVIDENCE: tracked reviewed public source provenance, not independent source truth',start_reason='Captured first valid historical engine observation',limitations=['Public reviewed source bytes bound to executed code and output commit; historical factual truth is not independently authenticated.','Historical value growth includes contributions and is not contribution-adjusted investment performance.','No trade authority; source completeness remains a reviewed claim.'])
        path=out/f'result-{i:03d}.json';dump(path,record);records.append(str(path))
    return records

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('capture');c.add_argument('--root',default='.');c.add_argument('--bundle',required=True);c.add_argument('--harness',choices=list(HARNESS),required=True);c.add_argument('--output',required=True);c.add_argument('--historical-evidence');c.add_argument('harness_args',nargs=argparse.REMAINDER)
    a=sub.add_parser('prepare-common');a.add_argument('--bundle',required=True);a.add_argument('--result-commit',required=True);a.add_argument('--contract-dir');a.add_argument('--output-dir',required=True)
    a=sub.add_parser('prepare-historical');a.add_argument('--bundle',required=True);a.add_argument('--result-commit',required=True);a.add_argument('--output-dir',required=True)
    v=sub.add_parser('verify');v.add_argument('--bundle',required=True);v.add_argument('--provider-run',required=True);v.add_argument('--contract-dir',required=True);v.add_argument('--result-commit',required=True);v.add_argument('--records',nargs='+',required=True);v.add_argument('--output',required=True)
    a=p.parse_args()
    if a.cmd=='capture':Capture(a.root,a.bundle,a.harness,a.harness_args[1:] if a.harness_args[:1]==['--'] else a.harness_args,historical_evidence=a.historical_evidence).run(a.output)
    elif a.cmd=='prepare-common':print(json.dumps(prepare_common(a.bundle,a.result_commit,a.output_dir)))
    elif a.cmd=='prepare-historical':print(json.dumps(prepare_records(a.bundle,a.result_commit,a.output_dir,True)))
    else:dump(a.output,verify_bundle(a.bundle,load(a.provider_run),a.records,a.contract_dir,a.result_commit))
if __name__=='__main__':main()
