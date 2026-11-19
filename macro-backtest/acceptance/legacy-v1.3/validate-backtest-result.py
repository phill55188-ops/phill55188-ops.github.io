"""Offline acceptance contract. No network, dispatch, trades, or engine mutation.
A passing supplied receipt is not independent authentication of GitHub.
"""
import calendar, datetime as dt, hashlib, json, math
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
    need(record['metric_convention']==('core_pre_contribution_v1' if kind=='COMMON_WINDOW_ARCHITECTURE' else 'historical_value_pct_change_v1'),'metric convention mismatch')
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
        if 'metrics' in raw_result and record['scenario_id']=='historical_single_run':candidates=[raw_result['metrics']]
        candidates+=raw_result.get('summary',[])+raw_result.get('results',[])
        candidates+=raw_result.get('smart_refill_backtest',{}).get('results',[])
    names=['ann_return','ann_vol','sharpe','sortino','max_drawdown','worst_month','ending_value','months']
    def metric_match(c):
        if c.get('strategy','historical_single_run')!=record['scenario_id'] or not all(k in c for k in names):return False
        for k in names:
            value=c[k]
            if isinstance(value,bool) or not (isinstance(value,(int,float)) or value is None):return False
            if value is None and k not in ['sharpe','sortino']:return False
            if isinstance(value,float) and math.isnan(value):
                if k not in ['sharpe','sortino']:return False
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
    need(record['metrics']['ann_vol']>=0 and record['metrics']['ending_value']>=0,'negative volatility/value')
    need(-1<=record['metrics']['max_drawdown']<=0,'invalid drawdown')
    for k in ['sharpe','sortino']:
        need((record['metrics'][k] is None)==(k in record['metrics']['undefined_reasons']),'undefined metric reason mismatch')
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
                    if e.get('type')!='CONTRIBUTION':need(e.get('execution_date')==item['applied_date'],'event execution date mismatch')
    return {'contract':'PASS','scope':'offline supplied-record consistency and byte integrity only','independent_workflow_verification':False,'trade_authority':False}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('result');p.add_argument('receipt');p.add_argument('--evidence-root',required=True);a=p.parse_args()
    print(json.dumps(validate(read_json(a.result),read_json(a.receipt),a.evidence_root),indent=2))
