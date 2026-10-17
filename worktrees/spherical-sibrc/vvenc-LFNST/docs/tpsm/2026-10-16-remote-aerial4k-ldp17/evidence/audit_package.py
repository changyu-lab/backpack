import json,hashlib,re,math,tarfile
from pathlib import Path
b=Path('/root/spherical_sibrc_20261016_aerial4k_ldp17')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
completed=json.loads((b/'completed.json').read_text());assert completed['state']=='complete';assert completed['historical_anchor_bitstream_identity']==[True]*4
protocol=json.loads((b/'protocol.json').read_text());rows=[]
for method in ['anchor','paper_ad','sibrc','joint']:
 for i in range(1,5):
  stem=b/'results'/f'{method}_R{i}';q=json.loads(Path(str(stem)+'.quality.json').read_text());r=json.loads(Path(str(stem)+'.run.json').read_text());v=Path(str(stem)+'.vvc')
  assert sha(v)==q['bitstream_sha256']
  assert r['reconstruction_sha256']==r['decoder_reconstruction_sha256']==q['reconstruction_prefix_sha256']
  assert q['source_prefix_sha256']==protocol['source_prefix_sha256'] and q['frames']==17
  assert abs(q['actual_bps']-v.stat().st_size*8*30/17)<1e-8
  pocs=[int(x) for x in re.findall(r'POC\s+(\d+)',Path(str(stem)+'.decode.log').read_text())];assert pocs==list(range(17)),(method,i,pocs)
  for key in ['picture_y_wspsnr','picture_y_spsnr','picture_y_cpppsnr']:assert len(q[key])==17 and all(math.isfinite(x) for x in q[key])
  rows.append({'method':method,'point':i,'actual_bps':q['actual_bps'],'target_bps':q['target_bps'],'rate_error_percent':q['rate_error_percent'],'bitstream_sha256':q['bitstream_sha256']})
for path,expected in protocol['assets'].items():assert sha(Path(path))==expected,path
assert '100% tests passed, 0 tests failed out of 3' in (b/'linux-tests.log').read_text()
assert '100% tests passed, 0 tests failed out of 1' in (b/'linux-tests.log').read_text()
assert 'Ran 20 tests' in (b/'python-tests.log').read_text() and 'Ran 4 tests' in (b/'python-tests.log').read_text()
(b/'audit.json').write_text(json.dumps({'state':'passed','points':rows,'checks':['historical anchor bitstream identity at all 4 points','all 16 bitstream SHA256 hashes','independent decoder reconstruction hashes','decoder POC 0..16 for every bitstream','all metrics finite and cover 17 frames','actual Annex-B rate','source prefix and frozen assets unchanged','4 Linux CTests and 24 Python tests']},indent=2))
files=[p for p in b.glob('*') if p.is_file() and p.suffix in ['.json','.py','.log']]+list((b/'results').glob('*.json'))+list((b/'results').glob('*.gz'))+list((b/'results').glob('*.log'))+list((b/'reference').glob('*.json'))
integrity={str(p.relative_to(b)):sha(p) for p in files};(b/'evidence-integrity.json').write_text(json.dumps(integrity,indent=2));files.append(b/'evidence-integrity.json')
with tarfile.open(b/'evidence.tar.gz','w:gz') as t:
 for p in files:t.add(p,arcname=str(p.relative_to(b)))
print('AUDIT_PASSED',len(rows),'points',len(files),'evidence files',sha(b/'evidence.tar.gz'))
