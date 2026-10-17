import csv,hashlib,json,re,math
from pathlib import Path
B=Path('/root/sibrc-ra32-beta-fixed5-20261015');OLD=Path('/root/sibrc-ra32-beta-20261015');P=Path('/data/vtmrc-vvenc-ra32-20261014')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for x in iter(lambda:f.read(8388608),b''):h.update(x)
 return h.hexdigest()
rows=[];errors=[];count=0
for f,h in json.loads((B/'frozen-assets.json').read_text()).items():assert sha(f)==h,f
for spec in json.loads((B/'sources.json').read_text()):
 for label in ['anchor','B2','B3','B5','B8','B12','B18','B20']:
  root=P if label=='anchor' else (OLD if label=='B5' else B)
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
assert len(list((B/'runs').rglob('*.run.json')))==144
for p in (B/'runs').rglob('*.run.json'):
 r=json.loads(p.read_text());models=[v.split('=',1)[1] for v in r['command'] if v.startswith('--SIBRCModel=')];assert models==[str(OLD/'models/B5/model')]
for suite in ['recalibrated','fixed5']:
 m=json.loads((B/(suite+'-mechanisms.json')).read_text());assert len(m['rows'])==504
 assert m['active_frequency_band_ratio'] is None
m=json.loads((B/'collection-descriptor-mechanisms.json').read_text());assert len(m['rows'])==14
(B/'final-validation.json').write_text(json.dumps(dict(status='PASS',comparison_streams=192,new_formal_streams=144,reused_B5=24,reused_anchor=24,frame_rows=6144,model_scope='Current sweep B5 I/P frozen for every runtime beta',mechanisms_summaries_each=504,collection_descriptor_summaries=14,per_band_activation_available=False,source_hash_scope='Source prefix metric provenance retained; no final full source rehash'),indent=2))
print('FINAL PASS',flush=True)
