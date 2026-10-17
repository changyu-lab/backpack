import json,subprocess,numpy as np
from pathlib import Path
b=Path('/data/vtmrc-vvenc-tune-20261014');f=b/'metric-fixtures'
for depth in (8,10):
 out=f/('linux'+str(depth)+'.json')
 subprocess.run([str(b/'metrics-build/metrics360'),str(f/('source'+str(depth)+'.yuv')),str(f/'recon.yuv'),'64','32','1','/root/VTM-23.0-paper-scc-rc-anchor-fit/cfg-360Lib/360Lib/sphere_655362.txt',str(out),'1','all',str(depth)],check=True)
 actual=json.loads(out.read_text());expected=json.loads((f/('old8.json' if depth==8 else 'new10.json')).read_text())
 for key in expected:assert np.allclose(actual[key],expected[key],rtol=0,atol=1e-9),(depth,key,actual,expected)
(b/'linux-metric-approved.json').write_text(json.dumps({'pass_test':True,'tolerance':1e-9,'checks':['Linux8_vs_frozenWindows8','Linux10_vs_frozenWindows10']}))
print('PASS Linux native metric fixtures')
