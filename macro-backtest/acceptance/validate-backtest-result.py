"""Offline acceptance contract. No network, dispatch, trades, or engine mutation.
A passing supplied receipt is not independent authentication of GitHub.
"""
import calendar, datetime as dt, hashlib, json, math, statistics
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
HERE=Path(__file__).resolve().parent

def read_json(path):
    def bad(x): raise ValueError('non-standard JSON number: '+x)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),parse_constant=bad)

def check_schema(value,name):
    schema=read_json(HERE/name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(value)

def validate_performance(performance):
    """Independent arithmetic consistency, not valuation/source authentication."""
    def need(ok,message):
        if not ok:raise ValueError('performance arithmetic: '+message)
    returns=[x['return'] for x in performance['monthly_returns']]
    need(returns and all(x>-1 for x in returns),'nonpositive unit NAV')
    initial=performance['initial_fee_return'];need(-1<initial<=0,'invalid inception fee return')
    values=[];nav=1.
    for x in returns:nav*=1+x;values.append(nav)
    need(math.isfinite(nav) and nav>0,'nonfinite terminal unit NAV')
    elapsed=performance['elapsed_days'];annual=nav**(365.25/elapsed)-1
    sd=statistics.stdev(returns) if len(returns)>1 else None
    negatives=[x for x in returns if x<0];down=statistics.stdev(negatives) if len(negatives)>1 else None
    mean=statistics.mean(returns)
    ratio=lambda den:mean/den*math.sqrt(12) if den is not None and den>0 else None
    peak=1.;drawdown=0.
    for x in [1+initial]+values:peak=max(peak,x);drawdown=min(drawdown,x/peak-1)
    expected={'ann_return':annual,'ann_vol':None if sd is None else sd*math.sqrt(12),'sharpe':ratio(sd),'sortino':ratio(down),'max_drawdown':drawdown,'worst_month':min(returns),'months':len(returns)}
    def close(a,b):return a is None and b is None or a is not None and b is not None and not isinstance(a,bool) and math.isfinite(a) and math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-10)
    need(close(performance['total_return'],nav-1),'total return inconsistent with monthly series')
    for name,value in expected.items():need(close(performance['metrics'][name],value),name+' inconsistent with monthly series')
    nulls={k for k,v in expected.items() if v is None};need(set(performance['metrics']['undefined_reasons'])==nulls,'undefined reason coverage mismatch')
    # ending_value includes capital flows and cannot be derived from return series alone.

