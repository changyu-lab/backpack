import importlib.util,json,re,subprocess,hashlib
from pathlib import Path
p=Path('/root/sibrc-ra300-20261016');sp=importlib.util.spec_from_file_location('rt',p/'remote_ra300.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
s=dict(filename='AerialCity_3840x1920_30fps_8bit_420_erp.yuv',width=3840,height=1920,fps=30,depth=8)
cmd=m.command(s,p/'smoke65',-37,None);cmd[cmd.index('-f')+1]='65'
assert not (p/'smoke65.vvc').exists()
with (p/'smoke65.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
t=(p/'smoke65.log').read_text();rows=re.findall(r'POC\s+(\d+).*?\(.*?\b([IPB])-SLICE',t);k={int(a):b for a,b in rows}
assert r.returncode==0 and sorted(k)==list(range(65)) and all(k[n]=='I' for n in [0,32,64]) and 'B' in k.values() and re.search(r'GOP size\s+: 32',t),t[-3000:]
(p/'smoke-approved.json').write_text(json.dumps(dict(status='PASS',frames=65,I_pocs=[a for a,b in k.items() if b=='I'],configuration_sha256=m.sha(m.CFG),exe_sha256=m.sha(m.EXE),command=cmd),indent=2))
print('RA65 SMOKE PASS',flush=True)
