import json,hashlib,re,math,tarfile,csv,gzip
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
b=Path('/root/spherical_sibrc_20261016_aerial4k_ldp65');N=65

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
assert json.loads((b/'completed.json').read_text())['state']=='complete'
p=json.loads((b/'protocol.json').read_text());assert p['frames']==65 and p['GOPSize']==16
assert p['source_prefix_65_sha256']=='3ee22fe710ba457828398d6298c0f7a74400605913430183efd67c9cfd810ee5'
for row in p['targets_from_300_cqp_logs']:
 f=b/'reference300'/f'R{row["point"]}.log';assert sha(f)==row['log_sha256'];m=re.findall(r'^vvenc \[info\]:\s+(\d+)\s+a\s+([0-9.]+)\s+',f.read_text(),re.M);assert len(m)==1 and m[0][0]=='300'
 value=int((Decimal(m[0][1])*1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP));assert value==row['target_bps']
rows=[];diagnostics={}
for method in ['anchor','paper_ad','sibrc','joint']:
 for i in range(1,5):
  stem=b/'results'/f'{method}_R{i}';q=json.loads(Path(str(stem)+'.quality.json').read_text());r=json.loads(Path(str(stem)+'.run.json').read_text());v=Path(str(stem)+'.vvc')
  assert sha(v)==q['bitstream_sha256'];assert r['reconstruction_sha256']==r['decoder_reconstruction_sha256']==q['reconstruction_prefix_sha256']
  assert q['source_prefix_sha256']==p['source_prefix_65_sha256'] and q['frames']==N
  assert abs(q['actual_bps']-v.stat().st_size*8*30/N)<1e-8
  po=[int(x) for x in re.findall(r'POC\s+(\d+)',Path(str(stem)+'.decode.log').read_text())];assert po==list(range(N)),(method,i,po)
  for key in ['picture_y_wspsnr','picture_y_spsnr','picture_y_cpppsnr']:assert len(q[key])==N and all(math.isfinite(x) for x in q[key])
  target=p['targets_from_300_cqp_logs'][i-1]['target_bps'];assert q['target_bps']==target
  rows.append({'method':method,'point':i,'actual_bps':q['actual_bps'],'target_bps':target,'rate_error_percent':q['rate_error_percent'],'bitstream_sha256':q['bitstream_sha256']})
  if method in ['sibrc','joint']:
   with gzip.open(Path(str(stem)+'.sibrc.csv.gz'),'rt') as f:ctus=[x for x in csv.DictReader(f) if x['kind']=='P']
   assert len(ctus)==450*64
   diagnostics[f'{method}_R{i}']={'p_ctus':len(ctus),'fallback_fraction':sum(int(x['fallback']) for x in ctus)/len(ctus),'nonzero_offsets':sum(int(x['offset'])!=0 for x in ctus)}
  if method=='anchor' and i==2:
   assert r['historical_encoder_check']['bitstream_identity']
   assert sha(Path(str(stem)+'.historical.vvc'))==q['bitstream_sha256']
for path,h in p['assets'].items():assert sha(Path(path))==h,path
assert not list(Path('/dev/shm/spherical_sibrc_aerial4k_ldp65').glob('*.yuv'))
(b/'controller-diagnostics.json').write_text(json.dumps(diagnostics,indent=2))
(b/'audit.json').write_text(json.dumps({'state':'passed','points':rows,'checks':['targets independently recomputed from the four 300-frame CQP logs','GOP16 and 65 frames','local and remote source prefix identity','all 16 bitstream hashes','all independent decoder reconstruction hashes','decoder POCs exactly0..64','all quality arrays contain65 finite values','actual complete Annex-B rates','same frozen assets','R2 anchor bit-identical to historical encoder','P CTU count450x64','own temporary reconstructions reclaimed']},indent=2))
files=[x for x in b.glob('*') if x.is_file() and x.suffix in ['.json','.py','.log','.cfg'] and x.name!='evidence-integrity.json']+list((b/'results').glob('*.json'))+list((b/'results').glob('*.gz'))+list((b/'results').glob('*.log'))+list((b/'reference300').glob('*'))
index={str(x.relative_to(b)):sha(x) for x in files};(b/'evidence-integrity.json').write_text(json.dumps(index,indent=2));files.append(b/'evidence-integrity.json')
with tarfile.open(b/'evidence.tar.gz','w:gz') as t:
 for x in files:t.add(x,arcname=str(x.relative_to(b)))
digest=sha(b/'evidence.tar.gz');(b/'evidence.sha256').write_text(digest+'\n')
print('AUDIT_PASSED',len(rows),'points',len(files),'files',digest)