def validate(record, receipt, root, now=None):
    check_schema(record,'backtest-run.schema.json'); check_schema(receipt,'workflow-receipt.schema.json')
    def need(condition,message):
        if not condition: raise ValueError(message)
    def finite(v):
        if isinstance(v,float):need(math.isfinite(v),'nonfinite number')
        elif isinstance(v,dict):
            for x in v.values():finite(x)
        elif isinstance(v,list):
            for x in v:finite(x)
    finite(record); finite(receipt)
    need(record['status']=='COMPLETE','incomplete/invalid result is not accepted')
    need(record['identity']==receipt['identity'],'cross-run/code/test/information-set mismatch')
    need(record['artifact']==receipt['artifact'],'artifact receipt mismatch')
    need(record['inputs']==receipt['inputs'],'cross-run input fingerprint mismatch')
    ident=record['identity']; kind=ident['test_type']; art=record['artifact']
    expected='.github/workflows/macro-defense-mix-test.yml' if kind=='COMMON_WINDOW_ARCHITECTURE' else '.github/workflows/macro-historical-validation.yml'
    need(ident['workflow_path']==expected,'workflow not mapped to primary test type')
    need(record['metric_convention']=='unitized_fee_inclusive_twr_v1','metric convention mismatch')
    need(record['metrics']==record['performance']['metrics'],'sidecar metrics must be corrected performance metrics')
    need((art['result_commit'] is not None)==(art['kind']=='git_file'),'git artifact requires result commit; Actions artifact must use null')
    if art['kind']=='git_file':need(art['id']==f"{ident['repository']}@{art['result_commit']}:{art['path']}",'git artifact identity mismatch')
    root=Path(root).resolve()
    def bytes_for(info):
        p=(root/info['path']).resolve(); need(p.is_relative_to(root),'path escapes evidence directory')
        b=p.read_bytes();need(hashlib.sha256(b).hexdigest()==info['sha256'],'digest mismatch: '+info['path']);return b
    raw=bytes_for(art)
    config=json.loads(bytes_for(record['inputs']['config']))
    for f in record['inputs']['data']:bytes_for(f)
    for k in ['test_type','information_set']:
        if k in config:need(config[k]==ident[k],'config identity mismatch: '+k)
    if 'anchor_date' in config:need(config['anchor_date']==record['anchor_date'],'config anchor mismatch')
    manifest=json.loads(bytes_for(record['inputs']['historical_manifest']))
    need(manifest==record['historical_evidence'],'historical sidecar mismatch')
    # Exact raw output must be read and its selected scenario's metrics bound, not merely hashed.
    def legacy_constant(x):
        if x!='NaN': raise ValueError('infinite raw metric')
        return float('nan')
    raw_result=json.loads(raw,parse_constant=legacy_constant)
    candidates=[]
    if isinstance(raw_result,dict):
        if 'performance' in raw_result and record['scenario_id']=='historical_single_run':candidates=[{'strategy':'historical_single_run','performance':raw_result['performance']}]
        candidates+=raw_result.get('summary',[])+raw_result.get('results',[])
        candidates+=raw_result.get('smart_refill_backtest',{}).get('results',[])
    names=['ann_return','ann_vol','sharpe','sortino','max_drawdown','worst_month','ending_value','months']
    def metric_match(c):
        if c.get('strategy','historical_single_run')!=record['scenario_id']:return False
        if c.get('performance')!=record['performance']:return False
        c=c.get('performance',{}).get('metrics',{})
        if not all(k in c for k in names):return False
        for k in names:
            value=c[k]
            if isinstance(value,bool) or not (isinstance(value,(int,float)) or value is None):return False
            if value is None and k not in ['ann_vol','sharpe','sortino']:return False
            if isinstance(value,float) and math.isnan(value):
                if k not in ['ann_vol','sharpe','sortino']:return False
                value=None  # only legacy undefined ratios are normalized; raw bytes retained
            if value!=record['metrics'][k]:return False
        return True
    need(any(metric_match(c) for c in candidates),'metrics not found verbatim in bound raw output')
    if 'test_type' in raw_result:need(raw_result['test_type']==kind,'raw test type mismatch')
    for k in ['anchor_date','actual_start','actual_end','requested_start']:
        if k in raw_result:need(raw_result[k]==record[k],'raw label mismatch: '+k)
    if 'information_set' in raw_result:need(raw_result['information_set']==ident['information_set'],'raw information-set mismatch')
    asof=dt.date.fromisoformat(record['checked_as_of']);today=now or dt.datetime.now(dt.timezone.utc).date()
    need(dt.datetime.fromisoformat(receipt['verified_at'].replace('Z','+00:00')).date()<=asof,'future workflow receipt');
    need(asof<=today,'future check date'); start=dt.date.fromisoformat(record['actual_start']);end=dt.date.fromisoformat(record['actual_end'])
    need(dt.date.fromisoformat(record['requested_start'])<=start<end<asof.replace(day=1),'start/end or incomplete current-month violation')
    dates=[dt.date.fromisoformat(x) for x in record['return_month_ends']]
    need(dates==sorted(dates) and dates[-1]==end and len(dates)==record['metrics']['months'],'return count/order/end mismatch')
    need(all(d.day==calendar.monthrange(d.year,d.month)[1] and start<d<asof.replace(day=1) for d in dates),'invalid or partial monthly label')
    need(sorted(x['path'] for x in record['data_coverage'])==sorted(x['path'] for x in record['inputs']['data']),'dataset coverage mismatch')
    for coverage in record['data_coverage']:
        need(dt.datetime.fromisoformat(coverage['retrieved_at'].replace('Z','+00:00')).date()<=asof,'future data retrieval')
        need([x['month_end'] for x in coverage['months']]==record['return_month_ends'],'data month coverage mismatch')
        for month in coverage['months']:
            label=dt.date.fromisoformat(month['month_end']);last=dt.date.fromisoformat(month['last_observation'])
            need(last<=dt.datetime.fromisoformat(coverage['retrieved_at'].replace('Z','+00:00')).date(),'data retrieval precedes observation')
            need(month['last_observation']==month['expected_last_session'] and label.replace(day=1)<=last<=label,'stale/incomplete data month')
    need((record['metrics']['ann_vol'] is None or record['metrics']['ann_vol']>=0) and record['metrics']['ending_value']>=0,'negative volatility/value')
    need(-1<=record['metrics']['max_drawdown']<=0,'invalid drawdown')
    for k in ['ann_vol','sharpe','sortino']:
        need((record['metrics'][k] is None)==(k in record['metrics']['undefined_reasons']),'undefined metric reason mismatch')
    perf=record['performance']
    validate_performance(perf)
    need(perf['metric_convention']==record['metric_convention'],'performance convention mismatch')
    need([x['month_end'] for x in perf['monthly_returns']]==record['return_month_ends'],'performance monthly labels mismatch')
    inception=dt.date.fromisoformat(perf['inception_date']);final=dt.date.fromisoformat(perf['final_observation_date'])
    need(inception<=start and inception<final<=end,'performance window mismatch')
    need(perf['elapsed_days']==(final-inception).days,'performance elapsed-day mismatch')
    need(perf['first_period_partial']==(inception.day!=calendar.monthrange(inception.year,inception.month)[1]),'partial first-period disclosure mismatch')
    need(perf['cashflow_timing']=='External contributions issue units at contemporaneous pre-flow NAV; trades and fees then change NAV; same-date event order preserved.','unsupported cashflow timing')
    need(perf['annualization_basis']=='Cumulative unit NAV annualized over actual inception-to-final-observation calendar days using 365.25; volatility and internal ratios use sqrt(12) monthly sampling.','unsupported annualization basis')
    profile=record['bias_profile'];need(profile['primary_test_type']==kind,'bias primary type mismatch')
    if kind=='COMMON_WINDOW_ARCHITECTURE':
        need(record['anchor_controls'] is None,'common-window cannot claim anchor-control proof')
        need(profile['completeness']=='NOT_APPLICABLE' and profile['variant']=='RETROSPECTIVE' and profile['claim']=='RETROSPECTIVE_ARCHITECTURE_ONLY' and profile['risks']==['SELECTION_SURVIVORSHIP'] and not profile['omitted_scope'] and record['bias_classification']=='RETROSPECTIVE_SELECTION_SURVIVORSHIP','unjustified retrospective bias classification')
    else:
        need('DECLARED_EVIDENCE_NOT_INDEPENDENTLY_AUTHENTICATED' in profile['risks'],'historical evidence limitation missing')
        if profile['completeness']=='SUPPORTED_SUBSET':
            need(profile['variant']=='SUPPORTED_SUBSET' and profile['claim']=='SUPPORTED_SUBSET_ONLY' and record['bias_classification']=='SUPPORTED_SUBSET_ONLY' and profile['omitted_scope'] and 'OMITTED_HISTORY' in profile['risks'] and record['limitations'],'subset claim must remain bounded')
        else:
            need(profile['completeness']=='COMPLETE' and profile['variant']=='FULL_SCOPE' and profile['claim']=='HISTORICAL_SCOPE_ONLY' and record['bias_classification']=='HISTORICAL_SCOPE_LIMITED' and not profile['omitted_scope'] and 'OMITTED_HISTORY' not in profile['risks'],'unsupported full-scope historical claim')
        need(record['historical_evidence']['status']=='COMPLETE','incomplete history cannot be accepted')
        proof=record['anchor_controls'];need(proof is not None,'anchor control provenance required')
        required={'targets','cash_target','initial_capital','monthly_contribution','fee','refill_method','max_anchor_slippage_days'} if kind=='ANCHOR_FORWARD_THESIS' else {'initial_targets','cash_target','initial_capital','fee','exclude_exogenous'}
        need(set(proof['controls'])==required,'implemented control provenance coverage mismatch')
        anchors=[x for x in record['historical_evidence']['items'] if x['classification']=='ANCHOR']
        for key,control in proof['controls'].items():
            need(key in config and control['value']==config[key] and not (isinstance(control['value'],bool) != isinstance(config[key],bool)),'missing/unsupported control default: '+key)
            need(any(all(control[k]==a[k] for k in ['source_ref','source_version','bounded_sha256','known_at']) for a in anchors),'control not tied to anchor source: '+key)
            need(control['known_at']<=record['anchor_date'],'post-anchor control provenance')
    h=record['historical_evidence']; need(not h['missing_items'],'missing historical evidence')
    if kind!='COMMON_WINDOW_ARCHITECTURE':
        anchor=dt.date.fromisoformat(record['anchor_date'])
        need(record['requested_start']==record['anchor_date'] and anchor<=start,'anchor start mismatch')
        need(any(x['classification']=='ANCHOR' for x in h['items']),'missing anchor evidence')
        for item in h['items']:
            known=dt.date.fromisoformat(item['known_at']);effective=dt.date.fromisoformat(item['effective_date'])
            need(known<=effective<=end,'future historical evidence')
            if item['classification']=='ANCHOR':
                need(item['event_sha256'] is None,'anchor is not an event')
                need(effective==anchor and known<=anchor,'anchor information leakage')
            else:
                need(kind=='EVENT_DATED_SYSTEM' and effective>=anchor,'event outside historical scope')
                need(item['event_sha256'] is not None,'missing event identity')
                if item['classification']=='EVENT':need(item['applied_date'] is not None,'event not applied')
            if item['applied_date'] is not None:need(effective<=dt.date.fromisoformat(item['applied_date'])<=end,'backdated/out-of-window event')
        if kind=='EVENT_DATED_SYSTEM':
            expected=[x for x in h['items'] if x['classification']!='ANCHOR']
            applied=raw_result.get('events_applied',[])
            need(len(applied)==len(expected),'event ledger outcome coverage mismatch')
            def fingerprint(event):
                return hashlib.sha256(json.dumps({k:v for k,v in event.items() if k not in ['status','execution_date']},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            need(sorted(fingerprint(e) for e in config.get('events',[]))==sorted(x['event_sha256'] for x in expected),'config event coverage mismatch')
            outcomes={fingerprint(e):e for e in applied}
            need(len(outcomes)==len(applied),'ambiguous duplicate event identity')
            for item in expected:
                need(item['event_sha256'] in outcomes,'event missing from raw output')
                e=outcomes[item['event_sha256']]
                need(e['date']==item['effective_date'],'event effective date mismatch')
                if item['applied_date'] is None:
                    need(item['classification']=='EXOGENOUS' and config.get('exclude_exogenous') is True and str(e.get('classification','')).upper()=='EXOGENOUS' and e.get('status')=='EXCLUDED_EXOGENOUS','unproved event exclusion')
                else:
                    need(e.get('status')=='APPLIED','event not applied in raw output')
                    need(e.get('execution_date')==item['applied_date'],'event execution date mismatch')
    return {'contract':'PASS','scope':'offline supplied-record consistency and byte integrity only','independent_workflow_verification':False,'trade_authority':False}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('result');p.add_argument('receipt');p.add_argument('--evidence-root',required=True);a=p.parse_args()
    print(json.dumps(validate(read_json(a.result),read_json(a.receipt),a.evidence_root),indent=2))
