"""Fresh-output integration checks; synthetic ERP fixture is not performance evidence."""
import argparse,hashlib,json,subprocess,time,sys
from pathlib import Path
import numpy as np
from audit import verify
ROOT=Path(__file__).resolve().parents[2]
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--encoder',type=Path,required=True);p.add_argument('--decoder',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--baseline',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 source=a.output/'fixture.yuv';rng=np.random.default_rng(3);y,x=np.mgrid[:256,:512];base=np.clip(110+40*np.sin(x/13)+30*np.cos(y/9)+rng.integers(-8,9,(256,512)),0,255).astype('u1')
 with source.open('wb') as f:
  for t in range(8):f.write(np.roll(base,t,axis=1).tobytes()+bytes([128])*(512*256//2))
 config=ROOT/'docs/vtm23-rc/aerialcity16_ldp.cfg';stats=ROOT/'docs/sibrc/calibration-v1/stats.txt';model=ROOT/'docs/sibrc/calibration-v1/model'
 common=['--preset','faster','-c',str(config),'-i',str(source),'-s','512x256','-fr','30','-f','8','--InputBitDepth=8','--InternalBitDepth=10','--OutputBitDepth=10','--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0','--LMCS=0','--QP=32']
 partial=a.output/'partial.yuv'
 with partial.open('wb') as f:
  for t in range(8):f.write(np.roll(base,t,axis=1)[:192,:192].tobytes()+bytes([128])*(192*192//2))
 records=[]
 def run(name,opts,encoder=None,expect_failure=False,partial_picture=False):
  args=common.copy()
  if partial_picture:args[args.index('-i')+1]=str(partial);args[args.index('-s')+1]='192x192'
  prefix=a.output/name;cmd=[str(encoder or a.encoder)]+args+['-b',str(prefix)+'.vvc','-o',str(prefix)+'.yuv']+opts
  start=time.time()
  with open(str(prefix)+'.log','w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
  rec={'name':name,'command':cmd,'exit_code':r.returncode,'elapsed_seconds':time.time()-start};records.append(rec)
  (a.output/'runs.json').write_text(json.dumps(records,indent=2))
  if expect_failure:
   if r.returncode==0:raise RuntimeError(name+' incorrectly accepted')
   return
  if r.returncode:raise RuntimeError(name+' failed: '+str(prefix)+'.log')
  rec['bitstream_sha256']=sha(str(prefix)+'.vvc');rec['reconstruction_sha256']=sha(str(prefix)+'.yuv')
  dec=[str(a.decoder),'-b',str(prefix)+'.vvc','-o',str(prefix)+'.decoded.yuv','--OutputBitDepth=10'];rec['decoder_command']=dec
  with open(str(prefix)+'.decode.log','w') as log:subprocess.run(dec,check=True,stdout=log,stderr=subprocess.STDOUT)
  if sha(str(prefix)+'.decoded.yuv')!=rec['reconstruction_sha256']:raise RuntimeError('decode mismatch '+name)
  if any(o.startswith('--TPSMAudit=') for o in opts):rec['predictor_audit']=verify(str(prefix)+'.audit.bin',str(prefix)+'.tpsm.csv')
  (a.output/'runs.json').write_text(json.dumps(records,indent=2));print(name+' passed',flush=True)
 def tpsm(name,mode,chain=0):return ['--TPSMMode='+str(mode),'--TPSMChain='+str(chain),'--TPSMTrace='+str(a.output/name)+'.tpsm.csv','--TPSMAudit='+str(a.output/name)+'.audit.bin']
 def sib(name):return ['--VTMRCTrace='+str(a.output/name)+'.vtm.csv','--VTMTargetBitrate=1000000','--SIBRCMode=3','--SIBRCStats='+str(stats),'--SIBRCModel='+str(model),'--SIBRCTrace='+str(a.output/name)+'.sibrc.csv']
 run('off',[]);run('explicit_off',['--TPSMMode=0']);run('paper1',tpsm('paper1',1,1));run('paper4',tpsm('paper4',1,4));run('paper_ad',tpsm('paper_ad',1));run('paper_repeat',tpsm('paper_repeat',1));run('paper_qp22',tpsm('paper_qp22',1)+['--QP=22']);run('sibrc',sib('sibrc'));run('joint',sib('joint')+tpsm('joint',2));run('joint_zero',sib('joint_zero')+tpsm('joint_zero',2)+['--TPSMStrength=0']);run('joint_strong',sib('joint_strong')+tpsm('joint_strong',2)+['--TPSMStrength=4']);run('paper_rc',['--VTMTargetBitrate=1000000']+tpsm('paper_rc',1));run('paper_partial',tpsm('paper_partial',1),partial_picture=True);run('paper_cache',tpsm('paper_cache',1)+['--MaxMTTDepth=3','--MaxMTTDepthI=3','--FastQtBtEnc=0','--QtbttExtraFast=0']);run('bad_lossless',tpsm('bad_lossless',1)+['--CostMode=lossless'],expect_failure=True);run('bad_combination',tpsm('bad_combination',2),expect_failure=True)
 run('anchor_rc',['--VTMTargetBitrate=1000000','--VTMRCTrace='+str(a.output/'anchor_rc.vtm.csv')])
 repair=['--SIBRCBiasRepair=1','--SIBRCIntraAnchor=1']
 run('repaired',sib('repaired')+repair)
 run('repaired_zero',sib('repaired_zero')+repair+tpsm('repaired_zero',2)+['--TPSMStrength=0'])
 run('repaired_refresh',sib('repaired_refresh')+repair+['--IntraPeriod=4'])
 run('repaired_joint',sib('repaired_joint')+repair+tpsm('repaired_joint',2)+['--TPSMStrength=4'])
 run('bad_repair',['--SIBRCBiasRepair=1'],expect_failure=True)
 import csv
 with open(a.output/'repaired.sibrc.csv') as f: rows=list(csv.DictReader(f))
 intra=[r for r in rows if r['kind']=='I']
 assert intra and all(int(r['offset'])==0 and float(r['predicted_bits'])==0 for r in intra),'intra must bypass controller'
 with open(a.output/'repaired_refresh.sibrc.csv') as f: refresh=list(csv.DictReader(f))
 later=[r for r in refresh if r['kind']=='I' and int(r['poc'])>0]
 assert later and all(int(r['offset'])==0 and float(r['predicted_bits'])==0 for r in later),'later intra must bypass prior inter controller'
 assert any(r['kind']=='P' and int(r['poc'])>int(later[0]['poc']) for r in refresh),'inter after refresh must resume'
 def intra_trace(name):
  with open(a.output/(name+'.vtm.csv')) as f:return [r for r in csv.DictReader(f) if int(r['poc'])==0]
 assert intra_trace('anchor_rc')==intra_trace('repaired'),'intra VTM decision and feedback identity'
 if a.baseline:run('baseline',[],a.baseline);run('baseline_sibrc',sib('baseline_sibrc'),a.baseline)
 if a.baseline:
  for suffix in ['.sibrc.csv','.vtm.csv']:
   if sha(str(a.output/'sibrc')+suffix)!=sha(str(a.output/'baseline_sibrc')+suffix):raise RuntimeError('SIBRC disabled TPSM trace mismatch '+suffix)
 by={r['name']:r for r in records}
 for x,y in [('repaired','repaired_zero'),('off','explicit_off'),('paper_ad','paper_repeat'),('sibrc','joint_zero')]+([('off','baseline'),('sibrc','baseline_sibrc')] if a.baseline else []):
  if by[x]['bitstream_sha256']!=by[y]['bitstream_sha256']:raise RuntimeError('identity mismatch '+x+'/'+y)
 with open(str(a.output/'paper_cache')+'.tpsm.csv') as f:cache_count=sum(int(r['cached_inter_cus']) for r in __import__('csv').DictReader(f))
 if cache_count==0:raise RuntimeError('fixture did not exercise selected cached inter CUs')
 (a.output/'summary.json').write_text(json.dumps({'baseline_encoder_sha256':sha(a.baseline) if a.baseline else None,'partial_fixture_sha256':sha(partial),'selected_cached_inter_cus':cache_count,'checks':'decode hashes, disabled bitstream and trace identity, deterministic repeat, final predictor pixel audit, invalid combined and repair modes, initial intra VTM identity, periodic intra controller bypass and inter resume, repaired zero-strength identity','source_sha256':sha(source),'encoder_sha256':sha(a.encoder),'decoder_sha256':sha(a.decoder),'config_sha256':sha(config),'stats_sha256':sha(stats),'model_I_sha256':sha(str(model)+'.I'),'model_P_sha256':sha(str(model)+'.P'),'runs':len(records)},indent=2))
if __name__=='__main__':main()
