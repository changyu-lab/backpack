"""Frozen multi-resolution replication; checkpoints resume only verified completed jobs."""
import sys,json,hashlib,shutil,subprocess,re,time,csv,os,argparse
import psutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST')
sys.path.insert(0,str(ROOT/'tools/sibrc'))
import run_local as runner
from evaluate import quality,bd_rate
BASE=Path('I:/vvenc-LFNST/.worktrees/sibrc-three-300-20261010')
CACHE=Path('D:/SIBRC-cache-20261010')
OLD=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010')
DEC=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe')
PY='F:/Anaconda/python.exe';FRAMES=300;QPS=(37,32,27,22)
SEQUENCES=[('PoleVault','PoleVault_le_3840x1920_30fps_8bit_420_erp.yuv',3840,1920,4,3),('BranCastle2','BranCastle2_6144x3072_30fps_8bit_420_erp.yuv',6144,3072,2,2),('DrivingInCity','DrivingInCity_3840x1920_30fps_8bit_420_erp.yuv',3840,1920,4,3)]
def save(p,q):
 p=Path(p);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(q,indent=2),encoding='utf8');tmp.replace(p)
def sha(p,limit=None):return runner.sha(p,limit)
def frozen_assets():
 BASE.mkdir(exist_ok=True);CACHE.mkdir(exist_ok=True)
 for original,name in [(OLD/'encoder-frozen.exe','encoder-frozen.exe'),(runner.CFG,'ldp.cfg'),(OLD/'model.I','model.I'),(OLD/'model.P','model.P'),(OLD/'stats.txt','stats.txt')]:
  dest=BASE/name
  if not dest.exists():shutil.copyfile(original,dest)
  assert sha(dest)==sha(original),'frozen asset changed '+name
 return {str(BASE/name):sha(BASE/name) for name in ('encoder-frozen.exe','ldp.cfg','model.I','model.P','stats.txt')}
def make_job(d,seq,source,w,h,name,frames,rate=0,mode=0,cqp=None):
 runner.DATA=d;runner.EXE=BASE/'encoder-frozen.exe';runner.CFG=BASE/'ldp.cfg';runner.SOURCES[seq]=source
 j=runner.job(name,seq,frames,rate,mode,recon=False,cqp=cqp)
 j['command'][j['command'].index('-s')+1]=str(w)+'x'+str(h)
 j['command']=[x.replace(str(d/'stats.txt'),str(BASE/'stats.txt')).replace(str(d/'model'),str(BASE/'model')) for x in j['command']]
 j['assets']=[str(BASE/Path(x).name) if Path(x).name in ('stats.txt','model.I','model.P') else x for x in j['assets']]
 j['width']=w;j['height']=h
 return j
def execute(j,proto):
 record=Path(j['log']).with_suffix('.run.json')
 if record.exists():
  r=json.loads(record.read_text());assert r['verified'] and r['command']==j['command']
  assert all(sha(p)==v for p,v in r['outputs_sha256'].items())
  return r
 assert not any(Path(x).exists() for x in j['outputs']),'partial output requires inspection '+j['name']
 for p in j['assets']:assert sha(p)==proto['assets'][p]
 print('START',j['source_sequence'],j['name'],flush=True)
 start=time.perf_counter()
 peak=0
 with Path(j['log']).open('w') as log:
  process=subprocess.Popen(j['command'],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
  while process.poll() is None:
   try:peak=max(peak,psutil.Process(process.pid).memory_info().rss)
   except psutil.NoSuchProcess:pass
   time.sleep(0.5)
  code=process.returncode
 text=Path(j['log']).read_text(errors='replace');pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))))
 r=dict(j,returncode=code,elapsed_seconds=time.perf_counter()-start,peak_rss_bytes=peak,pocs=pocs,raw_input=proto['source'],asset_hashes={p:proto['assets'][p] for p in j['assets']})
 r['verified']=code==0 and pocs==list(range(j['frames'])) and 'Total Time:' in text and all(Path(p).is_file() for p in j['outputs'])
 r['outputs_sha256']={p:sha(p) for p in j['outputs'] if Path(p).exists()}
 r['actual_bps']=Path(j['outputs'][0]).stat().st_size*8*30/j['frames'] if Path(j['outputs'][0]).exists() else 0
 save(record,r)
 assert r['verified'],j['name']+' failed '+text[-1500:]
 print('PASS',j['source_sequence'],j['name'],round(r['elapsed_seconds'],1),r['actual_bps'],flush=True)
 return r
