import importlib.util,json,re,subprocess
from pathlib import Path
p=Path('/root/sibrc-ldp16-300-20261015');sp=importlib.util.spec_from_file_location('runner',p/'remote_ldp16_300.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
s=dict(filename='AerialCity_3840x1920_30fps_8bit_420_erp.yuv',width=3840,height=1920,fps=30,depth=8)
cmd=m.command(s,p/'gop16-smoke',-37,None);cmd[cmd.index('-f')+1]='17'
with (p/'gop16-smoke.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
t=(p/'gop16-smoke.log').read_text();k=re.findall(r'POC\s+\d+.*?\(.*?([IPB])-SLICE',t)
assert r.returncode==0 and k==['I']+['P']*16,t[-3000:]
(p/'gop16-smoke-approved.json').write_text(json.dumps(dict(status='PASS',command=cmd,framekinds=k)))
