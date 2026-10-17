"""Paired short ERP screening with explicit provenance and original360Lib metrics."""
import argparse,json,subprocess,time,sys,csv
from pathlib import Path
from smoke import sha,ROOT
from quality import measure,bd_rate,KEYS

def prefix_sha(path,n):
 import hashlib
 h=hashlib.sha256()
 with open(path,'rb') as f:
  while n:
   b=f.read(min(1048576,n))
   if not b:raise ValueError('source is shorter than requested frames')
   n-=len(b);h.update(b)
 return h.hexdigest()
def validate_profiles(profiles):
 allowed={'anchor','sibrc','paper1','paper4','paper_ad','joint'}
 if not profiles or len(profiles)!=len(set(profiles)):raise ValueError('profiles must be nonempty and unique')
 if any(x not in allowed for x in profiles):raise ValueError('unknown profile')

def load_targets(path,current):
 values=json.loads(path.read_text())
 if len(values)!=4 or any(not isinstance(v,int) or isinstance(v,bool) or v<=0 for v in values):raise ValueError('targets must contain four positive integer bitrates')
 provenance={'path':str(path.resolve()),'sha256':sha(path),'values_bps':values}
 origin=path.parent/'manifest.json'
 if origin.exists():
  original=json.loads(origin.read_text())
  for key in ('source_prefix_sha256','width','height','frames','fps'):
   if original.get(key)!=current.get(key):raise ValueError('CQP target source/settings mismatch: '+key)
  if original.get('stage')!='cqp':raise ValueError('target origin must be CQP')
  provenance['cqp_manifest']={'path':str(origin.resolve()),'sha256':sha(origin)}
 else:provenance['cqp_manifest']=None
 return values,provenance

