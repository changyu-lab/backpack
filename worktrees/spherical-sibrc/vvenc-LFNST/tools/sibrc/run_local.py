"""Frozen local SIBRC screening pipeline; new outputs only, full commands and hashes retained."""
import argparse,csv,json,hashlib,re,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DATA=Path('I:/vvenc-LFNST/.worktrees/sibrc-experiment-data-20261009-v2')
EXE=ROOT/'bin/release-static/vvencFFapp.exe'
CFG=ROOT/'docs/vtm23-rc/aerialcity16_ldp.cfg'
SOURCES={s:Path('I:/Sequences360')/(s+'_3840x1920_30fps_8bit_420_erp.yuv') for s in ('AerialCity','DrivingInCity','DrivingInCountry')}
RATES=[1600000,3200000,6400000,12800000]
PY='F:/Anaconda/python.exe'
def sha(path,limit=None):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  left=limit
  while True:
   b=f.read(min(1048576,left) if left is not None else 1048576)
   if not b:break
   h.update(b)
   if left is not None:
    left-=len(b)
    if left<=0:break
 return h.hexdigest()
def job(name,seq,frames,rate,mode=0,qp=None,recon=False,cqp=None):
 prefix=DATA/name
 cmd=[str(EXE),'--preset','faster','-c',str(CFG),'-i',str(SOURCES[seq]),'-s','3840x1920','-fr','30','-f',str(frames),'-b',str(prefix)+'.vvc','--InputBitDepth=8','--InternalBitDepth=10','--OutputBitDepth=10',
 '--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0']
 outputs=[str(prefix)+'.vvc']
 if cqp is None:cmd+=['--VTMTargetBitrate='+str(rate),'--VTMRCTrace='+str(prefix)+'.vtm.csv'];outputs+=[str(prefix)+'.vtm.csv']
 else:cmd+=['--QP='+str(cqp)]
 if recon:cmd+=['-o',str(prefix)+'.yuv'];outputs+=[str(prefix)+'.yuv']
 assets=[EXE,CFG]
 if mode:
  cmd+=['--SIBRCMode='+str(mode)]
  if mode==1:cmd+=['--SIBRCResidual='+str(prefix)+'.residual.bin'];outputs+=[str(prefix)+'.residual.bin']
  if mode>=2:
   cmd+=['--SIBRCStats='+str(DATA/'stats.txt'),'--SIBRCTrace='+str(prefix)+'.sibrc.csv'];outputs+=[str(prefix)+'.sibrc.csv'];assets+=[DATA/'stats.txt']
  if mode==3:cmd+=['--SIBRCModel='+str(DATA/'model')];assets +=[DATA/'model.I',DATA/'model.P']
  if qp is not None:cmd+=['--SIBRCCalibrationQP='+str(qp)]
 return {'name':name,'source_sequence':seq,'frames':frames,'target_bps':rate,'command':cmd,'outputs':outputs,'assets':[str(x) for x in assets],'log':str(prefix)+'.log'}
def execute(j):
 if any(Path(p).exists() for p in j['outputs']):raise RuntimeError('output exists: '+j['name'])
 record=dict(j);record['asset_hashes']={p:sha(p) for p in j['assets']}
 record['raw_input']={'path':str(SOURCES[j['source_sequence']]),'file_bytes':SOURCES[j['source_sequence']].stat().st_size,'coded_prefix_sha256':sha(SOURCES[j['source_sequence']],3840*1920*3//2*j['frames'])}
 record['started_unix']=time.time();print('START',j['name'],flush=True)
 with open(j['log'],'w',encoding='utf8') as f:
  start=time.perf_counter();code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,cwd=ROOT).returncode
 record.update(returncode=code,elapsed_seconds=time.perf_counter()-start)
 text=Path(j['log']).read_text(encoding='utf8',errors='replace');pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))))
 record['pocs']=pocs;record['outputs_sha256']={p:sha(p) for p in j['outputs'] if Path(p).is_file()}
 record['verified']=code==0 and pocs==list(range(j['frames'])) and all(Path(p).is_file() for p in j['outputs']) and 'Total Time:' in text
 Path(DATA/(j['name']+'.run.json')).write_text(json.dumps(record,indent=2),encoding='utf8')
 if not record['verified']:raise RuntimeError(j['name']+' failed: '+text[-2500:])
 print('PASS',j['name'],round(record['elapsed_seconds'],3),flush=True);return record

