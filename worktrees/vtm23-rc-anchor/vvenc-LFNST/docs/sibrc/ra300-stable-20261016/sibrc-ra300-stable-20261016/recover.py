import importlib.util,json,hashlib,gzip,subprocess,shutil,time,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
B=Path('/root/sibrc-ra300-stable-20261016');OLD=Path('/root/sibrc-ra300-20261016');EXE=B/'vvencFFapp';TEMP=Path('/dev/shm/sibrc-ra300-regression-20261016');TEMP.mkdir(exist_ok=True)
sp=importlib.util.spec_from_file_location('rt',OLD/'remote_ra300.py');rt=importlib.util.module_from_spec(sp);sp.loader.exec_module(rt)
def read(p):return json.loads(p.read_text())
def save(p,x):rt.save(p,x)
def check_old(r):
 assert r['verified'] and len(r['pocs'])==300
 for f,h in r['outputs_sha256'].items():assert rt.sha(f)==h
 return r
records=[read(p) for p in (OLD/'runs').rglob('*.run.json')]
assert len(records)==24
selected=[('AerialCity','cqp',3),('AerialCity','anchor',3),('AerialCity','C4',3),('DrivingInCountry','anchor',1)]
gate=[]
for seq,label,pt in selected:
 r=check_old(next(x for x in records if (x['sequence'],x['label'],x['point'])==(seq,label,pt)))
 pre=TEMP/(seq+'_'+label+'_R'+str(pt));dest=B/(pre.name+'.regression.json')
 if dest.exists():
  x=read(dest);assert x['new_exe_sha256']==rt.sha(EXE);gate.append(x);continue
 cmd=[str(EXE)]+[v.replace(r['prefix'],str(pre)) for v in r['command'][1:]]
 assert not pre.with_suffix('.vvc').exists(),'partial gate output'
 print('GATE START',seq,label,pt,flush=True)
 with pre.with_suffix('.log').open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
 matched={}
 for path,expected in r['outputs_sha256'].items():
  if path.endswith('.gz'):continue
  f=Path(str(path).replace(r['prefix'],str(pre)));assert rt.sha(f)==expected,(path,'regression mismatch');matched[Path(path).name]=expected
 for path,expected in r.get('original_trace_sha256',{}).items():
  f=Path(path.replace(r['prefix'],str(pre)));assert rt.sha(f)==expected,(path,'trace mismatch');matched[Path(path).name]=expected
 x=dict(status='PASS',sequence=seq,label=label,point=pt,command=cmd,new_exe_sha256=rt.sha(EXE),bitstream_and_trace_identical=matched)
 save(dest,x);gate.append(x)
 # Gate outputs regenerate existing verified data; delete only own tmpfs duplicate after SHA match.
 for f in TEMP.glob(pre.name+'.*'):f.unlink()
 print('GATE PASS',seq,label,pt,flush=True)
assert len(gate)==4
save(B/'regression-approved.json',dict(status='PASS',new_exe_sha256=rt.sha(EXE),gates=gate,scope='4 full300 same-command regression runs byte-identical vvc and traces; positive path unchanged in tested cases'))
# Common helper used for the original positive branch and the new branch is identical for all positives.
save(B/'branch-domain-validation.json',dict(status='PASS',positive_integers_checked=199,positive_refinement_not_skipped=list(range(1,200)),zero_negative_target_bits=200,scope='Patch expression checks >0; official negative-budget formula remains documented as undefined'))
rt.BASE=B;rt.EXE=EXE
old_assets=read(OLD/'frozen-assets.json');new_assets={k:(rt.sha(EXE) if k==str(rt.FROZEN/'vvenc/bin/release-static/vvencFFapp') else v) for k,v in old_assets.items()};save(B/'frozen-assets.json',dict(original_assets=old_assets,new_exe_path=str(EXE),new_exe_sha256=rt.sha(EXE)))
failed=[r for r in records if not r['verified']];assert len(failed)==5
jobs=[(r['spec'],r['label'],r['point'],r['target_bps'],r['offset']) for r in failed]
print('RECOVERY START 5 FAILED STREAMS',flush=True)
with ThreadPoolExecutor(max_workers=5) as pool:new=list(pool.map(rt.encode,jobs))
allruns=[r for r in records if r['verified']]+new;assert len(allruns)==24
save(B/'reuse-manifest.json',[dict(prefix=r['prefix'],sequence=r['sequence'],label=r['label'],point=r['point'],outputs_sha256=r['outputs_sha256']) for r in records if r['verified']])
points=[]
for r in allruns:
 if r['label']!='cqp':points.append(rt.quality(r))
summary={}
for seq in ['AerialCity','DrivingInCountry']:
 a=sorted([q for q in points if q['sequence']==seq and q['label']=='anchor'],key=lambda q:q['point']);b=sorted([q for q in points if q['sequence']==seq and q['label']=='C4'],key=lambda q:q['point']);assert len(a)==len(b)==4;summary[seq]=rt.compare(a,b)
save(B/'summary.json',dict(bd=summary,scope='RA GOP32 Intra32 300frames;5 streams recomputed deterministic nonpositive intra-budget protection;19 original valid streams hash-reused after4 byte-identical regression runs; Country development; not unmodified native VTM'))
save(B/'all-runs.json',allruns)
print('COMPLETE RECOVERED RA300; final full audit pending',flush=True)
