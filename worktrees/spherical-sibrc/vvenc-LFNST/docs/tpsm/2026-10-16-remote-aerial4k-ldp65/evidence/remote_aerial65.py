"""Frozen TPSM/SIBRC comparison: LDP GOP16, 65 frames, targets from 300-frame CQP logs."""
import sys,json,hashlib,subprocess,time,gzip,os,re,shutil
from decimal import Decimal,ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
BASE=Path('/root/spherical_sibrc_20261016_aerial4k_ldp65')
PREV=Path('/root/spherical_sibrc_20261016_aerial4k_ldp17');SRC=PREV/'src'
sys.path.insert(0,str(SRC/'tools/tpsm'))
from quality import measure,bd_rate,KEYS
from screen import prefix_sha
EXE=SRC/'bin/release-static/vvencFFapp'
OLD=Path('/root/sibrc-ldp16-300-20261015');INPUT=Path('/dev/shm/sibrc-ldp16-300-input-20261015/AerialCity_3840x1920_30fps_8bit_420_erp.yuv')
DEC=Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/umake/gcc-11.4/x86_64/release/DecoderApp')
MET=Path('/data/vtmrc-vvenc-tune-20261014/metrics-build/metrics360');SPHERE=Path('/root/VTM-23.0-paper-scc-rc-anchor-fit/cfg-360Lib/360Lib/sphere_655362.txt')
CFG=BASE/'ldp16.cfg';STATS=SRC/'docs/sibrc/calibration-v1/stats.txt';MODEL=SRC/'docs/sibrc/calibration-v1/model'
OUT=BASE/'results';TEMP=Path('/dev/shm/spherical_sibrc_aerial4k_ldp65');N=65
METHODS=['anchor','paper_ad','sibrc','joint'];SUMMARY=re.compile(r'^vvenc \[info\]:\s+(\d+)\s+a\s+([0-9.]+)\s+',re.M)
def save(p,x):
 t=Path(str(p)+'.tmp');t.write_text(json.dumps(x,indent=2));t.replace(p)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def run(cmd,log):
 with log.open('w') as f:subprocess.run([str(x) for x in cmd],stdout=f,stderr=subprocess.STDOUT,check=True)
def trace_zip(stem):
 for p in OUT.glob(stem.name+'.*.csv'):
  raw=p.read_bytes();z=Path(str(p)+'.gz');z.write_bytes(gzip.compress(raw,mtime=0));assert gzip.decompress(z.read_bytes())==raw;p.unlink()