def main():
 p=argparse.ArgumentParser();p.add_argument('--encoder',type=Path,required=True);p.add_argument('--decoder',type=Path,required=True);p.add_argument('--metrics',type=Path,required=True);p.add_argument('--sphere',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--width',type=int,default=3840);p.add_argument('--height',type=int,default=1920);p.add_argument('--frames',type=int,default=8);p.add_argument('--fps',type=int,default=30);p.add_argument('--output',type=Path,required=True);p.add_argument('--stage',choices=['cqp','rc'],required=True);p.add_argument('--targets',type=Path);p.add_argument('--profiles',nargs='+');p.add_argument('--strength',type=float,default=1.0);p.add_argument('--model-prefix',type=Path);p.add_argument('--bias-repair',action='store_true');p.add_argument('--intra-anchor',action='store_true');p.add_argument('--qp-radius',type=int,default=2);a=p.parse_args();
 if not 0<=a.qp_radius<=12:raise ValueError('QP radius must be in[0,12]')
 a.output.mkdir(parents=True,exist_ok=False)
 config=ROOT/'docs/vtm23-rc/aerialcity16_ldp.cfg';stats=ROOT/'docs/sibrc/calibration-v1/stats.txt';model=a.model_prefix or ROOT/'docs/sibrc/calibration-v1/model'
 common=['--preset','faster','-c',str(config),'-i',str(a.source),'-s',f'{a.width}x{a.height}','-fr',str(a.fps),'-f',str(a.frames),'--InputBitDepth=8','--InternalBitDepth=10','--OutputBitDepth=10','--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0','--LMCS=0']
 assets={'encoder':a.encoder,'decoder':a.decoder,'metrics':a.metrics,'sphere':a.sphere,'config':config,'stats':stats,'model_I':Path(str(model)+'.I'),'model_P':Path(str(model)+'.P')}
 for kind in ('I','P'):
  meta=Path(str(model)+'.'+kind+'.json')
  if meta.exists():assets['model_'+kind+'_metadata']=meta
 manifest={'source':str(a.source),'source_prefix_sha256':prefix_sha(a.source,a.width*a.height*3//2*a.frames),'frames':a.frames,'width':a.width,'height':a.height,'fps':a.fps,'stage':a.stage,'temporal_strength':a.strength,'bias_repair':a.bias_repair,'intra_anchor':a.intra_anchor,'qp_action_bounds':[-a.qp_radius,a.qp_radius],'assets':{k:{'path':str(v),'sha256':sha(v)} for k,v in assets.items()},'interpretation':'short screening; not 300-frame paper replication'}
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
 targets=None
 if a.stage=='rc':
  if not a.targets:raise ValueError('RC requires frozen target JSON from CQP anchor')
  targets,manifest["frozen_targets"]=load_targets(a.targets,manifest)
  (a.output/"manifest.json").write_text(json.dumps(manifest,indent=2))
 profiles=a.profiles or (['anchor','paper1','paper4','paper_ad'] if a.stage=='cqp' else ['anchor','sibrc','paper1','paper4','paper_ad','joint'])
 validate_profiles(profiles)
 if a.stage=='cqp' and any(x in profiles for x in ['sibrc','joint']):raise ValueError('SIBRC requires RC stage')
 records=[];curves={}
 for profile in profiles:
  curve=[]
  for i,qp in enumerate([22,27,32,37]):
   if (a.output/'STOP').exists():print('Stopped between jobs',flush=True);return
   stem=a.output/(profile+'_R'+str(i+1));cmd=[str(a.encoder)]+common+['-b',str(stem)+'.vvc','-o',str(stem)+'.yuv','--QP='+str(qp)]
   if targets:cmd+=['--VTMTargetBitrate='+str(targets[i]),'--VTMRCTrace='+str(stem)+'.vtm.csv']
   if profile in ['sibrc','joint']:cmd+=['--SIBRCMode=3','--SIBRCMinOffset='+str(-a.qp_radius),'--SIBRCMaxOffset='+str(a.qp_radius),'--SIBRCStats='+str(stats),'--SIBRCModel='+str(model),'--SIBRCTrace='+str(stem)+'.sibrc.csv']
   if profile in ['sibrc','joint']:cmd+=['--SIBRCBiasRepair='+str(int(a.bias_repair)),'--SIBRCIntraAnchor='+str(int(a.intra_anchor))]
   if profile.startswith('paper') or profile=='joint':cmd+=['--TPSMMode='+str(2 if profile=='joint' else 1),'--TPSMChain='+str({'paper1':1,'paper4':4}.get(profile,0)),'--TPSMTrace='+str(stem)+'.tpsm.csv']
   if profile=='joint':cmd+=['--TPSMStrength='+str(a.strength)]
   rec={'profile':profile,'qp_label':qp,'target_bps':targets[i] if targets else None,'command':cmd};start=time.time()
   with open(str(stem)+'.log','w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
   rec.update(exit_code=r.returncode,encode_elapsed_seconds=time.time()-start);records.append(rec);(a.output/'runs.json').write_text(json.dumps(records,indent=2))
   if r.returncode:raise RuntimeError('encode failed '+str(stem))
   dec=[str(a.decoder),'-b',str(stem)+'.vvc','-o',str(stem)+'.decoded.yuv','--OutputBitDepth=10'];rec['decoder_command']=dec
   with open(str(stem)+'.decode.log','w') as log:subprocess.run(dec,check=True,stdout=log,stderr=subprocess.STDOUT)
   rec['bitstream_sha256']=sha(str(stem)+'.vvc');rec['reconstruction_sha256']=sha(str(stem)+'.yuv')
   if rec['reconstruction_sha256']!=sha(str(stem)+'.decoded.yuv'):raise RuntimeError('decode mismatch '+str(stem))
   q=measure(a.source,str(stem)+'.yuv',a.width,a.height,a.frames,str(stem)+'.vvc',a.fps,a.metrics,a.sphere);q['encode_elapsed_seconds']=rec['encode_elapsed_seconds'];q['target_bps']=rec['target_bps'];q['rate_error_percent']=None if not targets else 100*(q['actual_bps']/targets[i]-1);curve.append(q)
   (Path(str(stem)+'.quality.json')).write_text(json.dumps(q,indent=2));(a.output/'runs.json').write_text(json.dumps(records,indent=2));print(profile,qp,round(q['actual_bps']),[round(q[k],4) for k in KEYS],flush=True)
  curves[profile]=curve;(a.output/'curves.json').write_text(json.dumps(curves,indent=2))
  if profile=='anchor' and not targets:(a.output/'targets.json').write_text(json.dumps([round(q['actual_bps']) for q in curve],indent=2))
  results={}
  for ref in ['anchor','sibrc']:
   if ref in curves:
    for cand in curves:
     if cand==ref:continue
     values={}
     for k in KEYS:
      try:values[k]=bd_rate([q[k] for q in curves[ref]],[q['actual_bps'] for q in curves[ref]],[q[k] for q in curves[cand]],[q['actual_bps'] for q in curves[cand]])
      except ValueError as e:values[k]={'unavailable':str(e)}
     results[cand+'_vs_'+ref]=values
  (a.output/'bd_rates.json').write_text(json.dumps(results,indent=2))
if __name__=='__main__':main()
