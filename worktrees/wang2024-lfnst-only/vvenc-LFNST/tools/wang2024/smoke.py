"""Remote integration verification, separate from formal timing."""
import pathlib,subprocess,os,json,random,hashlib,shutil
from tools.wang2024.contract import runtime_env,command
from tools.lard_lfnst.official_360lib_metrics import run_360lib_metrics
r=pathlib.Path('/data/wang2024_lfnst_only_20261007');o=r/'smoke';o.mkdir(exist_ok=True)
base=pathlib.Path('/root/vvenc_lard_exp/Stage123_AI_WrongSkip_20261005/src')
manifest=json.loads((r/'tools/wang2024/baseline_source_sha256.json').read_text())
mismatch=[]
for rel,sha in manifest.items():
 p=base/rel
 if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:mismatch.append(rel)
print('baseline source mismatches',len(mismatch),mismatch[:15],flush=True)
if mismatch:raise RuntimeError('formal source provenance mismatch')
random.seed(20241007)
data=bytes(max(0,min(255,100+(x*3+y*7)%80+random.randrange(-20,21))) for y in range(128) for x in range(128))
frame=data+bytes([128])*(128*128//2)
(o/'input.yuv').write_bytes(frame*16)
seq=dict(name='smoke',path=str(o/'input.yuv'),width=128,height=128,fps=30,bitdepth=8)
checks=[]
for preset,config in [('fast','AI'),('medium','AI'),('slow','AI'),('medium','RA'),('medium','LDP')]:
 folder=o/preset/config;folder.mkdir(parents=True,exist_ok=True);hashes={};audits={}
 for mode in ('original','off','shadow','on'):
  enc=base/'bin/release-static/vvencFFapp' if mode=='original' else r/'src/bin/release-static/vvencFFapp'
  bit=folder/(mode+'.vvc');rec=folder/(mode+'.yuv')
  cmd=command(enc,seq,22,preset,config,bit,rec,r/'ldp.cfg')
  env=runtime_env('proposed' if mode=='on' else 'anchor',os.environ)
  if mode in ('on','shadow'):
   env.update(WANG_LFNST_MODE=mode,WANG_LFNST_AUDIT=str(folder/(mode+'.json')),WANG_LFNST_VERIFY_PRIMARY='1')
  with (folder/(mode+'.log')).open('w') as f:subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
  hashes[mode]=dict(bit=hashlib.sha256(bit.read_bytes()).hexdigest(),rec=hashlib.sha256(rec.read_bytes()).hexdigest())
  if mode in ('on','shadow'):audits[mode]=json.loads((folder/(mode+'.json')).read_text())
 assert hashes['original']==hashes['off']==hashes['shadow'],(preset,config,hashes)
 assert sum(k['skipped'] for k in audits['on']['kernels'])>0
 assert all(k['skipped']==0 for k in audits['shadow']['kernels'])
 checks.append(dict(preset=preset,config=config,hashes=hashes,audits=audits))
 print('PASS',preset,config,'original=off=shadow; on skipped',sum(k['skipped'] for k in audits['on']['kernels']),flush=True)
assert sum(k['isp_considered'] for c in checks for k in c['audits']['shadow']['kernels'])>0,'ISP coverage absent across native presets'
assert sum(k['mip_considered'] for c in checks for k in c['audits']['shadow']['kernels'])>0,'MIP coverage absent across native presets'
folder=o/'medium/AI'
metrics=run_360lib_metrics(executable=pathlib.Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/360ConvertAppStatic'),original=o/'input.yuv',reconstruction=folder/'on.yuv',sphere_file=pathlib.Path('/data/ibrc_st_direct_wref/VTM-23.0/cfg-360Lib/360Lib/sphere_655362.txt'),width=128,height=128,fps=30,frames=1,original_bitdepth=8,reconstruction_bitdepth=10,log_path=folder/'quality.log',parsed_json_path=folder/'quality.json')
assert metrics and (folder/'quality.json').exists()
decoder=pathlib.Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/DecoderAppStatic')
decoded=False
if decoder.exists():
 with (folder/'decoder.log').open('w') as f:subprocess.run([str(decoder),'-b',str(folder/'on.vvc'),'-o',str(folder/'decoded.yuv')],stdout=f,stderr=subprocess.STDOUT,check=True)
 assert hashlib.sha256((folder/'decoded.yuv').read_bytes()).hexdigest()==checks[1]['hashes']['on']['rec']
 decoded=True;print('PASS independent VTM decode reconstruction hash',flush=True)
report=dict(status='PASS',source_mismatches=mismatch,checks=checks,quality=metrics,independent_decode=decoded,encoder_sha256=hashlib.sha256((r/'src/bin/release-static/vvencFFapp').read_bytes()).hexdigest())
(o/'verification.json').write_text(json.dumps(report,indent=2))
print('PASS all integration smoke checks',flush=True)
