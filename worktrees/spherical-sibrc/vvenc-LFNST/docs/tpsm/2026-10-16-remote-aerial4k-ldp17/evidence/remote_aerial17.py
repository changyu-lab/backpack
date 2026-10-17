"""Frozen-revision AerialCity remote experiment; run sequentially to bound storage."""
import sys,json,hashlib,subprocess,time,gzip,os,shutil
from pathlib import Path
BASE=Path('/root/spherical_sibrc_20261016_aerial4k_ldp17')
SRC=BASE/'src';sys.path.insert(0,str(SRC/'tools/tpsm'))
from quality import measure,bd_rate,KEYS
from screen import prefix_sha
EXE=SRC/'bin/release-static/vvencFFapp'
DEC=Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/umake/gcc-11.4/x86_64/release/DecoderApp')
MET=Path('/data/vtmrc-vvenc-tune-20261014/metrics-build/metrics360')
SPHERE=Path('/root/VTM-23.0-paper-scc-rc-anchor-fit/cfg-360Lib/360Lib/sphere_655362.txt')
SOURCE=Path('/data/360seqFull_17f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv')
OLD=Path('/data/vtmrc-vvenc-tune-20261014/baseline/AerialCity')
OUT=BASE/'results';OUT.mkdir(exist_ok=True)
TEMP=Path('/dev/shm/spherical_sibrc_aerial4k_ldp17');TEMP.mkdir(exist_ok=True)
CFG=SRC/'docs/vtm23-rc/aerialcity16_ldp.cfg';STATS=SRC/'docs/sibrc/calibration-v1/stats.txt';MODEL=SRC/'docs/sibrc/calibration-v1/model'
def save(p,obj):p.write_text(json.dumps(obj,indent=2))
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for v in iter(lambda:f.read(1048576),b''):h.update(v)
 return h.hexdigest()
def run(cmd,log):
 with log.open('w') as f:subprocess.run([str(x) for x in cmd],stdout=f,stderr=subprocess.STDOUT,check=True)
