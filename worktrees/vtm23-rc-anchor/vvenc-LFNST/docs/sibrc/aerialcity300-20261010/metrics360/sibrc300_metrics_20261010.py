import sys,json,subprocess,time,hashlib,re,csv,shutil,ctypes,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
ROOT=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST')
sys.path.insert(0,str(ROOT/'tools/sibrc'))
from evaluate import quality,bd_rate
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010')
OUT=D/'metrics360';OUT.mkdir(exist_ok=True)
TMP=ROOT/'build-vtmrc/sibrc300-decoder-temp'
TMP_I=Path('I:/vvenc-LFNST/.worktrees/sibrc300-decoder-temp')
ACTIVE={}
DEC=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe')
EXE=Path('I:/vvenc-LFNST/.worktrees/metrics360-corrected/Release/metrics360.exe')
SCALAR=Path('I:/vvenc-LFNST/.worktrees/metrics360-fast/Release/metrics360.exe')
SPHERE=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/cfg-360Lib/360Lib/sphere_655362.txt')
SOURCE=ROOT/'build-vtmrc/metric-source-cache/AerialCity_3840x1920_30fps_8bit_420_erp.yuv'
SIZE=3840*1920*3*300
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,q):p.write_text(json.dumps(q,indent=2),encoding='utf8')
def process(r):
 name=r['name'];dest=OUT/(name+'.json')
 exe=EXE
 if dest.exists():
  q=json.loads(dest.read_text());assert q['metrics360_exe_sha256']==sha(exe);return q
 rec=TMP/(name+'.yuv')
 old=json.loads((D/(name+'.quality.json')).read_text());assert sha(D/(name+'.vvc'))==old['bitstream_sha256']
 start=time.perf_counter();cmd=[str(DEC),'-b',str(D/(name+'.vvc')),'-o',str(rec)]
 print('START',name,flush=True)
 if not rec.exists():
  with (OUT/(name+'.decode.log')).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
 assert rec.stat().st_size==SIZE
 native=OUT/(name+'.native.json')
 provenance=OUT/(name+'.native.provenance.json')
 expected={'mode':'legacy-cpp-only' if name.endswith('_R1') else 'all','exe_sha256':sha(SCALAR if name.endswith('_R1') else exe),'sphere_sha256':sha(SPHERE),'source_prefix_sha256':old['source_prefix_sha256'],'reconstruction_sha256':old['reconstruction_prefix_sha256'],'bitstream_sha256':old['bitstream_sha256'],'frames':300,'dimensions':[3840,1920]}
 if native.exists():
  cache=json.loads(native.read_text());assert len(cache['picture_y_spsnr'])==len(cache['picture_y_cpppsnr'])==300
  if provenance.exists():assert json.loads(provenance.read_text())==dict(expected,output_sha256=sha(native))
  else:
   assert name.endswith('_R1') and 'RECOVERED '+name in (D/'metrics360_recovery.log').read_text()
   manifest=json.loads((OUT/'protocol.json').read_text());assert sha(SCALAR)==manifest['source_assets_sha256'][str(SCALAR)]
   save(provenance,dict(expected,output_sha256=sha(native)))
 elif name in ACTIVE:
  kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=ctypes.c_void_p;kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
  handle=kernel.OpenProcess(0x100000,False,ACTIVE[name])
  if handle:
   while kernel.WaitForSingleObject(handle,1000)==258:pass
   kernel.CloseHandle(handle)
  assert native.exists()
 else:
  with (OUT/(name+'.metrics.log')).open('w') as log:subprocess.run([str(exe),str(SOURCE),str(rec),'3840','1920','300',str(SPHERE),str(native),*([] if name.endswith('_R1') else ['3'])],stdout=log,stderr=subprocess.STDOUT,check=True)
  save(provenance,dict(expected,output_sha256=sha(native)))
 corrected=None
 if name.endswith('_R1'):
  corrected=OUT/(name+'.spsnr_corrected.json');corrected_provenance=OUT/(name+'.spsnr_corrected.provenance.json');s_expected=dict(expected,exe_sha256=sha(exe),mode='s-only')
  if corrected.exists():assert json.loads(corrected_provenance.read_text())==dict(s_expected,output_sha256=sha(corrected))
  else:
   with (OUT/(name+'.spsnr_corrected.log')).open('w') as log:subprocess.run([str(exe),str(SOURCE),str(rec),'3840','1920','300',str(SPHERE),str(corrected),'3','s-only'],stdout=log,stderr=subprocess.STDOUT,check=True)
   save(corrected_provenance,dict(s_expected,output_sha256=sha(corrected)))
  sample=OUT/(name+'.cpp_spot_validation.json')
  with tempfile.TemporaryDirectory(prefix='cpp-validation-',dir=str(TMP)) as td:
   t=Path(td);indices=[0,150,299];frame_bytes=3840*1920*3//2
   with SOURCE.open('rb') as src,rec.open('rb') as recon,(t/'source.yuv').open('wb') as so,(t/'recon.yuv').open('wb') as ro:
    for index in indices:
     src.seek(index*frame_bytes);recon.seek(index*frame_bytes*2);sb=src.read(frame_bytes);rb=recon.read(frame_bytes*2);assert len(sb)==frame_bytes and len(rb)==frame_bytes*2;so.write(sb);ro.write(rb)
   with (OUT/(name+'.cpp_spot_validation.log')).open('w') as log:subprocess.run([str(exe),str(t/'source.yuv'),str(t/'recon.yuv'),'3840','1920','3',str(SPHERE),str(sample),'3'],stdout=log,stderr=subprocess.STDOUT,check=True)
  sample_q=json.loads(sample.read_text());old_cpp=json.loads(native.read_text())['picture_y_cpppsnr'];assert sample_q['picture_y_cpppsnr']==[old_cpp[index] for index in indices]
 q=quality(SOURCE,rec,3840,1920,300,spherical=False)
 assert q['reconstruction_prefix_sha256']==old['reconstruction_prefix_sha256']
 assert q['source_prefix_sha256']==old['source_prefix_sha256']
 assert q['picture_y_wspsnr']==old['picture_y_wspsnr'] and q['picture_y_psnr']==old['picture_y_psnr']
 q.update(json.loads(native.read_text()))
 if corrected:
  verified=json.loads(corrected.read_text());assert len(verified['picture_y_spsnr'])==300
  q['spsnr_revalidation_max_abs_difference']=float(np.max(np.abs(np.asarray(q['picture_y_spsnr'])-verified['picture_y_spsnr'])))
  q['cpp_revalidation_samples']=[0,150,299];q['cpp_revalidation_max_abs_difference']=0.0
  q.update(verified)
 for k in ('spsnr','cpppsnr'):assert len(q['picture_y_'+k])==300;q['mean_y_'+k]=float(np.mean(q['picture_y_'+k]))
 text=(D/(name+'.log')).read_text(errors='replace')
 rows=re.findall(r'POC\s+(\d+).*?\)\s+(\d+) bits',text)
 assert [int(x) for x,y in rows]==list(range(300))
 bits=[int(y) for x,y in rows];q.update(name=name,target_bps=old['target_bps'],actual_bps=old['actual_bps'],picture_bits=bits,picture_bitrate_bps=[x*30 for x in bits],metrics360_exe_sha256=sha(exe),cpp_metrics360_exe_sha256=sha(SCALAR if name.endswith('_R1') else exe),native_json_sha256=sha(native),spsnr_json_sha256=sha(corrected if corrected else native),spsnr_geometry_explicitly_initialized=True,metric_workers=3,default_metrics=['WS-PSNR','S-PSNR-NN','CPP-PSNR'],sphere_sha256=sha(SPHERE),bitstream_sha256=old['bitstream_sha256'],reconstruction_hash_matches_previous=True,elapsed_seconds=time.perf_counter()-start,frame_bit_definition='encoder POC bits times 30 fps; sequence bitrate uses complete Annex-B stream',annexb_minus_picture_bits=(D/(name+'.vvc')).stat().st_size*8-sum(bits))
 save(dest,q)
 assert rec.resolve().parent in (TMP.resolve(),TMP_I.resolve());rec.unlink()
 print('DONE',name,q['mean_y_spsnr'],q['mean_y_cpppsnr'],flush=True);return q
