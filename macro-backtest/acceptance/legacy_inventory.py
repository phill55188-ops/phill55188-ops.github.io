"""Read-only inventory of tracked legacy outputs. Never runs/revalidates a backtest."""
import hashlib,json,subprocess,sys
from pathlib import Path

def inventory(root):
    root=Path(root)
    paths=subprocess.check_output(['git','-C',str(root),'ls-files','macro-backtest'],text=True).splitlines()
    items=[]
    for name in paths:
        p=Path(name)
        if any(part.startswith('results') for part in p.parts) and p.suffix in {'.json','.csv','.html'}:
            items.append({'path':name,'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'status':'LEGACY_NOT_REVALIDATED','current_acceptance':False})
    return {'inventory_version':'1.4','source_commit':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),'policy':'Inventory only, not a determination that old results are false. No recalculation, deletion, migration or execution. Current acceptance requires explicit current-contract revalidation with original evidence or separately authorized rerun.','artifacts':items}
if __name__=='__main__':print(json.dumps(inventory(sys.argv[1] if len(sys.argv)>1 else '.'),indent=2,sort_keys=True))
