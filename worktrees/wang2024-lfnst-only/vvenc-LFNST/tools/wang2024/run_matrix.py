"""Wang2024 paired ERP matrix. Formal and transform timing are separate runs."""
import argparse,concurrent.futures,csv,hashlib,json,math,os,re,shutil,subprocess,sys,time
from pathlib import Path
from tools.wang2024.contract import jobs,frames,QPS,ADDITIONAL,runtime_env,command,timing_matches,completion_matches
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'results'
ENC=ROOT/'src/bin/release-static/vvencFFapp'
CONVERT=Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/360ConvertAppStatic')
SPHERE=Path('/data/ibrc_st_direct_wref/VTM-23.0/cfg-360Lib/360Lib/sphere_655362.txt')
SEQROOT=Path('/data/360seqFull_32f')
def save(p,data):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(data,indent=2));t.replace(p)
def load(p):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return None
def identity():
 files=[ENC,CONVERT,SPHERE,ROOT/'ldp.cfg',Path(__file__),ROOT/'tools/wang2024/contract.py']
 files += [ROOT/p for p in ('tools/lard_360_metrics.py','tools/lard_lfnst/official_360lib_metrics.py','tools/lard_lfnst/run_skip21_stage12_erp14_configs.py','tools/lard_lfnst/run_skip21_stage2_validation.py','tools/lard_lfnst/run_skip21_stage12_ra_360lib.py')]
 hashes={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
 return hashlib.sha256(json.dumps(dict(contract=plan(),hashes=hashes),sort_keys=True).encode()).hexdigest()
def sequences():
 result=[]
 for p in sorted(SEQROOT.glob('*.yuv')):
  m=re.fullmatch(r'(.+)_(\d+)x(\d+)_(\d+)fps_(\d+)bit_420_erp.yuv',p.name)
  if m:result.append(dict(name=m[1],path=str(p),width=int(m[2]),height=int(m[3]),fps=int(m[4]),bitdepth=int(m[5])))
 if len(result)!=14:raise RuntimeError('expected14 inputs, found '+str(len(result)))
 return result
def plan():
 seqs=sequences();j=jobs([s['name'] for s in seqs]);commands=[]
 for p,c,s in j:
  seq=next(x for x in seqs if x['name']==s)
  for q in QPS:
   for k in ('anchor','proposed'):
    folder=OUT/p/c/s/('QP'+str(q))/'repeat1'
    commands.append(dict(preset=p,config=c,sequence=s,qp=q,kind=k,mode=runtime_env(k,{})['WANG_LFNST_MODE'],command=command(ENC,seq,q,p,c,folder/(k+'.vvc'),folder/(k+'_rec.yuv'),ROOT/'ldp.cfg')))
 return dict(protocol='Wang2024-LFNST-only-equations1-4',jobs=j,frames={'AI':1,'RA':16,'LDP':16},repeats=1,threads=1,qps=list(QPS),commands=commands,total_formal_encodes=len(commands),qpstep='2^((codingQP-4)/6)',rec_cleanup='after all metrics saved',platform='Linux independent matched cohort; host shared with other experiments')
def child(preset,config,sequence):
 from tools.lard_lfnst import run_skip21_stage12_ra_360lib as runner
 from scipy.interpolate import PchipInterpolator
 target=OUT/preset/config/sequence
 run_identity=identity()
 runner.frames_for_config=lambda config,**kw:1 if config=='AI' else 16
 original_options=runner.encoder_config_options
 def options(config,**kw):
  v=original_options(config,**kw)
  if config=='LD':v+=['-c',str(ROOT/'ldp.cfg')]
  return v
 runner.encoder_config_options=options
 runner.PROFILES['Wang2024']=ADDITIONAL;runner.FORMAL_PROFILES.add('Wang2024')
 runner.proposed_additional_for_qp=lambda *a,**kw:ADDITIONAL
 original_contract=runner.case_expected_contract
 def contract(**kw):
  v=original_contract(**kw);v.update(wang_mode='off' if kw['kind']=='anchor' else 'on',wang_protocol='Wang2024-equations1-4',wang_run_identity=run_identity)
  return v
 runner.case_expected_contract=contract
 original_case=runner.run_encode_case
 def case(**kw):
  kind=kw['kind'];folder=kw['run_dir'];old=dict(os.environ)
  env=runtime_env(kind,old)
  os.environ.clear();os.environ.update(env)
  try:
   manifest=original_case(**kw)
   audit=folder/(kind+'_transform.csv');verified=folder/(kind+'_transform_verified.json')
   cmd=list(manifest['command']);i=cmd.index('-o');del cmd[i:i+2]
   bit=folder/(kind+'_timed.vvc');cmd[cmd.index('-b')+1]=str(bit)
   expected=dict(sha256=manifest['SHA256'],encoder_sha256=manifest['hashes']['encoder_sha256'],command=cmd,wang_mode=env['WANG_LFNST_MODE'],run_identity=run_identity)
   if not timing_matches(load(verified),expected):
    tenv=dict(env,LFNST_TRANSFORM_AUDIT=str(audit))
    with (folder/(kind+'_timed.log')).open('w') as f:subprocess.run(cmd,env=tenv,stdout=f,stderr=subprocess.STDOUT,check=True)
    sha=hashlib.sha256(bit.read_bytes()).hexdigest()
    if sha!=manifest['SHA256']:raise RuntimeError('transform timing bitstream mismatch: '+str(folder))
    with audit.open() as f:ns=sum(int(r['ns']) for r in csv.DictReader(f))
    if ns<=0:raise RuntimeError('missing transform timing')
    save(verified,dict(expected,transform_ns=ns))
    bit.unlink()
   return manifest
  finally:os.environ.clear();os.environ.update(old)
 runner.run_encode_case=case
 sys.argv=['wang2024','--encoder',str(ENC),'--360convert',str(CONVERT),'--seq-root',str(SEQROOT),'--sphere-file',str(SPHERE),'--out-root',str(target),'--qps','22,27,32,37','--profiles','Wang2024','--threads','1','--preset',preset,'--encode-config','LD' if config=='LDP' else config,'--ra-gop','16','--ld-gop','8','--ai-frames','1','--repeats','1','--expect-count','14','--sequence-filter','^'+re.escape(sequence)+'$','--resume']
 runner.main()
 with next(target.rglob('encode_rows.csv')).open() as f:rows=list(csv.DictReader(f))
 group={k:[r for r in rows if r['kind']==k] for k in ('anchor','proposed')}
 if not all(len(v)==4 for v in group.values()):raise RuntimeError('incomplete four-QP group')
 result=dict(preset=preset,config=config,sequence=sequence,repeat=1)
 for metric in ('PSNR','WS','S','CPP'):
  a,b=[sorted((math.log(float(r['Kbps'])),float(r['360Lib13_6_'+metric+'_Y'])) for r in group[k]) for k in ('anchor','proposed')]
  lo=max(a[0][0],b[0][0]);hi=min(a[-1][0],b[-1][0])
  if hi<=lo:raise RuntimeError('no common log-rate interval')
  result[metric+'_Y_BDPSNR_dB']=(PchipInterpolator(*zip(*b)).integrate(lo,hi)-PchipInterpolator(*zip(*a)).integrate(lo,hi))/(hi-lo)
 totals={}
 for k in ('anchor','proposed'):
  files=list(target.rglob(k+'_transform_verified.json'))
  if len(files)!=4:raise RuntimeError('incomplete transform timing')
  totals[k]=sum(json.loads(f.read_text())['transform_ns'] for f in files)
 result.update(totals);result['TS_T_pct']=100*(1-totals['proposed']/totals['anchor'])
 save(target/'extra_metrics.json',result);save(target/'complete.json',dict(status='COMPLETE',run_identity=run_identity))
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true');parser.add_argument('--child',nargs=3)
 args=parser.parse_args()
 if args.child:child(*args.child);return
 contract=plan();contract['encoder_sha256']=hashlib.sha256(ENC.read_bytes()).hexdigest() if ENC.exists() else None
 cpus=[int(c) for c in os.environ.get('WANG_CPU_LIST','18,20').split(',')]
 if len(set(cpus))!=len(cpus) or not set(cpus)<=os.sched_getaffinity(0):raise RuntimeError('invalid CPU list')
 contract.update(cpus=cpus,workers=len(cpus));save(OUT/'plan.json',contract)
 if args.dry_run:print('PASS dry-run:126groups,1008formal encodes,repeat1,threads1');return
 for p in (ENC,CONVERT,SPHERE,ROOT/'ldp.cfg'):
  if not p.is_file():raise RuntimeError('missing '+str(p))
 run_identity=identity()
 completed=[]
 def status(state,active=None):save(OUT/'progress.json',dict(status=state,total_groups=126,completed_groups=len(completed),completed=completed,active=active,updated_unix=time.time()))
 pending={};free=list(cpus)
 def work(job,cpu):
  folder=OUT.joinpath(*job);folder.mkdir(parents=True,exist_ok=True)
  with (folder/'runner.log').open('a') as f:subprocess.run(['taskset','-c',str(cpu),sys.executable,'-u','-m','tools.wang2024.run_matrix','--child',*job],cwd=str(ROOT),stdout=f,stderr=subprocess.STDOUT,check=True)
  return job
 status('RUNNING')
 try:
  with concurrent.futures.ThreadPoolExecutor(max_workers=len(cpus)) as pool:
   for job in contract['jobs']:
    if completion_matches(load(OUT.joinpath(*job)/'complete.json'),run_identity):completed.append(job);continue
    while not free:
     done,_=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
     for f in done:free.append(pending.pop(f));completed.append(f.result());status('RUNNING')
    while shutil.disk_usage(ROOT).free<8*2**30 or int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text())[1])<6*1024**2:
     status('WAITING_RESOURCES');time.sleep(20)
    cpu=free.pop();pending[pool.submit(work,job,cpu)]=cpu;status('RUNNING',job)
   for f in concurrent.futures.as_completed(pending):completed.append(f.result());status('RUNNING')
  status('COMPLETE')
 except Exception:
  status('FAILED');raise
if __name__=='__main__':main()
