import json,re,hashlib
from pathlib import Path
p=Path('/root/sibrc-ldp16-300-20261015');t=(p/'gop16-smoke.log').read_text()
k=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',t)
assert k==['I']+['P']*16 and 'Total Time:' in t and re.search(r'GOP size\s+: 16',t)
(p/'gop16-smoke-approved.json').write_text(json.dumps(dict(status='PASS',framekinds=k,scope='Existing completed 17-frame CQP smoke reused; parser backspace escape corrected; no re-encode',log_sha256=hashlib.sha256(t.encode()).hexdigest()),indent=2))
print('GOP16 SMOKE PASS')