def main():
 os.environ['SIBRC_METRIC_WORKERS']='2'
 historical=[];runs=[]
 for i in range(1,5):
  r=json.loads((OLD/f'rc17_anchor_R{i}.run.json').read_text());q=json.loads((OLD/f'rc17_anchor_R{i}.quality.json').read_text())
  assert r['frames']==17 and r['width']==3840 and r['height']==1920 and r['window_start']==0
  assert q['frames']==17 and q['cpp_dimensions']==[3840,1920]
  assert CFG.name and sha(CFG) in r['asset_hashes'].values()
  historical.append(q);runs.append(r)
 source_hash=prefix_sha(SOURCE,3840*1920*3//2*17)
 assert all(q['source_prefix_sha256']==source_hash for q in historical),'source prefix mismatch'
 paths=[EXE,DEC,MET,SPHERE,CFG,STATS,Path(str(MODEL)+'.I'),Path(str(MODEL)+'.P'),BASE/'source-36c604e8.tar.gz',BASE/'remote_aerial17.py']
 save(BASE/'protocol.json',{'revision':'36c604e8','source':str(SOURCE),'source_prefix_sha256':source_hash,'frames':17,'width':3840,'height':1920,'fps':30,'coding':'LDP','preset':'faster','targets_bps':[r['target_bps'] for r in runs],'target_origin':'existing historical 300-frame CQP targets, reused unchanged for 17 frames','historical_anchor':str(OLD),'strength':4,'bias_repair':True,'intra_anchor':True,'model':'v1','offset':[-2,2],'assets':{str(p):sha(p) for p in paths},'linux_build':{'type':'Release','jobs':4,'LTO':False,'CXX_FLAGS':'-Wno-error=misleading-indentation','reason':'frozen Windows-tested source contains single-line clauses; keep warnings while allowing Linux build, no algorithm source edits'},'storage':'sequential encode/decode/metric; temporary reconstruction in /dev/shm; own temporary recon deleted only after quality and hash checks'})
 curves={};identity=[]
 for method in ['anchor','paper_ad','sibrc','joint']:
  curve=[]
  for i,r in enumerate(runs,1):
   if (BASE/'STOP').exists():raise RuntimeError('STOP requested between jobs')
   stem=OUT/f'{method}_R{i}';rec=TEMP/f'{method}_R{i}.yuv';dec=TEMP/f'{method}_R{i}.decoded.yuv'
   done=Path(str(stem)+'.quality.json')
   if done.exists():
    q=json.loads(done.read_text());curve.append(q)
    if method=='anchor':identity.append(q['historical_bitstream_identity'])
    continue
   cmd=r['command'].copy();cmd[0]=str(EXE)
   for key,value in [('-c',CFG),('-i',SOURCE),('-b',str(stem)+'.vvc')]:cmd[cmd.index(key)+1]=str(value)
   cmd=[('--VTMRCTrace='+str(stem)+'.vtm.csv') if x.startswith('--VTMRCTrace=') else x for x in cmd]
   cmd+=['-o',str(rec)]
   if method in ['sibrc','joint']:cmd+=['--SIBRCMode=3','--SIBRCBiasRepair=1','--SIBRCIntraAnchor=1','--SIBRCStats='+str(STATS),'--SIBRCModel='+str(MODEL),'--SIBRCTrace='+str(stem)+'.sibrc.csv']
   if method in ['paper_ad','joint']:cmd+=['--TPSMMode='+str(1 if method=='paper_ad' else 2),'--TPSMChain=0','--TPSMTrace='+str(stem)+'.tpsm.csv']
   if method=='joint':cmd+=['--TPSMStrength=4']
   start=time.time();run(cmd,Path(str(stem)+'.log'));elapsed=time.time()-start
   assert rec.stat().st_size==3840*1920*3*17
   dc=[DEC,'-b',str(stem)+'.vvc','-o',dec,'--OutputBitDepth=10'];run(dc,Path(str(stem)+'.decode.log'))
   assert sha(rec)==sha(dec),'decoder reconstruction mismatch'
   bit_hash=sha(str(stem)+'.vvc');same=bit_hash==historical[i-1]['bitstream_sha256']
   if method=='anchor' and same:
    q=historical[i-1].copy();q['quality_origin']='reused historical anchor after exact bitstream and source prefix identity';identity.append(True)
    assert q['reconstruction_prefix_sha256']==sha(rec)
   else:
    q=measure(SOURCE,rec,3840,1920,17,str(stem)+'.vvc',30,MET,SPHERE)
    q['quality_origin']='measured current remote reconstruction'
    if method=='anchor':identity.append(False)
   q.update(actual_bps=Path(str(stem)+'.vvc').stat().st_size*8*30/17,target_bps=r['target_bps'],rate_error_percent=100*(Path(str(stem)+'.vvc').stat().st_size*8*30/17/r['target_bps']-1),historical_bitstream_identity=same if method=='anchor' else None,bitstream_sha256=bit_hash,encode_elapsed_seconds=elapsed)
   save(Path(str(stem)+'.run.json'),{'command':cmd,'decoder_command':[str(x) for x in dc],'encode_elapsed_seconds':elapsed,'reconstruction_sha256':sha(rec),'decoder_reconstruction_sha256':sha(dec),'returncode':0})
   save(done,q);curve.append(q)
   # Remove only verified reconstructions produced by this runner, within its own tmp directory.
   assert rec.parent==TEMP and dec.parent==TEMP
   rec.unlink();dec.unlink()
   for p in OUT.glob(stem.name+'.*.csv'):
    raw=p.read_bytes();z=Path(str(p)+'.gz');z.write_bytes(gzip.compress(raw,mtime=0));assert gzip.decompress(z.read_bytes())==raw;p.unlink()
   print(method,i,round(q['actual_bps']),{k:round(q[k],5) for k in KEYS},flush=True)
   save(BASE/'progress.json',{'method':method,'point':i,'completed_points':sum(len(v) for v in curves.values())+len(curve)})
  curves[method]=curve;save(BASE/'curves.json',curves)
  results={}
  for ref in curves:
   for candidate in curves:
    if candidate==ref:continue
    v={}
    for k in KEYS:
     try:v[k]=bd_rate([q[k] for q in curves[ref]],[q['actual_bps'] for q in curves[ref]],[q[k] for q in curves[candidate]],[q['actual_bps'] for q in curves[candidate]])
     except ValueError as e:v[k]={'unavailable':str(e)}
    results[candidate+'_vs_'+ref]=v
  save(BASE/'bd_rates.json',results)
 save(BASE/'completed.json',{'state':'complete','points':16,'historical_anchor_bitstream_identity':identity,'all_decodes_hash_verified':True,'all_17_frames':True,'results':'bd_rates.json','rate_errors_percent':{k:[q['rate_error_percent'] for q in v] for k,v in curves.items()}})
if __name__=='__main__':
 try:main()
 except Exception as e:
  save(BASE/'failure.json',{'error':repr(e),'time':time.time()});raise

