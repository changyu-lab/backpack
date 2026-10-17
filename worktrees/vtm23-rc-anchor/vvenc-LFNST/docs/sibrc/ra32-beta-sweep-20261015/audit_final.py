import csv,hashlib,json,re,math
from pathlib import Path
B=Path('/root/sibrc-ra32-beta-20261015');P=Path('/data/vtmrc-vvenc-ra32-20261014')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for x in iter(lambda:f.read(8388608),b''):h.update(x)
 return h.hexdigest()
rows=[];errors=[];count=0
for f,h in json.loads((B/'frozen-assets.json').read_text()).items():assert sha(f)==h,f
for spec in json.loads((B/'sources.json').read_text()):
 for label in ['anchor','B2','B3','B5','B8','B12','B18','B20']:
  root=P if label=='anchor' else B
  for pt in range(1,5):
   pre=root/'runs'/spec['name']/label/('R'+str(pt));r=json.loads(pre.with_suffix('.run.json').read_text());q=json.loads(pre.with_suffix('.quality.json').read_text())
   assert r['verified'] and r['pocs']==list(range(32))
   for f,h in r['outputs_sha256'].items():assert sha(f)==h,f
   assert q['bitstream_sha256']==sha(pre.with_suffix('.vvc'))
   text=pre.with_suffix('.log').read_text();kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
   assert len(kinds)==32 and 'I' in kinds and 'B' in kinds
   assert sum(q['picture_bits'])==pre.with_suffix('.vvc').stat().st_size*8
   assert abs(q['actual_bps']-sum(q['picture_bits'])*spec['fps']/32)<1e-6
   for k in ['psnr','wspsnr','spsnr','cpppsnr']:assert len(q['picture_y_'+k])==32 and all(math.isfinite(v) for v in q['picture_y_'+k])
   if label!='anchor':
    ct=json.loads(pre.with_suffix('.contract.json').read_text());assert ct['invalid_intersections']==0 and ct['unsafe_applied_qps']==0
   errors.append(dict(sequence=spec['name'],method=label,point=pt,target_bps=q['target_bps'],actual_bps=q['actual_bps'],error_percent=100*(q['actual_bps']/q['target_bps']-1)))
   for poc in range(32):
    row=dict(sequence=spec['name'],method=label,point=pt,poc=poc,bits=q['picture_bits'][poc],bitrate_bps=q['picture_bits'][poc]*spec['fps'])
    row.update({k:q['picture_y_'+k][poc] for k in ['psnr','wspsnr','spsnr','cpppsnr']});rows.append(row)
   count+=1;print('AUDIT',count,flush=True)
for name,data in [('frames.csv',rows),('rate-errors.csv',errors)]:
 with (B/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
assert count==192 and len(rows)==6144
import gzip
records=list((B/'collect').rglob('*.run.json'));assert len(records)==224
labels={}
for record in records:
 r=json.loads(record.read_text());assert r['verified'];packed=Path(r['prefix']+'.sibrc.csv.gz')
 assert sha(packed)==r['packed_sha256']
 h=hashlib.sha256()
 with gzip.open(packed,'rb') as f:
  for chunk in iter(lambda:f.read(8388608),b''):h.update(chunk)
 assert h.hexdigest()==r['raw_trace_sha256']
 key=(r['sequence'],r['window'],r['qp']);labels.setdefault(key,set()).add(r['bitstream_sha256'])
assert len(labels)==32 and all(len(v)==1 for v in labels.values())
protocol=json.loads((B/'calibration-protocol.json').read_text());keyhash=protocol['common_key_sha256']
for beta in [2,3,5,8,12,18,20]:
 for kind in ['I','P']:
  m=json.loads((B/'models'/('B'+str(beta))/('model.'+kind+'.json')).read_text());assert m['matched_key_sha256']==keyhash
compat=json.loads((B/'compatibility-approved.json').read_text());assert compat['pass_test'] and compat['bitstream_identical']
(B/'final-validation.json').write_text(json.dumps(dict(status='PASS',comparison_streams=count,new_formal_streams=168,reused_anchor=24,frame_rows=len(rows),collection_runs=224,collection_bitstream_equal_groups=32,common_training_samples=protocol['common_samples'],common_key_sha256=keyhash,beta5_regression='PASS limited AerialCity RA32 R1',source_hash_scope='Metric source prefix provenance retained; final pass does not rehash full sources'),indent=2))
print('FINAL PASS',flush=True)