def prepare():
 OUT.mkdir(exist_ok=True);TEMP.mkdir(exist_ok=True);reference=BASE/'reference300';reference.mkdir(exist_ok=True)
 shutil.copyfile(OLD/'ldp16.cfg',CFG);assert re.search(r'^GOPSize:\s*16\s*$',CFG.read_text(),re.M)
 oldspec=json.loads((OLD/'AerialCity-targets.json').read_text());assert prefix_sha(INPUT,3840*1920*3//2*300)==oldspec['source_prefix_sha256']
 rows=[];commands=[]
 for i in range(1,5):
  p=OLD/'runs/AerialCity/cqp'/f'R{i}.log';text=p.read_text();matches=SUMMARY.findall(text);assert len(matches)==1 and int(matches[0][0])==300
  target=int((Decimal(matches[0][1])*1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
  meta=json.loads(p.with_suffix('.run.json').read_text());assert meta['returncode']==0 and meta['pocs']==list(range(300));assert meta['spec']['source_prefix_sha256']==oldspec['source_prefix_sha256'];assert meta['command'][meta['command'].index('-f')+1]=='300'
  qp=int(next(x.split('=')[1] for x in meta['command'] if x.startswith('--QP=')))
  rows.append({'point':i,'qp':qp,'frames':300,'log_kbps':matches[0][1],'target_bps':target,'log':str(p),'log_sha256':sha(p),'cqp_bitstream_sha256':meta['outputs_sha256'][str(p.with_suffix('.vvc'))]})
  shutil.copyfile(p,reference/p.name);shutil.copyfile(p.with_suffix('.run.json'),reference/p.with_suffix('.run.json').name)
  anchor=json.loads((OLD/'runs/AerialCity/anchor'/f'R{i}.run.json').read_text());cmd=anchor['command'].copy();assert int(next(x.split('=')[1] for x in cmd if x.startswith('--VTMTargetBitrate=')))==target
  commands.append(cmd)
 assert [r['qp'] for r in rows]==[37,32,27,22]
 previous=json.loads((PREV/'protocol.json').read_text());assert sha(EXE)==previous['assets'][str(EXE)]
 assets=[EXE,DEC,MET,SPHERE,CFG,STATS,Path(str(MODEL)+'.I'),Path(str(MODEL)+'.P'),BASE/'remote_aerial65.py']
 protocol={'algorithm_revision':'36c604e8','source':str(INPUT),'source_prefix_65_sha256':prefix_sha(INPUT,3840*1920*3//2*N),'source_prefix_300_sha256':oldspec['source_prefix_sha256'],'width':3840,'height':1920,'fps':30,'frames':N,'coding':'LDP','GOPSize':16,'preset':'faster','targets_from_300_cqp_logs':rows,'rounding':'decimal kbps times1000, round half up to integer bps','methods':METHODS,'temporal_strength_joint':4,'bias_repair':True,'intra_anchor':True,'qp_bounds':[-2,2],'model':'unchanged v1 I/P','parallel_jobs':3,'metric_workers_per_job':2,'assets':{str(p):sha(p) for p in assets},'anchor_policy':'fresh 65-frame anchor at the same frozen targets; R2 also compared with the existing historical encoder','previous_17_frame_protocol':str(PREV/'protocol.json')}
 save(BASE/'protocol.json',protocol);print('FROZEN_TARGETS',[r['target_bps'] for r in rows],flush=True)
 return rows,commands,protocol

def case(method,i,oldcmd,target):
 if (BASE/'STOP').exists():raise RuntimeError('STOP requested between jobs')
 stem=OUT/f'{method}_R{i}';rec=TEMP/f'{method}_R{i}.yuv';dec=TEMP/f'{method}_R{i}.decoded.yuv';done=Path(str(stem)+'.quality.json')
 if done.exists():return json.loads(done.read_text())
 if shutil.disk_usage(BASE).free<150*1024**2:raise RuntimeError('Less than150MiB free persistent disk; do not delete other experiments')
 if shutil.disk_usage(TEMP).free<3*1024**3:raise RuntimeError('Insufficient own reconstruction scratch space')
 cmd=oldcmd.copy();oldexe=cmd[0];cmd[0]=str(EXE)
 for key,value in [('-c',CFG),('-i',INPUT),('-f',str(N)),('-b',str(stem)+'.vvc')]:cmd[cmd.index(key)+1]=str(value)
 cmd=[('--VTMRCTrace='+str(stem)+'.vtm.csv') if x.startswith('--VTMRCTrace=') else x for x in cmd];cmd+=['-o',str(rec)]
 if method in ['sibrc','joint']:cmd+=['--SIBRCMode=3','--SIBRCMinOffset=-2','--SIBRCMaxOffset=2','--SIBRCBiasRepair=1','--SIBRCIntraAnchor=1','--SIBRCStats='+str(STATS),'--SIBRCModel='+str(MODEL),'--SIBRCTrace='+str(stem)+'.sibrc.csv']
 if method in ['paper_ad','joint']:cmd+=['--TPSMMode='+str(1 if method=='paper_ad' else 2),'--TPSMChain=0','--TPSMTrace='+str(stem)+'.tpsm.csv']
 if method=='joint':cmd+=['--TPSMStrength=4']
 print('START',method,i,flush=True);start=time.time();run(cmd,Path(str(stem)+'.log'));elapsed=time.time()-start
 assert rec.stat().st_size==3840*1920*3*N
 dc=[DEC,'-b',str(stem)+'.vvc','-o',dec,'--OutputBitDepth=10'];run(dc,Path(str(stem)+'.decode.log'));assert sha(rec)==sha(dec)
 q=measure(INPUT,rec,3840,1920,N,str(stem)+'.vvc',30,MET,SPHERE);bit_hash=sha(str(stem)+'.vvc')
 record={'command':cmd,'decoder_command':[str(x) for x in dc],'encode_elapsed_seconds':elapsed,'reconstruction_sha256':sha(rec),'decoder_reconstruction_sha256':sha(dec),'returncode':0}
 if method=='anchor' and i==2:
  check=cmd.copy();check[0]=oldexe;check[check.index('-b')+1]=str(stem)+'.historical.vvc';j=check.index('-o');del check[j:j+2]
  check=[('--VTMRCTrace='+str(stem)+'.historical.vtm.csv') if x.startswith('--VTMRCTrace=') else x for x in check]
  run(check,Path(str(stem)+'.historical.log'));assert sha(str(stem)+'.historical.vvc')==bit_hash,'closed-path anchor identity failed'
  record['historical_encoder_check']={'command':check,'encoder_sha256':sha(Path(oldexe)),'bitstream_identity':True,'bitstream_sha256':bit_hash}
 q.update(target_bps=target,rate_error_percent=100*(q['actual_bps']/target-1),bitstream_sha256=bit_hash,encode_elapsed_seconds=elapsed)
 save(Path(str(stem)+'.run.json'),record);save(done,q)
 assert rec.parent==TEMP and dec.parent==TEMP;rec.unlink();dec.unlink();trace_zip(stem)
 print('DONE',method,i,round(q['actual_bps']),{k:round(q[k],5) for k in KEYS},flush=True);return q

def summaries(points):
 curves={m:[points[(m,i)] for i in range(1,5)] for m in METHODS if all((m,i) in points for i in range(1,5))}
 save(BASE/'curves.json',curves);results={}
 for ref in curves:
  for cand in curves:
   if ref==cand:continue
   values={}
   for k in KEYS:
    try:values[k]=bd_rate([q[k] for q in curves[ref]],[q['actual_bps'] for q in curves[ref]],[q[k] for q in curves[cand]],[q['actual_bps'] for q in curves[cand]])
    except ValueError as e:values[k]={'unavailable':str(e)}
   results[cand+'_vs_'+ref]=values
 save(BASE/'bd_rates.json',results);return curves

def main():
 os.environ['SIBRC_METRIC_WORKERS']='2';targets,commands,protocol=prepare();points={}
 with ThreadPoolExecutor(max_workers=3) as pool:
  jobs={pool.submit(case,m,i,commands[i-1],targets[i-1]['target_bps']):(m,i) for m in METHODS for i in range(1,5)}
  for future in as_completed(jobs):
   m,i=jobs[future];points[(m,i)]=future.result();curves=summaries(points);save(BASE/'progress.json',{'completed_points':len(points),'total_points':16,'last_method':m,'last_point':i,'complete_methods':list(curves)})
 save(BASE/'completed.json',{'state':'complete','points':16,'frames':N,'GOPSize':16,'rate_errors_percent':{m:[q['rate_error_percent'] for q in v] for m,v in curves.items()}})
if __name__=='__main__':
 try:main()
 except Exception as e:save(BASE/'failure.json',{'error':repr(e),'time':time.time()});raise
