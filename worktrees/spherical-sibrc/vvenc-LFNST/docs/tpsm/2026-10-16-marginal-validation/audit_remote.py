"""Independent local audit of the returned marginal experiment; no remote mutations."""
from pathlib import Path
import json,gzip,csv,hashlib,re,math,sys,tarfile
import numpy as np
ROOT=Path('C:/Users/hitxi/.codex/worktrees/spherical-sibrc/vvenc-LFNST');sys.path.insert(0,str(ROOT/'tools/tpsm'))
from marginal import contrast,ranking,select_ctus
B=Path('I:/vvenc-LFNST/.tmp/tpsm-marginal');D=B/'remote-evidence'
D.mkdir(exist_ok=True)
with tarfile.open(B/'remote-evidence.tar.gz') as t:
 for m in t.getmembers():assert not m.issym() and not m.islnk() and not m.name.startswith('/') and '..' not in Path(m.name).parts
 t.extractall(D)
R=D/'run';P=json.loads((R/'protocol.json').read_text());S=json.loads((R/'selection.json').read_text());Q=json.loads((R/'results.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def metrics(name):return json.loads((R/(name+'.metrics.json')).read_text())
def rows(name,kind):
 with gzip.open(R/(name+'.'+kind+'.csv.gz'),'rt') as f:return list(csv.DictReader(f))
baseline=metrics('baseline');zero=metrics('zero_replay')
expected_exe=P['assets']['/dev/shm/spherical_sibrc_probe_src/bin/release-static/vvencFFapp']
assert sha(D/'vvencFFapp-probe')==expected_exe
assert sha(D/'overlay-final12.tar.gz')==hashlib.sha256((B/'overlay-final12.tar.gz').read_bytes()).hexdigest()
assert 'Ran 11 tests' in (D/'final-tests.log').read_text() and 'Ran 20 tests' in (D/'final-tests.log').read_text()
assert '100% tests passed, 0 tests failed out of 2' in (D/'final-tests.log').read_text()

assert baseline['bitstream_sha256']==zero['bitstream_sha256']=='adf87f21575af859165eedc3a9e45447842372508fcafda7a8522775b2b8dccb'
assert baseline['frame_reconstruction_sha256']==zero['frame_reconstruction_sha256'] and baseline['wsse']==zero['wsse']
assert P['probe_poc']==8 and P['frames']==65 and P['target_bps']==818855
assert sha(R/'baseline.decisions')==S['decision_sha256']
selected=select_ctus(rows('baseline','tpsm'),8,4);assert selected==S['samples']
localS=json.loads((ROOT/'docs/tpsm/2026-10-16-marginal-validation/reviewed-selection-poc8.json').read_text())
# Cross-platform decimal traces can differ in the last printed lambda/cos bit.
# Freeze sample identity/rank strata and compare numeric weights, not text formatting.
assert [(x['ctu'],x['stratum']) for x in localS['samples']]==[(x['ctu'],x['stratum']) for x in selected]
for x,y in zip(localS['samples'],selected):
 assert x['qp']==y['qp'] and x['bits']==y['bits']
 assert math.isclose(float(x['wt']),float(y['wt']),rel_tol=1e-12,abs_tol=1e-12)

schedule=rows('baseline','sibrc');assert len(schedule)==450*65
expectedkeys=[(p,c) for p in range(65) for c in range(450)]
assert [(int(x['poc']),int(x['ctu'])) for x in schedule]==expectedkeys
picture=[(x['poc'],x['qp'],x['lambda']) for x in rows('baseline','vtm') if x['event']=='begin'];assert len(picture)==65
results=[];evidence={}
for name in ['baseline','zero_replay']+['ctu'+r['ctu']+suffix for r in selected for suffix in ['_minus','_plus']]:
 m=metrics(name);record=json.loads((R/(name+'.run.json')).read_text());assert record['returncode']==0
 assert m['reconstruction_sha256']==m['decoder_reconstruction_sha256'];assert len(m['wsse'])==65 and len(m['picture_bits'])==65 and all(math.isfinite(x) and x>0 for x in m['wsse'])
 assert len(m['frame_reconstruction_sha256'])==65 and m['frame_reconstruction_sha256'][:8]==baseline['frame_reconstruction_sha256'][:8]
 assert m['picture_bits'][:8]==baseline['picture_bits'][:8] and m['wsse'][:8]==baseline['wsse'][:8]
 bit=R/(name+'.vvc');assert sha(bit)==m['bitstream_sha256'];assert bit.stat().st_size*8==m['annexb_bits']
 decoded=(R/(name+'.decode.log')).read_text();assert [int(x) for x in re.findall(r'POC\s+(\d+)',decoded)]==list(range(65))
 init=[(x['poc'],x['qp'],x['lambda']) for x in rows(name,'vtm') if x['event']=='begin'];assert init==picture
 if name not in ['baseline','zero_replay']:
  ctu=int(name.split('_')[0][3:]);offset=-1 if name.endswith('minus') else 1
  after=rows(name,'sibrc');assert len(after)==len(schedule)
  for before,changed,key in zip(schedule,after,expectedkeys):
   assert (int(changed['poc']),int(changed['ctu']))==key
   bump=offset if key==(8,ctu) else 0
   assert int(changed['qp'])==int(before['qp'])+bump
   assert math.isclose(float(changed['lambda']),float(before['lambda'])*2**(bump/3),rel_tol=1e-14)
 evidence[name]={'bitstream_sha256':m['bitstream_sha256'],'annexb_minus_picture_bits':m['annexb_bits']-sum(m['picture_bits']),'schedule_checked':True,'all65frames_decode_checked':True,'prefix0_to7_identical':True}
for sample,r in zip(selected,Q['samples']):
 assert int(sample['ctu'])==r['ctu'];a=metrics('ctu'+sample['ctu']+'_minus');b=metrics('ctu'+sample['ctu']+'_plus')
 for label,pair in [('minus_vs_baseline',(a,baseline)),('baseline_vs_plus',(baseline,b)),('central_minus_vs_plus',(a,b))]:
  v=contrast(*pair,8)
  for k,x in v.items():
   actual=r[label][k]
   assert (x is None and actual is None) or (x is not None and actual is not None and math.isclose(x,actual,rel_tol=1e-12,abs_tol=1e-8)),(r['ctu'],k,x,actual)
 results.append(r)
valid=[r for r in results if r['central_minus_vs_plus']['amplification'] is not None]
for label,field in [('future_per_current_error','amplification'),('raw_future_reduction','future_sse_reduction')]:
 use=valid if field=='amplification' else results
 v=ranking([r['wt'] for r in use],[r['central_minus_vs_plus'][field] for r in use]);assert v==Q['rank_tests'][label]
# Independent baseline per-frame PSNR matches prior65-frame reference.
old=json.loads((ROOT/'docs/tpsm/2026-10-16-remote-aerial4k-ldp65/evidence/results/sibrc_R2.quality.json').read_text());assert np.allclose(old['picture_y_wspsnr'],baseline['wspsnr'],rtol=0,atol=1e-10)
output={'state':'passed','cases':26,'all26_independent_decodes':True,'all_frozen_picture_and_CTU_schedules_checked':True,'all_probe_prefixes_unchanged':True,'sample_selection_matches_pre_outcome_local_selection':True,'all_contrasts_and_permutation_results_independently_recomputed':True,'baseline_matches_prior4k65R2':True,'cases_detail':evidence,'rank_tests':Q['rank_tests']}
(B/'independent-audit.json').write_text(json.dumps(output,indent=2));print('AUDIT_PASSED26',json.dumps(Q['rank_tests']))
