import json,subprocess
from pathlib import Path
b=Path('/data/vtmrc-vvenc-tune-round2-20261014')
p=b/'plan.json';old=p.read_text();(b/'plan-before-bounds-fix.json').write_text(old)
plan=json.loads(old);plan['offsets']=[[0,3],[0,4],[0,5],[0,6],[-1,3],[-1,2],[-2,1],[-3,0],[-3,1]];plan['bounds_correction']='Frozen encoder requires min<=0<=max; invalid one-sided nonzero trials retained and excluded.';p.write_text(json.dumps(plan,indent=2))
runner=b/'remote_tune.py';src=runner.read_text();src=src.replace("str(BASE/'vvenc/tools/sibrc/verify_intra_contract.py')","str(FROZEN/'vvenc/tools/sibrc/verify_intra_contract.py')");runner.write_text(src)
bad=[];valid=0
for path in (b/'runs').rglob('*.run.json'):
 r=json.loads(path.read_text())
 if not r['verified']:bad.append(str(path));continue
 valid+=1;contract=Path(r['prefix']+'.contract.json')
 if not contract.exists():subprocess.run(['python3',str(b/'vvenc/tools/sibrc/verify_intra_contract.py'),r['prefix'],'--output',str(contract)],check=True,stdout=subprocess.DEVNULL)
(b/'bounds-correction-record.json').write_text(json.dumps(dict(invalid_trials_retained=bad,valid_encodes_reused=valid),indent=2))
subprocess.run(['python3','-u',str(runner)],cwd=b,check=True)
