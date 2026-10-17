import importlib.util,json
from pathlib import Path
p=Path('/root/sibrc-ra300-20261016');sp=importlib.util.spec_from_file_location('rt',p/'remote_ra300.py');r=importlib.util.module_from_spec(sp);sp.loader.exec_module(r)
records=[json.loads(f.read_text()) for f in (p/'runs').rglob('*.run.json')]
good=[x for x in records if x['verified'] and x['label']!='cqp']
for x in good:r.quality(x)
r.save(p/'partial-quality-completion.json',dict(verified_comparison_streams=len(good),failed_comparison_streams=5,full_four_point_BD_available=False))
print('COMPLETE VERIFIED PARTIAL METRICS',len(good),flush=True)