def main():
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['dump','collect','smoke','cqp','main']);p.add_argument('--workers',type=int,default=2);a=p.parse_args();DATA.mkdir(parents=True,exist_ok=True)
 if a.stage=='dump':
  jobs=[job('dump_'+s,s,4,6400000,1) for s in ('DrivingInCity','DrivingInCountry')]
  jobs+=[job('identity_off','AerialCity',16,6400000),job('identity_dump','AerialCity',16,6400000,1)]
 elif a.stage=='collect':
  jobs=[job('collect_'+s+'_QP'+str(q),s,16,6400000,2,q) for s in ('DrivingInCity','DrivingInCountry') for q in (22,27,32,37)]
  jobs += [job('identity_collect','AerialCity',16,6400000,2)]
 elif a.stage=='smoke':jobs=[job('smoke_'+method+'_R'+str(i), 'AerialCity',16,rate,0 if method=='anchor' else 3,recon=True) for i,rate in enumerate(RATES,1) for method in ('anchor','full')]
 elif a.stage=='cqp':jobs=[job('cqp128_QP'+str(q),'AerialCity',128,0,cqp=q) for q in (22,27,32,37)]
 else:
  rates=json.loads((DATA/'main_targets.json').read_text(encoding='utf8'))
  jobs=[job('main_'+method+'_R'+str(i),'AerialCity',128,rate,0 if method=='anchor' else 3,recon=True) for i,rate in enumerate(rates,1) for method in ('anchor','full')]
 (DATA/(a.stage+'_jobs.json')).write_text(json.dumps(jobs,indent=2),encoding='utf8')
 with ThreadPoolExecutor(max_workers=a.workers) as pool:records=list(pool.map(execute,jobs))
 (DATA/(a.stage+'_results.json')).write_text(json.dumps(records,indent=2),encoding='utf8')
 if a.stage=='dump':
  assert sha(DATA/'identity_off.vvc')==sha(DATA/'identity_dump.vvc')
  assert sha(DATA/'identity_off.vvc')==sha(ROOT/'build-vtmrc/aerialcity16_ldp/R3.vvc')
  assert sha(DATA/'identity_off.vtm.csv')==sha(ROOT/'build-vtmrc/aerialcity16_ldp/R3.csv')
  combined=DATA/'development_residual.bin'
  with combined.open('wb') as out:
   for s in ('DrivingInCity','DrivingInCountry'):out.write((DATA/('dump_'+s+'.residual.bin')).read_bytes())
  meta={'sequences':['DrivingInCity','DrivingInCountry'],'frames':4,'run_records':[str(DATA/('dump_'+s+'.run.json')) for s in ('DrivingInCity','DrivingInCountry')],'dump_stride':16,'residual_normalization':'8bit','prediction':'first L0, integer SAD stride4 coarse4 +/-8 refine1 +/-2; intra128','evaluation_excluded':['AerialCity']}
  (DATA/'development_metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf8')
  subprocess.run([PY,str(ROOT/'tools/sibrc/calibrate.py'),'stats','--input',str(combined),'--metadata',str(DATA/'development_metadata.json'),'--output',str(DATA/'stats.txt')],check=True)
  print('PASS stats and anchor identity',flush=True)
 elif a.stage=='collect':
  rows=[]
  assert sha(DATA/'identity_collect.vvc')==sha(DATA/'identity_off.vvc')
  assert sha(DATA/'identity_collect.vtm.csv')==sha(DATA/'identity_off.vtm.csv')
  for j in jobs:
   if j['source_sequence']=='AerialCity':continue
   with open(DATA/(j['name']+'.sibrc.csv')) as f:
    for r in csv.DictReader(f):r['source_sequence']=j['source_sequence'];r['sequence']=j['source_sequence'];r['run_id']=j['name'];rows.append(r)
  with (DATA/'development_samples.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
  for kind in ('I','P'):subprocess.run([PY,str(ROOT/'tools/sibrc/calibrate.py'),'model','--input',str(DATA/'development_samples.csv'),'--metadata',str(DATA/'development_metadata.json'),'--kind',kind,'--equator-degrees','15','--output',str(DATA/('model.'+kind))],check=True)
  print('PASS independent frozen I/P models',flush=True)
 elif a.stage=='cqp':
  rates=[int(round((DATA/('cqp128_QP'+str(q)+'.vvc')).stat().st_size*8*30/128)) for q in (37,32,27,22)]
  (DATA/'main_targets.json').write_text(json.dumps(rates),encoding='utf8');print('FROZEN targets',rates,flush=True)
if __name__=='__main__':main()
