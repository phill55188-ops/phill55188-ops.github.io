"""Join the real completed receipt to immutable capture; never runs the engine."""
import argparse, importlib.util, json, pathlib, shutil, subprocess, sys
HERE=pathlib.Path(__file__).resolve().parent

def evaluate(checkout,capture,provider_run,verified_capture,output):
    output=pathlib.Path(output).resolve()
    try:
        spec=importlib.util.spec_from_file_location('acceptance_runtime',HERE/'acceptance_runtime.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        proof=json.loads(pathlib.Path(verified_capture).read_text())
        run=json.loads(pathlib.Path(provider_run).read_text())
        # Re-run verification; the supplied prior result is not authority by association.
        spec2=importlib.util.spec_from_file_location('persisted_check',HERE/'verify_persisted_capture.py')
        check=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(check)
        artifact=json.loads((pathlib.Path(provider_run).resolve().parent/'artifact.json').read_text())
        actual=check.verify(checkout,capture,run,artifact)
        if actual!=proof:raise ValueError('Persisted verification receipt changed')
        work=output.parent/'acceptance-evidence'
        if work.exists():raise ValueError('Evidence checkout already exists; do not overwrite')
        subprocess.run(['git','-C',str(pathlib.Path(checkout).resolve()),'worktree','add','--detach',str(work),proof['result_commit']],check=True,capture_output=True)
        bundle=work/proof['bundle_path'];record_dir=work/'acceptance-records'
        if proof['kind']=='defense':
            paths=module.prepare_common(bundle,proof['result_commit'],record_dir)
        else:
            # Historical evidence cannot be fabricated from today's canon or the run itself.
            paths=sorted(str(x) for x in (bundle/'acceptance-records').glob('result-*.json'))
            if not paths:raise ValueError('INCOMPLETE: genuine reviewed historical acceptance records are absent')
        result=module.verify_bundle(bundle,run,paths,HERE,proof['result_commit'])
        result['persisted_capture']=proof
        result['scope']='primary captured harness only; supplemental benchmark/stress outputs are not certified'
        output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        exported=output.parent/'acceptance-records';exported.mkdir(exist_ok=False)
        for p in paths:shutil.copy2(p,exported/pathlib.Path(p).name)
        if (record_dir/'historical-manifest.json').exists():shutil.copy2(record_dir/'historical-manifest.json',exported/'historical-manifest.json')
        print('Primary result acceptance gate passed with actual completed provider receipt')
        return 0
    except Exception as exc:
        output.write_text(json.dumps({'status':'INCOMPLETE_OR_REJECTED','reason':str(exc),'trade_authority':False,'live_backtest_executed_by_observer':False},indent=2)+'\n')
        print('Acceptance gate rejected: '+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--checkout',required=True);p.add_argument('--capture',required=True);p.add_argument('--provider-run',required=True);p.add_argument('--verified-capture',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    raise SystemExit(evaluate(a.checkout,a.capture,a.provider_run,a.verified_capture,a.output))
