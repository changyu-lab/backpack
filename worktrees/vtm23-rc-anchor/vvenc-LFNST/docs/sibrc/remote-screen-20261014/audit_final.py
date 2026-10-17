import json,csv,hashlib,math
from pathlib import Path
b=Path('/data/vtmrc-vvenc-tune-20261014')
def sha(p,n=None):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  while n is None or n>0:
   x=f.read(8388608 if n is None else min(n,8388608))
   if not x:break
   h.update(x)
   if n is not None:n-=len(x)
 assert n in (None,0)
 return h.hexdigest()
plan=json.loads((b/'plan.json').read_text());records=list((b/'runs').rglob('*.run.json'));assert len(records)==252
for path,h in json.loads((b/'frozen-assets.json').read_text()).items():assert sha(path)==h
for s in plan['sequences']:
 size=s['width']*s['height']*3//2*17*(2 if s['depth']==10 else 1)
 assert sha(Path('/data/360seqFull_17f')/s['filename'],size)==s['source_prefix_sha256']
frames=[];rates=[];matched=0;compared=0;contracts=0
for f in records:
 r=json.loads(f.read_text());assert r['verified'] and r['pocs']==list(range(17))
 for p,h in r['outputs_sha256'].items():assert sha(p)==h
 prefix=Path(r['prefix']);q=json.loads(prefix.with_suffix('.quality.json').read_text());assert q['bitstream_sha256']==sha(prefix.with_suffix('.vvc'))
 assert all(len(q['picture_y_'+k])==17 and math.isfinite(q['mean_y_'+k]) for k in ['wspsnr','spsnr','cpppsnr','psnr'])
 assert sum(q['picture_bits'])==prefix.with_suffix('.vvc').stat().st_size*8
 assert q['actual_bps']==prefix.with_suffix('.vvc').stat().st_size*8*r['spec']['fps']/17
 if r['label']!='anchor':
  contract=json.loads(Path(str(prefix)+'.contract.json').read_text());assert contract['invalid_intersections']==contract['unsafe_applied_qps']==0;contracts+=1
 if r['label'] in ('anchor','C4'):
  old=json.loads((b/'baseline'/r['sequence']/'quality.json').read_text());token='_anchor_' if r['label']=='anchor' else '_C4_'
  ref=next(x for x in old if token in x['name'] and x['name'].endswith('_R'+str(r['point'])))
  compared+=1;matched+=ref['bitstream_sha256']==q['bitstream_sha256']
 rates.append([r['sequence'],r['label'],r['point'],q['target_bps'],q['actual_bps'],100*(q['actual_bps']/q['target_bps']-1)])
 for k in range(17):frames.append([r['sequence'],r['label'],r['point'],k,q['picture_bits'][k],q['picture_bits'][k]*r['spec']['fps']]+[q['picture_y_'+x][k] for x in ['wspsnr','spsnr','cpppsnr','psnr']])
with (b/'frames.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['sequence','label','point','poc','bits','frame_bitrate_bps','wspsnr','spsnr','cpppsnr','psnr']);w.writerows(frames)
with (b/'rate-errors.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['sequence','label','point','target_bps','actual_bps','error_percent']);w.writerows(rates)
result=dict(pass_test=True,streams=252,frames_per_stream=17,frame_rows=len(frames),contracts=contracts,linux_windows_baseline_compared=compared,linux_windows_baseline_bit_identical=matched,checks=['all_output_hashes','all_frozen_asset_hashes','all_native_source17_prefix_hashes','POC0_16','all_four_metric_frame_counts','actual_annexb_rate_nativefps','all_nonanchor_intra_contracts'],reconstruction_hash_scope='recorded at evaluation; temporary files already removed',gain_scope='screening only, no independent window uploaded or tested')
(b/'final-validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
