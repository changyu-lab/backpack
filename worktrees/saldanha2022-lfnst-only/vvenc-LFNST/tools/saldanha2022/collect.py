"""First-frame planar collection and bitstream-neutral instrumentation checks."""
import argparse, concurrent.futures, hashlib, json, os, subprocess, time
from pathlib import Path

SEQUENCES = [
 ('BasketballPass','BasketballPass_416x240_50.yuv',416,240,50,'train','substitute'),
 ('BQMall','BQMall_832x480_60.yuv',832,480,60,'train','substitute'),
 ('BasketballDrill','BasketballDrill_832x480_50.yuv',832,480,50,'train','substitute'),
 ('RaceHorses','RaceHorses_416x240_30.yuv',416,240,30,'train','substitute'),
 ('Kimono','Kimono_1920x1080_24.yuv',1920,1080,24,'train','paper-source-name-Kimono1'),
 ('ParkScene','ParkScene_1920x1080_24.yuv',1920,1080,24,'train','paper-source'),
 ('FourPeople','FourPeople_1280x720_60.yuv',1280,720,60,'validation','substitute'),
 ('BQSquare','BQSquare_416x240_60.yuv',416,240,60,'validation','substitute'),
]

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):
 p=Path(p); t=p.with_suffix('.tmp'); t.write_text(json.dumps(obj,indent=2),encoding='utf-8'); t.replace(p)

def run(encoder,out,seq,qp,mode,model=None):
 name,file,w,h,fps,*_=seq
 out.mkdir(parents=True,exist_ok=True)
 cmd=[str(encoder),'--preset','medium','-i','I:/HEVC-test/'+file,'-s',f'{w}x{h}','-r',str(fps),
      '--InputChromaFormat','420','--InputBitDepth','8','-q',str(qp),'--qpa','0','-f','1',
      '--mtprofile','0','--threads','1','--IntraPeriod','1','--GOPSize','1','--DecodingRefreshType','1',
      '--additional','LFNST=1 LardLfnstSkip=0','-b',str(out/'stream.vvc')]
 env={k:v for k,v in os.environ.items() if not k.startswith('SALDANHA_')}
 env.update(SALDANHA_MODE=mode,SALDANHA_SEQUENCE=name,SALDANHA_STATS=str(out/'stats.json'))
 if mode=='collect': env.update(SALDANHA_CSV=str(out/'features.csv'),SALDANHA_STRIDE='8',SALDANHA_MAX_ROWS='500000')
 if model: env['SALDANHA_MODEL']=str(model)
 manifest={'command':cmd,'mode':mode,'encoder_sha256':sha(encoder),'model_sha256':sha(model) if model else None,
           'sequence':name,'qp':qp,'frames':1,'split':seq[5],
           'first_frame_sha256':hashlib.sha256(open('I:/HEVC-test/'+file,'rb').read(w*h*3//2)).hexdigest()}
 prior=out/'result.json'
 if prior.exists():
  old=json.loads(prior.read_text())
  if all(old.get(k)==v for k,v in manifest.items()) and old.get('returncode')==0 and (out/'stream.vvc').exists(): return old
  raise RuntimeError('Stale/failed collection directory: '+str(out))
 start=time.perf_counter()
 with (out/'encode.log').open('w') as log:
  p=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
 manifest.update(returncode=p.returncode,seconds=time.perf_counter()-start)
 if p.returncode: save(prior,manifest); raise RuntimeError('Encoding failed '+str(out))
 manifest['bitstream_sha256']=sha(out/'stream.vvc')
 if mode!='off': manifest['statistics']=json.loads((out/'stats.json').read_text())
 save(prior,manifest)
 return manifest

def main():
 p=argparse.ArgumentParser(); p.add_argument('--encoder',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--jobs',type=int,default=4);p.add_argument('--smoke-only',action='store_true')
 a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 fake=a.output/'smoke-only-always-skip.model'
 fake.write_text('LFNST_REPTREE_V1 13 1\n0 -1 0 -1 -1 0 1 0\n')
 results={}
 for name,enc,mode in [('reference',a.baseline,'off'),('off',a.encoder,'off'),('collect',a.encoder,'collect'),('shadow',a.encoder,'shadow'),('on',a.encoder,'on')]:
  results[name]=run(enc,a.output/'smoke'/name,SEQUENCES[0],32,mode,fake if mode in ('shadow','on') else None)
  print('SMOKE',name,results[name]['seconds'],flush=True)
 assert len({results[n]['bitstream_sha256'] for n in ('reference','off','collect','shadow')})==1,'Neutral modes differ'
 assert results['on']['statistics']['suppressed_candidates']>0,'On mode never suppressed candidates'
 save(a.output/'smoke-results.json',results)
 if a.smoke_only: return
 jobs=[(s,q) for s in SEQUENCES for q in (22,27,32,37)]
 save(a.output/'collection-plan.json',{'sequences':SEQUENCES,'frames':1,'qps':[22,27,32,37],
    'sampling_stride':8,'max_rows_per_case':500000,'threads_per_encoder':1,'concurrency':a.jobs,
    'scope':'Retrained adaptation with disclosed training substitutions; ERP14 entirely held out'})
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
  futures={pool.submit(run,a.encoder,a.output/'data'/s[0]/f'QP{q}',s,q,'collect'):(s[0],q) for s,q in jobs}
  done=[]
  for f in concurrent.futures.as_completed(futures):
   result=f.result();done.append(result);save(a.output/'collection-results.json',done)
   print('COLLECT',futures[f],result['seconds'],result['statistics'],flush=True)
 print('COMPLETE',len(done),flush=True)

if __name__=='__main__': main()
