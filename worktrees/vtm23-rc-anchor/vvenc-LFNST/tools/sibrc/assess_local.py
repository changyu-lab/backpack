"""Evaluate completed paired jobs; independently decode every evaluated stream."""
import argparse,csv,json,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from run_local import DATA,SOURCES,sha
from evaluate import quality,bd_rate
DEC=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe')
def assess(job):
 name=job['name'];p=DATA/name;out=DATA/(name+'.quality.json')
 trace=Path(str(p)+'.sibrc.csv')
 source_hash=job['raw_input']['coded_prefix_sha256']
 signature={'source_prefix_sha256':source_hash,'frames':job['frames'],'width':3840,'height':1920,'fps':30,'target_bps':job['target_bps'],'decoder_sha256':sha(DEC),'trace_sha256':sha(trace) if trace.exists() else None,'run_record_sha256':sha(DATA/(name+'.run.json'))}
 if out.exists():
  if sha(SOURCES['AerialCity'],3840*1920*3//2*job['frames'])!=source_hash:raise RuntimeError('source changed since encoding: '+name)
  q=json.loads(out.read_text(encoding='utf8'))
  if q.get('evaluation_signature')!=signature:raise RuntimeError('cached assessment provenance differs: '+name)
  if q['reconstruction_sha256']!=sha(str(p)+'.yuv') or q.get('bitstream_sha256')!=sha(str(p)+'.vvc') or not q['decode_matches']:raise RuntimeError('cached assessment input differs: '+name)
  return q
 expected_recon_bytes=3840*1920*3*job['frames']
 if Path(str(p)+'.yuv').stat().st_size!=expected_recon_bytes:raise RuntimeError('encoder reconstruction size differs: '+name)
 dec=DATA/(name+'.decoded.yuv');log=DATA/(name+'.decode.log')
 if dec.exists():raise RuntimeError('decode already exists: '+name)
 cmd=[str(DEC),'-b',str(p)+'.vvc','-o',str(dec)]
 with log.open('w',encoding='utf8') as f:code=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
 if code:raise RuntimeError('decoder failed '+name)
 if dec.stat().st_size!=expected_recon_bytes:raise RuntimeError('decoder reconstruction size differs: '+name)
 q=quality(SOURCES['AerialCity'],str(p)+'.yuv',3840,1920,job['frames'])
 if q['source_prefix_sha256']!=source_hash:raise RuntimeError('source changed since encoding: '+name)
 decoded_hash=sha(dec)
 if decoded_hash!=q['reconstruction_prefix_sha256'] or decoded_hash!=job['outputs_sha256'][str(p)+'.yuv']:raise RuntimeError('decoder or encoder reconstruction differs '+name)
 bitstream_hash=sha(str(p)+'.vvc')
 if bitstream_hash!=job['outputs_sha256'][str(p)+'.vvc']:raise RuntimeError('bitstream changed since encoding: '+name)
 q.update(name=name,actual_bps=Path(str(p)+'.vvc').stat().st_size*8*30/job['frames'],target_bps=job['target_bps'],elapsed_seconds=job['elapsed_seconds'],decoder_command=cmd,decoder_sha256=sha(DEC),reconstruction_sha256=decoded_hash,decode_matches=True,bitstream_sha256=bitstream_hash)
 q['evaluation_signature']=signature
 q['rate_error_percent']=100*(q['actual_bps']/q['target_bps']-1)
 trace=Path(str(p)+'.sibrc.csv')
 if trace.exists():
  with trace.open() as f:rows=list(csv.DictReader(f))
  q['actions']={str(i):sum(int(r['offset'])==i for r in rows) for i in range(-2,3)}
  q['fallback_ctus']=sum(int(r['fallback']) for r in rows)
  q['ctus']=len(rows)
 out.write_text(json.dumps(q,indent=2),encoding='utf8');print('EVALUATED',name,q['mean_y_wspsnr'],flush=True);return q
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['smoke','main']);a=p.parse_args()
 jobs=json.loads((DATA/(a.stage+'_results.json')).read_text(encoding='utf8'))
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(assess,jobs))
 anchor=[q for q in results if '_anchor_' in q['name']];full=[q for q in results if '_full_' in q['name']]
 report={'points':results}
 for key in ('mean_y_wspsnr','mean_y_psnr'):
  report[key+'_bd_rate_percent']=bd_rate([q[key] for q in anchor],[q['actual_bps'] for q in anchor],[q[key] for q in full],[q['actual_bps'] for q in full])
 (DATA/(a.stage+'_assessment.json')).write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in report.items() if k!='points'}),flush=True)
