import json,hashlib,subprocess,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST')
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010');OUT=D/'metrics360'
TMP=ROOT/'build-vtmrc/sibrc300-decoder-temp'
SOURCE=ROOT/'build-vtmrc/metric-source-cache/AerialCity_3840x1920_30fps_8bit_420_erp.yuv'
EXE=ROOT/'build-vtmrc/metrics360-parallel/Release/metrics360.exe'
DEC=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe')
SPHERE=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/cfg-360Lib/360Lib/sphere_655362.txt')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()
def run(name):
 q=json.loads((OUT/(name+'.json')).read_text());rec=TMP/(name+'.yuv')
 assert not rec.exists()
 print('DECODE FOR CPP VALIDATION',name,flush=True)
 with (OUT/(name+'.cpp_validation_decode.log')).open('w') as log:
  subprocess.run([str(DEC),'-b',str(D/(name+'.vvc')),'-o',str(rec)],stdout=log,stderr=subprocess.STDOUT,check=True)
 assert rec.stat().st_size==3840*1920*3*300
 assert sha(rec)==q['reconstruction_prefix_sha256']
 indices=[0,150,299];size=3840*1920*3//2
 with tempfile.TemporaryDirectory(prefix='cpp-final-validation-',dir=str(ROOT/'build-vtmrc/metric-tests')) as td:
  t=Path(td)
  with SOURCE.open('rb') as source,rec.open('rb') as recon,(t/'src.yuv').open('wb') as so,(t/'rec.yuv').open('wb') as ro:
   for i in indices:
    source.seek(i*size);recon.seek(i*size*2)
    s=source.read(size);r=recon.read(size*2);assert len(s)==size and len(r)==size*2;so.write(s);ro.write(r)
  out=OUT/(name+'.cpp_spot_validation.json')
  with (OUT/(name+'.cpp_spot_validation.log')).open('w') as log:
   subprocess.run([str(EXE),str(t/'src.yuv'),str(t/'rec.yuv'),'3840','1920','3',str(SPHERE),str(out),'3'],stdout=log,stderr=subprocess.STDOUT,check=True)
  v=json.loads(out.read_text());assert v['picture_y_cpppsnr']==[q['picture_y_cpppsnr'][i] for i in indices]
  evidence={'frames':indices,'exe_sha256':sha(EXE),'sphere_sha256':sha(SPHERE),'reconstruction_prefix_sha256':q['reconstruction_prefix_sha256'],'source_prefix_sha256':q['source_prefix_sha256'],'cpp_output_sha256':sha(out),'max_abs_difference':0.0}
  (OUT/(name+'.cpp_spot_validation.provenance.json')).write_text(json.dumps(evidence,indent=2))
 q.update(cpp_revalidation_samples=indices,cpp_revalidation_max_abs_difference=0.0)
 (OUT/(name+'.json')).write_text(json.dumps(q,indent=2))
 assert rec.resolve().parent==TMP.resolve();rec.unlink()
 print('PASS CPP CORRECTED EXACT',name,indices,flush=True)
 return q
with ThreadPoolExecutor(max_workers=2) as pool:points=list(pool.map(run,['rc300_anchor_R1','rc300_full_R1']))
a=json.loads((OUT/'assessment.json').read_text())
for q in points:
 a['points']=[q if p['name']==q['name'] else p for p in a['points']]
(OUT/'assessment.json').write_text(json.dumps(a,indent=2))
print('PASS both R1 corrected CPP spot checks; numerical BD-rates unchanged')
