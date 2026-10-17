"""Frozen-schedule CTU +/-1 contrasts. Scientific validation, no algorithm tuning."""
import argparse,csv,gzip,hashlib,json,os,re,subprocess,time,sys,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
from smoke import ROOT,sha
from screen import prefix_sha
from marginal import select_ctus,contrast,ranking

def save(p,x):
 t=Path(str(p)+'.tmp');t.write_text(json.dumps(x,indent=2));t.replace(p)

def frame_metrics(source,recon,width,height,frames):
 pixels=width*height;w=np.cos(np.pi*((np.arange(height)+.5)/height-.5));mass=float(w.sum()*width);sse=[];hashes=[]
 with open(source,'rb') as f,open(recon,'rb') as g:
  for k in range(frames):
   a=f.read(pixels);b=g.read(pixels*2);assert len(a)==pixels and len(b)==pixels*2
   x=np.frombuffer(a,dtype='u1').reshape(height,width);y=np.frombuffer(b,dtype='<u2').reshape(height,width)
   assert np.max(y)<=1023
   d=x.astype(float)-y.astype(float)/4.;d*=d;sse.append(float(np.dot(d.sum(axis=1),w)))
   ac=f.read(pixels//2);bc=g.read(pixels);assert len(ac)==pixels//2 and len(bc)==pixels
   hashes.append(hashlib.sha256(b+bc).hexdigest())
 return {'wsse':sse,'wspsnr':[float(10*np.log10(255**2/(x/mass))) for x in sse],'frame_reconstruction_sha256':hashes}

def picture_bits(log,frames):
 values=re.findall(r'POC\s+(\d+).*?\s(\d+) bits',Path(log).read_text())
 if [int(x[0]) for x in values]!=list(range(frames)):raise ValueError('picture bit/POC coverage mismatch')
 return [int(x[1]) for x in values]

def main():
 p=argparse.ArgumentParser();p.add_argument('--encoder',required=True,type=Path);p.add_argument('--decoder',required=True,type=Path);p.add_argument('--source',required=True,type=Path);p.add_argument('--config',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--expected-baseline',required=True);p.add_argument('--width',type=int,default=3840);p.add_argument('--height',type=int,default=1920);p.add_argument('--frames',type=int,default=65);p.add_argument('--poc',type=int,default=8);p.add_argument('--target',type=int,default=818855);p.add_argument('--jobs',type=int,default=4);p.add_argument('--scratch',type=Path);p.add_argument('--baseline-only',action='store_true');a=p.parse_args()
 a.output.mkdir(exist_ok=True,parents=True);temp=a.scratch or a.output/'temporary';temp.mkdir(exist_ok=True,parents=True);decisions=a.output/'baseline.decisions'
 stats=ROOT/'docs/sibrc/calibration-v1/stats.txt';model=ROOT/'docs/sibrc/calibration-v1/model'
 common=[str(a.encoder),'--preset','faster','-c',str(a.config),'-i',str(a.source),'-s',f'{a.width}x{a.height}','-fr','30','-f',str(a.frames),'--InputBitDepth=8','--InternalBitDepth=10','--OutputBitDepth=10','--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0','--VTMTargetBitrate='+str(a.target),'--SIBRCMode=3','--SIBRCMinOffset=-2','--SIBRCMaxOffset=2','--SIBRCBiasRepair=1','--SIBRCIntraAnchor=1','--SIBRCStats='+str(stats),'--SIBRCModel='+str(model),'--TPSMMode=2','--TPSMStrength=0','--TPSMChain=0']
 assets=[a.encoder,a.decoder,a.config,stats,Path(str(model)+'.I'),Path(str(model)+'.P'),Path(__file__),ROOT/'tools/tpsm/marginal.py']
 protocol={'geometry':[a.width,a.height],'frames':a.frames,'probe_poc':a.poc,'target_bps':a.target,'source_prefix_sha256':prefix_sha(a.source,a.width*a.height*3//2*a.frames),'assets':{str(p):sha(p) for p in assets},'expected_baseline_sha256':a.expected_baseline,'sampling':'seed20261016;4 CTUs per wt<1,wt=1,wt>1; current inter eligibility and complete configured prior beta chain, no intervening reset, bits>=32; POC8 selected from baseline-only diversity after POC16 failed; select before perturbation results','objective':'strictly future final-reconstruction spherical luma SSE; current-frame and future effects separated','limitation':'QP and lambda frozen; coding modes, MV choices, entropy and filters respond; finite contrasts include within-frame interactions and altered future bits'}
 old=a.output/'protocol.json'
 if old.exists():assert json.loads(old.read_text())==protocol,'resume protocol/assets changed'
 else:save(old,protocol)
 def encode(name,extra):
  if (a.output/'STOP').exists():raise RuntimeError('STOP requested between jobs')
  done=a.output/(name+'.metrics.json')
  if done.exists():return json.loads(done.read_text())
  stem=a.output/name;rec=temp/(name+'.yuv');decoded=temp/(name+'.decoded.yuv')
  if shutil.disk_usage(temp).free<3*1024**3:raise RuntimeError('insufficient reconstruction scratch')
  cmd=common+['-b',str(stem)+'.vvc','-o',str(rec),'--TPSMTrace='+str(stem)+'.tpsm.csv','--SIBRCTrace='+str(stem)+'.sibrc.csv','--VTMRCTrace='+str(stem)+'.vtm.csv']+extra
  start=time.time()
  with open(str(stem)+'.log','w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
  dc=[str(a.decoder),'-b',str(stem)+'.vvc','-o',str(decoded),'--OutputBitDepth=10']
  with open(str(stem)+'.decode.log','w') as f:subprocess.run(dc,stdout=f,stderr=subprocess.STDOUT,check=True)
  assert rec.stat().st_size==a.width*a.height*3*a.frames and sha(rec)==sha(decoded),'decode mismatch'
  q=frame_metrics(a.source,rec,a.width,a.height,a.frames);q.update(picture_bits=picture_bits(str(stem)+'.log',a.frames),annexb_bits=Path(str(stem)+'.vvc').stat().st_size*8,bitstream_sha256=sha(str(stem)+'.vvc'),reconstruction_sha256=sha(rec),decoder_reconstruction_sha256=sha(decoded),elapsed_seconds=time.time()-start)
  save(a.output/(name+'.run.json'),{'command':cmd,'decoder_command':dc,'returncode':0})
  assert rec.parent==temp and decoded.parent==temp;rec.unlink();decoded.unlink()
  for path in a.output.glob(name+'.*.csv'):
   raw=path.read_bytes();z=Path(str(path)+'.gz');z.write_bytes(gzip.compress(raw,mtime=0));assert gzip.decompress(z.read_bytes())==raw;path.unlink()
  save(done,q) # Completion checkpoint only after trace archival and reconstruction cleanup.
  print('DONE',name,round(q['elapsed_seconds'],1),flush=True);return q
 baseline=encode('baseline',['--VTMDecisionRecord='+str(decisions)]);assert baseline['bitstream_sha256']==a.expected_baseline,'baseline differs from historical SIBRC'
 zero=encode('zero_replay',['--VTMDecisionReplay='+str(decisions)]);assert zero['bitstream_sha256']==baseline['bitstream_sha256'],'zero replay differs'
 with gzip.open(a.output/'baseline.tpsm.csv.gz','rt') as f:rows=list(csv.DictReader(f))
 selected=select_ctus(rows,a.poc,4)
 selection={'decision_sha256':sha(decisions),'selection_before_probes':True,'samples':selected}
 frozen=a.output/'selection.json'
 if frozen.exists():assert json.loads(frozen.read_text())==selection
 else:save(frozen,selection)
 if a.baseline_only:print('BASELINE_AND_ZERO_IDENTITY_PASSED',flush=True);return
 records=[]
 with ThreadPoolExecutor(max_workers=a.jobs) as pool:
  jobs={pool.submit(encode,'ctu'+r['ctu']+('_minus' if off==-1 else '_plus'),['--VTMDecisionReplay='+str(decisions),'--VTMProbePOC='+str(a.poc),'--VTMProbeCTU='+r['ctu'],'--VTMProbeOffset='+str(off)]):(r,off) for r in selected for off in [-1,1]}
  for future in as_completed(jobs):
   r,off=jobs[future];q=future.result();assert q['frame_reconstruction_sha256'][:a.poc]==baseline['frame_reconstruction_sha256'][:a.poc],'pre-probe prefix changed';records.append({'ctu':r['ctu'],'offset':off});save(a.output/'progress.json',{'completed_probes':len(records),'total_probes':24})
 results=[]
 for r in selected:
  minus=json.loads((a.output/('ctu'+r['ctu']+'_minus.metrics.json')).read_text());plus=json.loads((a.output/('ctu'+r['ctu']+'_plus.metrics.json')).read_text())
  row={'ctu':int(r['ctu']),'wt':float(r['wt']),'stratum':r['stratum'],'baseline_ctu_bits':int(r['bits']),'baseline_qp':int(r['qp']),'minus_vs_baseline':contrast(minus,baseline,a.poc),'baseline_vs_plus':contrast(baseline,plus,a.poc),'central_minus_vs_plus':contrast(minus,plus,a.poc),'central_annexb_extra_bits':minus['annexb_bits']-plus['annexb_bits'],'minus_bitstream_unchanged':minus['bitstream_sha256']==baseline['bitstream_sha256'],'plus_bitstream_unchanged':plus['bitstream_sha256']==baseline['bitstream_sha256']}
  row['central_future_psnr_gain_sum_db']=sum(x-y for x,y in zip(minus['wspsnr'][a.poc+1:],plus['wspsnr'][a.poc+1:]));results.append(row)
 valid=[r for r in results if r['central_minus_vs_plus']['amplification'] is not None]
 tests={}
 for label,field in [('future_per_current_error','amplification'),('raw_future_reduction','future_sse_reduction')]:
  use=valid if field=='amplification' else results
  tests[label]=ranking([r['wt'] for r in use],[r['central_minus_vs_plus'][field] for r in use]) if len(use)>1 else {'spearman':None,'n':len(use)}
 save(a.output/'results.json',{'samples':results,'rank_tests':tests,'invalid_amplification_samples':len(results)-len(valid),'interpretation':'finite one-frame stratified diagnostic; response per current error is primary, raw future benefit is content-confounded; no population inference','baseline_and_zero_identity':True,'all_26_decodes_hash_verified':True});print(json.dumps(tests),flush=True)
if __name__=='__main__':main()
