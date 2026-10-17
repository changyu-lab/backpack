import json,csv,gzip,hashlib,re,math
from pathlib import Path
B=Path('/root/sibrc-ra300-stable-20261016');OLD=Path('/root/sibrc-ra300-20261016')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for x in iter(lambda:f.read(8388608),b''):h.update(x)
 return h.hexdigest()
a=json.loads((B/'frozen-assets.json').read_text())
for f,h in a['original_assets'].items():assert sha(f)==h
assert sha(a['new_exe_path'])==a['new_exe_sha256']
for x in json.loads((OLD/'input-reuse-manifest.json').read_text()):assert sha(x['path'])==x['sha256']
assert json.loads((B/'regression-approved.json').read_text())['status']=='PASS'
records=json.loads((B/'all-runs.json').read_text());assert len(records)==24
rows=[];errs=[];guards=[];contracts=0
for r in records:
 assert r['verified'] and r['pocs']==list(range(300))
 pre=Path(r['prefix']);t=pre.with_suffix('.log').read_text();types={int(p):k for p,k in re.findall(r'POC\s+(\d+).*?\(.*?\b([IPB])-SLICE',t)}
 assert sorted(types)==list(range(300)) and [p for p in sorted(types) if types[p]=='I']==list(range(0,300,32)) and 'B' in types.values()
 for f,h in r['outputs_sha256'].items():assert sha(f)==h
 for f,h in r.get('original_trace_sha256',{}).items():
  z=hashlib.sha256()
  with gzip.open(f+'.gz','rb') as a:
   for x in iter(lambda:a.read(8388608),b''):z.update(x)
  assert z.hexdigest()==h
 assert abs(r['actual_bps']-pre.with_suffix('.vvc').stat().st_size*8*30/300)<1e-6
 if r['label']=='cqp':continue
 q=json.loads(pre.with_suffix('.quality.json').read_text());assert q['bitstream_sha256']==sha(pre.with_suffix('.vvc')) and sum(q['picture_bits'])==pre.with_suffix('.vvc').stat().st_size*8
 for k in ['psnr','wspsnr','spsnr','cpppsnr']:assert len(q['picture_y_'+k])==300 and all(math.isfinite(x) for x in q['picture_y_'+k])
 errs.append(dict(sequence=r['sequence'],method=r['label'],point=r['point'],target_bps=r['target_bps'],actual_bps=r['actual_bps'],error_percent=100*(r['actual_bps']/r['target_bps']-1),exe=r['command'][0]))
 for poc in range(300):
  row=dict(sequence=r['sequence'],method=r['label'],point=r['point'],poc=poc,bits=q['picture_bits'][poc],bitrate_bps=q['picture_bits'][poc]*30)
  row.update({k:q['picture_y_'+k][poc] for k in ['psnr','wspsnr','spsnr','cpppsnr']});rows.append(row)
 if r['label']=='C4':
  ct=json.loads(pre.with_suffix('.contract.json').read_text());assert ct['invalid_intersections']==0 and ct['unsafe_applied_qps']==0;contracts+=1
 if r['command'][0]==str(B/'vvencFFapp'):
  seen=0;activations=[]
  with gzip.open(str(pre)+'.vtm.csv.gz','rt') as f:
   for x in csv.DictReader(f):
    if x['event']=='begin' and types[int(x['poc'])]=='I' and int(x['seq_left'])<=0:activations.append(dict(poc=int(x['poc']),remaining_bits=int(x['seq_left']),remaining_frames=300-seen,target_bits=int(x['pic_target'])));assert int(x['pic_target'])==200
    if x['event']=='picture':seen+=1
  guards.append(dict(sequence=r['sequence'],method=r['label'],point=r['point'],activations=activations))
 print('AUDIT PASS',r['sequence'],r['label'],r['point'],flush=True)
assert len(rows)==4800 and len(errs)==16 and contracts==8
for n,data in [('frames.csv',rows),('rate-errors.csv',errs)]:
 with (B/n).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
(B/'numeric-guard-activations.json').write_text(json.dumps(guards,indent=2))
(B/'branch-domain-validation.json').write_text(json.dumps(dict(status='BY_CONSTRUCTION_NOT_NUMERIC_TEST',scope='Patch branch uses remainingAverageBits>0; formal1..199 numerical sweep not yet run; do not cite199 tests'),indent=2))
(B/'final-validation.json').write_text(json.dumps(dict(status='PASS',streams=24,comparison_streams=16,cqp_streams=8,frames=300,frame_rows=4800,contracts=contracts,original_valid_streams_reused=19,stable_streams=5,full_source_sha_checked=True,guard_scope='Deterministic nonpositive intra-budget200bits extension;4 full300 regression vvc/trace byte-identical; not original unmodified VTM',development_sequences=['DrivingInCountry']),indent=2))
print('FINAL AUDIT PASS',flush=True)
