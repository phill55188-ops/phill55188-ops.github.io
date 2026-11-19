"""Verify downloaded evidence against the exact persisted Git tree; never unpickle."""
import argparse, hashlib, json, pathlib, re, subprocess
REPO='phill55188-ops/phill55188-ops.github.io'
WORKFLOWS={369746177:('MACRO Defense Mix Test','.github/workflows/macro-defense-mix-test.yml','defense'),374956997:('MACRO Historical Validation','.github/workflows/macro-historical-validation.yml','historical')}
def require(ok,msg):
    if not ok:raise ValueError(msg)
def read(path):return json.loads(pathlib.Path(path).read_text())
def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args])
def verify(checkout,capture,run,artifact):
    root=pathlib.Path(capture).resolve();repo=pathlib.Path(checkout).resolve();seal=read(root/'seal.json')
    require(run.get('repository',{}).get('full_name')==REPO,'wrong repository')
    require(run.get('head_repository',{}).get('full_name')==REPO,'untrusted head repository')
    require(run.get('head_branch')=='macro-backtest-v08','wrong branch')
    require(run.get('event') in ['push','workflow_dispatch'],'unexpected generation event')
    require(run.get('status')=='completed' and run.get('conclusion')=='success','generation unsuccessful')
    require(run.get('workflow_id') in WORKFLOWS,'unknown workflow')
    name,path,kind=WORKFLOWS[run['workflow_id']]
    require(run.get('name')==name and run.get('path')==path,'workflow identity mismatch')
    require(re.fullmatch('[a-f0-9]{40}',run.get('head_sha','')),'invalid executed commit')
    require(git(repo,'rev-parse','HEAD').decode().strip()==run['head_sha'],'wrong code checkout')
    expected=f"macro-backtest/results-provenance/{run['id']}-{run['run_attempt']}/{kind}"
    require(seal.get('kind')==kind and seal.get('bundle_path')==expected,'wrong sealed run path')
    result=seal.get('result_commit','');require(re.fullmatch('[a-f0-9]{40}',result),'invalid result commit')
    require(artifact.get('name')==f"macro-capture-{run['id']}-{run['run_attempt']}" and isinstance(artifact.get('id'),int) and not artifact.get('expired',True),'wrong/expired artifact')
    require(artifact.get('workflow_run',{}).get('id')==run['id'] and artifact.get('workflow_run',{}).get('head_sha')==run['head_sha'],'artifact belongs to different run')
    subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',run['head_sha'],result],check=True,capture_output=True)
    paths=git(repo,'ls-tree','-r','--name-only',result,'--',expected).decode().splitlines()
    require(paths,'persisted capture tree missing')
    bundle=root/'bundle';local={p.relative_to(bundle).as_posix():p for p in bundle.rglob('*') if p.is_file()}
    expected_files={p[len(expected)+1:]:p for p in paths}
    require(set(local)==set(expected_files),'downloaded/persisted file set mismatch')
    for relative,p in local.items():
        require(not p.is_symlink() and p.resolve().is_relative_to(bundle.resolve()),'unsafe capture path')
        persisted=git(repo,'show',f'{result}:{expected_files[relative]}')
        require(p.read_bytes()==persisted,'downloaded evidence does not match persisted bytes: '+relative)
    manifest=read(bundle/'capture-manifest.json')
    require(manifest.get('status')=='CAPTURED','capture did not complete')
    return {'result_commit':result,'bundle_path':expected,'kind':kind,'files_verified':len(paths),'provider_run_id':run['id'],'provider_run_attempt':run['run_attempt'],'artifact_id':artifact['id'],'capture_manifest_sha256':hashlib.sha256((bundle/'capture-manifest.json').read_bytes()).hexdigest()}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--checkout',required=True);p.add_argument('--capture',required=True);p.add_argument('--provider-run',required=True);p.add_argument('--artifact',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    try:
        result=verify(a.checkout,a.capture,read(a.provider_run),read(a.artifact))
    except Exception as exc:
        pathlib.Path(a.output).write_text(json.dumps({'status':'REJECTED','reason':str(exc),'trade_authority':False},indent=2)+'\n')
        raise SystemExit(1)
    pathlib.Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print('Persisted capture identity and bytes verified')
