import json,gzip,hashlib,re,csv,math
from pathlib import Path
B=Path('/root/sibrc-ldp16-300-20261015')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for x in iter(lambda:f.read(8388608),b''):h.update(x)
 return h.hexdigest()
for f,h in json.loads((B/'frozen-assets.json').read_text()).items():assert sha(f)==h,f
for x in json.loads((B/'upload-verification.json').read_text()):assert Path(x['path']).stat().st_size==x['bytes'] and sha(x['path'])==x['sha256']
records=list((B/'runs').rglob('*.run.json'));assert len(records)==24
contracts=0;quality=0
for p in records:
 r=json.loads(p.read_text());assert r['verified'] and r['ldp_framekind'] and r['pocs']==list(range(300))
 for f,h in r['outputs_sha256'].items():assert sha(f)==h,f
 for f,h in r.get('original_trace_sha256',{}).items():
  digest=hashlib.sha256()
  with gzip.open(f+'.gz','rb') as t:
   for x in iter(lambda:t.read(8388608),b''):digest.update(x)
  assert digest.hexdigest()==h
 pre=Path(r['prefix']);text=pre.with_suffix('.log').read_text();kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
 assert kinds==['I']+['P']*299 and re.search(r'GOP size\s+: 16',text)
 assert abs(r['actual_bps']-pre.with_suffix('.vvc').stat().st_size*8*r['spec']['fps']/300)<1e-6
 if r['label']!='cqp':
  q=json.loads(pre.with_suffix('.quality.json').read_text());assert q['bitstream_sha256']==sha(pre.with_suffix('.vvc'))
  assert sum(q['picture_bits'])==pre.with_suffix('.vvc').stat().st_size*8
  for k in ['psnr','wspsnr','spsnr','cpppsnr']:assert len(q['picture_y_'+k])==300 and all(math.isfinite(x) for x in q['picture_y_'+k])
  quality+=1
 if r['label']=='C4':
  ct=json.loads(pre.with_suffix('.contract.json').read_text());assert ct['invalid_intersections']==0 and ct['unsafe_applied_qps']==0;contracts+=1
 print('AUDIT',r['sequence'],r['label'],r['point'],flush=True)
assert quality==16 and contracts==8
with (B/'frames.csv').open() as f:assert len(list(csv.DictReader(f)))==4800
(B/'final-validation.json').write_text(json.dumps(dict(status='PASS',all_streams=24,comparison_streams=16,cqp_streams=8,frames_per_stream=300,frame_rows=4800,intra_contracts=8,gopsize=16,source_full_300_sha_rechecked=True,compressed_and_original_trace_hashes_verified=True,development_sequences=['DrivingInCountry']),indent=2))
print('FINAL AUDIT PASS',flush=True)
