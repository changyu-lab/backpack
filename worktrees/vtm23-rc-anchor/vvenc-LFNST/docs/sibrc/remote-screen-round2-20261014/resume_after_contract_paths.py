import time,os,subprocess,json
from pathlib import Path
b=Path('/data/vtmrc-vvenc-tune-round2-20261014')
while Path('/proc/1902261').exists():time.sleep(10)
for path in (b/'runs').rglob('*.run.json'):
 r=json.loads(path.read_text());assert r['verified']
 prefix=r['prefix'];contract=Path(prefix+'.contract.json')
 if not contract.exists():subprocess.run(['python3',str(b/'vvenc/tools/sibrc/verify_intra_contract.py'),prefix,'--output',str(contract)],check=True)
subprocess.run(['python3','-u',str(b/'remote_tune.py')],cwd=b,check=True)