if __name__=='__main__':
 TMP.mkdir(exist_ok=True,parents=True);TMP_I.mkdir(exist_ok=True,parents=True)
 records=json.loads((D/'rc_results.json').read_text());points=[]
 assert all(p.name in {r['name']+'.yuv' for r in records} and p.stat().st_size==SIZE for p in TMP.iterdir())
 assert shutil.disk_usage(TMP).free+sum(p.stat().st_size for p in TMP.iterdir())>2*SIZE+1_500_000_000
 with ThreadPoolExecutor(max_workers=2) as pool:
  jobs=[pool.submit(process,r) for r in records]
  for job in as_completed(jobs):points.append(job.result());save(OUT/'progress.json',points)
 a=sorted([q for q in points if '_anchor_' in q['name']],key=lambda q:q['target_bps']);b=sorted([q for q in points if '_full_' in q['name']],key=lambda q:q['target_bps'])
 report={'points':a+b,'metrics':['WS-PSNR','S-PSNR-NN','CPP-PSNR'],'scope':'luma; mean of per-picture dB; 300 frames; 8-bit reference/10-bit reconstruction; official 360Lib S/CPP, 655362 spherical samples; CPP 3840x1920 Lanczos3/luma and Lanczos2/chroma','bd_rate_percent':{k:bd_rate([q['mean_y_'+k] for q in a],[q['actual_bps'] for q in a],[q['mean_y_'+k] for q in b],[q['actual_bps'] for q in b]) for k in ('wspsnr','spsnr','cpppsnr','psnr')}}
 save(OUT/'assessment.json',report)
 with (OUT/'frames.csv').open('w',newline='') as f:
  wr=csv.writer(f);wr.writerow(['method','target_bps','poc','bits','bitrate_bps','wspsnr','spsnr','cpppsnr','psnr'])
  for q in a+b:
   for k in range(300):wr.writerow(['Anchor' if '_anchor_' in q['name'] else 'SIBRC',q['target_bps'],k,q['picture_bits'][k],q['picture_bitrate_bps'][k]]+[q['picture_y_'+m][k] for m in ('wspsnr','spsnr','cpppsnr','psnr')])
 print('COMPLETE',report['bd_rate_percent'],flush=True)
