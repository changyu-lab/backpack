import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import fixed_runtime as r
B=r.BASE;OLD=r.ORIGINAL;BETAS=[2,3,5,8,12,18,20]
def checked(pre):
 x=json.loads(pre.with_suffix('.run.json').read_text());assert x['verified']
 for f,h in x['outputs_sha256'].items():assert r.sha(f)==h,f
 q=json.loads(pre.with_suffix('.quality.json').read_text());assert q['bitstream_sha256']==r.sha(pre.with_suffix('.vvc'))
 return x,q
def main():
 specs=json.loads((OLD/'sources.json').read_text());assert len(specs)==6
 assets={str(p):r.sha(p) for p in [r.EXE,r.METRIC,r.DEC,r.CFG,r.STATS,OLD/'models/B5/model.I',OLD/'models/B5/model.P']}
 dest=B/'frozen-assets.json'
 if dest.exists():assert json.loads(dest.read_text())==assets
 else:r.save(dest,assets)
 r.save(B/'sources.json',specs)
 reuse=[]
 for s in specs:
  for label,base in [('anchor',r.PREVIOUS),('B5',OLD)]:
   for i in range(1,5):
    pre=base/'runs'/s['name']/label/('R'+str(i));x,q=checked(pre);reuse.append(dict(sequence=s['name'],label=label,point=i,prefix=str(pre),bitstream_sha256=q['bitstream_sha256']))
 r.save(B/'reuse-manifest.json',reuse)
 jobs=[(s,'B'+str(beta),i,rate,[-2,2,beta]) for s in specs for beta in BETAS if beta!=5 for i,rate in enumerate(s['targets'],1)]
 assert len(jobs)==144
 with ThreadPoolExecutor(max_workers=28) as pool:records=list(pool.map(r.encode,jobs))
 summary={}
 for s in specs:
  anchor=[checked(r.PREVIOUS/'runs'/s['name']/'anchor'/('R'+str(i)))[1] for i in range(1,5)]
  summary[s['name']]={}
  for beta in BETAS:
   if beta==5:qs=[checked(OLD/'runs'/s['name']/'B5'/('R'+str(i)))[1] for i in range(1,5)]
   else:qs=[r.quality(x) for x in records if x['sequence']==s['name'] and x['label']=='B'+str(beta)]
   assert len(qs)==4;summary[s['name']][str(beta)]=r.compare(anchor,qs);r.save(B/'summary-progress.json',summary)
 r.save(B/'summary.json',dict(bd=summary,betas=BETAS,protocol='Fixed current sweep B5 I/P models; only runtime beta changed; 144 new streams,24 B5+24 Anchor reused; RA32 six sequences; development City/Country'))
 print('COMPLETE FIXED B5 SWEEP',flush=True)
if __name__=='__main__':main()
