import json, os, subprocess, hashlib
from pathlib import Path
root=Path('I:/vvenc-LFNST/.tmp/saldanha2022/trained-smoke')
root.mkdir(exist_ok=True)
w=Path('C:/Users/hitxi/.codex/worktrees/saldanha2022-lfnst-only/vvenc-LFNST')
results={}
for mode in ['off','shadow','on']:
 d=root/mode; d.mkdir(exist_ok=True)
 env={k:v for k,v in os.environ.items() if not k.startswith('SALDANHA_')}
 env.update(SALDANHA_MODE=mode,SALDANHA_MODEL=str(w/'models/saldanha2022/model.txt'),SALDANHA_STATS=str(d/'stats.json'))
 cmd=[str(w/'bin/release-static/vvencFFapp.exe'),'--preset','medium','-i','I:/HEVC-test/BasketballPass_416x240_50.yuv','-s','416x240','-r','50','--InputBitDepth','8','-q','32','--qpa','0','-f','1','--mtprofile','0','--threads','1','--IntraPeriod','1','--GOPSize','1','--DecodingRefreshType','1','--additional','LFNST=1 LardLfnstSkip=0','-b',str(d/'stream.vvc'),'-o',str(d/'recon.yuv')]
 with (d/'encode.log').open('w') as f: subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
 results[mode]={'command':cmd,'hashes':{n:hashlib.sha256((d/n).read_bytes()).hexdigest() for n in ['stream.vvc','recon.yuv']}}
 if mode!='off':results[mode]['stats']=json.loads((d/'stats.json').read_text())
assert results['off']['hashes']==results['shadow']['hashes']
assert results['on']['stats']['suppressed_candidates']>0
(root/'results.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