def decode_metrics(d,r,source,w,h,workers,frames=300,pilot=False):
 name=r['name'];dest=d/(name+'.quality.json')
 rec=CACHE/(d.name+'-'+name+'.yuv');expected=w*h*3*frames
 if dest.exists():
  q=json.loads(dest.read_text());assert q['bitstream_sha256']==sha(d/(name+'.vvc'))
  assert q['decoder_sha256']==sha(DEC)
  metric_exe=Path(os.environ.get('SIBRC_METRICS360_EXE',str(ROOT/'build-vtmrc/metrics360-parallel/Release/metrics360.exe')))
  sphere=Path(os.environ.get('SIBRC_SPHERE_FILE','I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/cfg-360Lib/360Lib/sphere_655362.txt'))
  assert q['metrics360_exe_sha256']==sha(metric_exe) and q['sphere_sha256']==sha(sphere)
  assert q['source_prefix_sha256']==sha(source,w*h*3//2*frames)
  assert q['frames']==frames and q['width']==w and q['height']==h
  assert q['cpp_dimensions']==[w,h] and q['metric_peak_10bit']==1020
  if rec.exists():
   assert rec.stat().st_size==expected and sha(rec)==q['reconstruction_prefix_sha256']
   assert rec.resolve().parent==CACHE.resolve();rec.unlink()
  return q
 assert not rec.exists(),'partial reconstruction requires inspection '+str(rec)
 assert shutil.disk_usage(CACHE).free>expected+3_000_000_000
 print('DECODE',d.name,name,flush=True)
 with (d/(name+'.decode.log')).open('w') as log:subprocess.run([str(DEC),'-b',str(d/(name+'.vvc')),'-o',str(rec)],stdout=log,stderr=subprocess.STDOUT,check=True)
 assert rec.stat().st_size==expected
 os.environ['SIBRC_METRIC_WORKERS']=str(workers)
 q=quality(source,rec,w,h,frames)
 assert q['source_prefix_sha256']==sha(source,w*h*3//2*frames)
 text=Path(r['log']).read_text(errors='replace');rows=re.findall(r'POC\s+(\d+).*?\)\s+(\d+) bits',text)
 assert [int(p) for p,b in rows]==list(range(frames))
 bits=[int(b) for p,b in rows];assert sum(bits)==(d/(name+'.vvc')).stat().st_size*8
 q.update(name=name,target_bps=r['target_bps'],actual_bps=r['actual_bps'],picture_bits=bits,picture_bitrate_bps=[b*30 for b in bits],bitstream_sha256=sha(d/(name+'.vvc')),decoder_sha256=sha(DEC),annexb_minus_picture_bits=0,width=w,height=h,encoder_elapsed_seconds=r['elapsed_seconds'],source_sequence=d.name)
 if r['target_bps']:q['rate_error_percent']=100*(q['actual_bps']/r['target_bps']-1)
 save(dest,q)
 assert rec.resolve().parent==CACHE.resolve();rec.unlink()
 print('QUALITY',d.name,name,{m:q['mean_y_'+m] for m in ('wspsnr','spsnr','cpppsnr')},flush=True)
 return q
def finish(d,seq,proto,points):
 a=sorted([q for q in points if '_anchor_' in q['name']],key=lambda q:q['target_bps']);b=sorted([q for q in points if '_full_' in q['name']],key=lambda q:q['target_bps'])
 assert len(a)==len(b)==4
 result={'sequence':seq,'protocol':proto,'points':a+b,'bd_rate_percent':{m:bd_rate([q['mean_y_'+m] for q in a],[q['actual_bps'] for q in a],[q['mean_y_'+m] for q in b],[q['actual_bps'] for q in b]) for m in ('wspsnr','spsnr','cpppsnr','psnr')}}
 save(d/'assessment.json',result)
 with (d/'frames.csv').open('w',newline='') as f:
  out=csv.writer(f);out.writerow(['method','target_bps','poc','bits','bitrate_bps','wspsnr','spsnr','cpppsnr','psnr'])
  for q in a+b:
   for k in range(300):out.writerow(['Anchor' if '_anchor_' in q['name'] else 'SIBRC',q['target_bps'],k,q['picture_bits'][k],q['picture_bitrate_bps'][k]]+[q['picture_y_'+m][k] for m in ('wspsnr','spsnr','cpppsnr','psnr')])
 lines=['# '+seq+' ERP 300-frame results','','Native resolution, LDP, frozen faster encoder and SIBRC models. Source8/reconstruction10. WS/S-NN/CPP luma means of per-frame dB; actual Annex-B bitrate and common-range PCHIP BD-rate.','','|Metric|BD-rate|','|---|---:|']
 for m in ('wspsnr','spsnr','cpppsnr','psnr'):lines.append('|'+m+'|%+.4f%%|'%result['bd_rate_percent'][m])
 lines+=['','Timing is elapsed wall time under concurrent jobs, not an isolated encoding-speed benchmark.','Model development sequences: DrivingInCity/DrivingInCountry. DrivingInCity is a development sequence; PoleVault/BranCastle2 are held out.','S-PSNR is the NN variant with 655362 original 360Lib sphere samples. CPP dimensions equal native source resolution; Lanczos3 luma/Lanczos2 chroma, peak1020 at10bits.','Frames.csv contains all2400rows. Figures use Anchor/SIBRC, S-PSNR (dB), transparent backgrounds and inward ticks on all four sides.']
 (d/'report.md').write_text('\n'.join(lines)+'\n')
 plot=Path('I:/vvenc-LFNST/.worktrees/plot_compact_sibrc_panels.py')
 subprocess.run([PY,str(plot),str(d/'assessment.json'),'--sequence-label',seq,'--output-dir',str(d/'panels')],check=True)
 archive=ROOT/'docs/sibrc/three-sequence300-20261010'/seq;archive.mkdir(parents=True,exist_ok=True)
 for p in d.iterdir():
  if p.is_file() and p.suffix in ('.json','.md') or p.name=='frames.csv':shutil.copyfile(p,archive/p.name)
 shutil.copytree(d/'panels',archive/'panels',dirs_exist_ok=True)
 print('COMPLETE SEQUENCE',seq,result['bd_rate_percent'],flush=True)
def sequence(spec,assets,pilot_only=False):
 seq,filename,w,h,encworkers,metricworkers=spec;d=BASE/seq;d.mkdir(exist_ok=True)
 original=Path('I:/Sequences360')/filename;source=CACHE/filename;needed=w*h*3//2*300
 assert original.stat().st_size>=needed
 protocol=d/'protocol.json'
 if protocol.exists():
  proto=json.loads(protocol.read_text());assert proto['assets']==assets
  assert source.exists() and sha(source,needed)==proto['source']['coded_prefix_sha256']
 else:
  print('CACHE SOURCE',seq,flush=True)
  # Hash original while copying once; repeated HDD scans dominate 6K/8K setup.
  pending=source.with_suffix(source.suffix+'.copying')
  assert pending.resolve().parent==CACHE.resolve() and source.resolve().parent==CACHE.resolve()
  before=original.stat();digest=hashlib.sha256();position=0
  with original.open('rb') as src,pending.open('wb') as out:
   for block in iter(lambda:src.read(8*1024*1024),b''):
    out.write(block);take=max(0,min(len(block),needed-position))
    digest.update(block[:take]);position+=len(block)
  after=original.stat();assert before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns
  assert position==before.st_size
  hsrc=digest.hexdigest();assert sha(pending,needed)==hsrc
  pending.replace(source)
  proto={'sequence':seq,'width':w,'height':h,'fps':30,'frames':300,'qps':QPS,'encoder_workers':encworkers,'metric_workers':metricworkers,'source':{'path':str(original),'cache':str(source),'file_bytes':original.stat().st_size,'coded_prefix_sha256':hsrc},'assets':assets,'preset':'faster','configuration':'LDP GOP8, sequential CTU feedback, QPA/native RC/WPP/tile/frame parallelism off','model_development':['DrivingInCity','DrivingInCountry'],'retuning':False,'targets':'rounded actual 300-frame CQP37/32/27/22 Annex-B bps','default_metrics':['WS-PSNR','S-PSNR-NN','CPP-PSNR'],'evaluation':'original360Lib S/CPP, native dimensions, mean per-frame dB, actual-rate PCHIP common-range BD-rate'}
  save(protocol,proto)
 pilot=make_job(d,seq,source,w,h,'pilot8_CQP37',8,cqp=37);pr=execute(pilot,proto)
 smoke=make_job(d,seq,source,w,h,'pilot8_full',8,rate=int(round(pr['actual_bps'])),mode=3);sr=execute(smoke,proto)
 subprocess.run([PY,str(ROOT/'tools/sibrc/verify_intra_contract.py'),str(d/smoke['name']),'--output',str(d/'pilot.contract.json')],check=True)
 decode_metrics(d,sr,source,w,h,1,frames=8,pilot=True)
 if pilot_only:return
 peak=max(pr.get('peak_rss_bytes',0),sr.get('peak_rss_bytes',0))
 if peak:
  available=psutil.virtual_memory().available
  requested=encworkers;encworkers=max(1,min(requested,int(max(0,available-700_000_000)/(peak*1.4))))
  proto.update(encoder_workers_requested=requested,encoder_workers=encworkers,encoder_pilot_peak_rss=peak,available_memory_at_stage=available,memory_budget='700MB reserve; 1.4x observed short-pilot peak per process; at least one encoder')
  save(protocol,proto)
  print('RESOURCE LIMIT',seq,'workers',encworkers,'peak',peak,'available',available,flush=True)
 jobs=[make_job(d,seq,source,w,h,'cqp300_QP'+str(q),300,cqp=q) for q in reversed(QPS)];save(d/'cqp_jobs.json',jobs)
 with ThreadPoolExecutor(max_workers=encworkers) as pool:results=list(pool.map(lambda j:execute(j,proto),jobs))
 results.sort(key=lambda r:-int(r['name'].split('QP')[-1]));save(d/'cqp_results.json',results)
 targets=[int(round(r['actual_bps'])) for r in results];save(d/'targets.json',targets)
 jobs=[make_job(d,seq,source,w,h,'rc300_'+method+'_R'+str(i),300,rate,0 if method=='anchor' else 3) for i,rate in reversed(list(enumerate(targets,1))) for method in ('anchor','full')];save(d/'rc_jobs.json',jobs)
 with ThreadPoolExecutor(max_workers=encworkers) as pool:results=list(pool.map(lambda j:execute(j,proto),jobs))
 save(d/'rc_results.json',results);points=[]
 for r in results:
  if '_full_' in r['name']:subprocess.run([PY,str(ROOT/'tools/sibrc/verify_intra_contract.py'),str(d/r['name']),'--output',str(d/(r['name']+'.contract.json'))],check=True)
  points.append(decode_metrics(d,r,source,w,h,metricworkers));save(d/'quality_progress.json',points)
 finish(d,seq,proto,points)
def main():
 p=argparse.ArgumentParser();p.add_argument('--pilot-only',action='store_true');p.add_argument('--preflight-all',action='store_true');p.add_argument('--sequence',choices=[s[0] for s in SEQUENCES]);args=p.parse_args()
 assets=frozen_assets()
 if args.preflight_all:
  for spec in SEQUENCES:sequence(spec,assets,True)
 for spec in SEQUENCES:
  if args.sequence and spec[0]!=args.sequence:continue
  sequence(spec,assets,args.pilot_only)
 if args.pilot_only or args.sequence:return
 all_results={s[0]:json.loads((BASE/s[0]/'assessment.json').read_text())['bd_rate_percent'] for s in SEQUENCES}
 all_results['AerialCity']=json.loads((OLD/'metrics360/assessment.json').read_text())['bd_rate_percent']
 save(BASE/'aggregate.json',{'sequences':all_results,'mean_percent':{m:sum(q[m] for q in all_results.values())/4 for m in ('wspsnr','spsnr','cpppsnr','psnr')},'scope':'arithmetic mean of four completed sequence BD-rates'})
 archive=ROOT/'docs/sibrc/three-sequence300-20261010';archive.mkdir(exist_ok=True,parents=True)
 shutil.copyfile(BASE/'aggregate.json',archive/'aggregate.json')
 print('ALL COMPLETE',all_results,flush=True)
if __name__=='__main__':main()

