"""Frozen expanded-development candidate; preserve all previous results."""
import json,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import run_local as runner
import assess_local as assessment
from evaluate import bd_rate
OLD=runner.DATA
NEW=Path('I:/vvenc-LFNST/.worktrees/sibrc-expanded-20261010')
if __name__=='__main__':
 if NEW.exists():raise RuntimeError('use a fresh candidate output directory')
 NEW.mkdir()
 for kind in ('I','P'):
  shutil.copyfile(OLD/('extended-calibration/final.'+kind),NEW/('model.'+kind))
  shutil.copyfile(OLD/('extended-calibration/final.'+kind+'.json'),NEW/('model.'+kind+'.json'))
 shutil.copyfile(OLD/'stats.txt',NEW/'stats.txt')
 shutil.copyfile(OLD/'extended-calibration/comparison.json',NEW/'development_comparison.json')
 runner.DATA=NEW;assessment.DATA=NEW
 jobs=[runner.job('smoke_full_R'+str(i),'AerialCity',16,r,3,recon=True) for i,r in enumerate(runner.RATES,1)]
 (NEW/'jobs.json').write_text(json.dumps(jobs,indent=2),encoding='utf8')
 with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(runner.execute,jobs))
 (NEW/'results.json').write_text(json.dumps(records,indent=2),encoding='utf8')
 with ThreadPoolExecutor(max_workers=2) as pool:points=list(pool.map(assessment.assess,records))
 anchor=[q for q in json.loads((OLD/'smoke_assessment.json').read_text())['points'] if '_anchor_' in q['name']]
 original=json.loads((OLD/'smoke_results.json').read_text())
 for q in anchor:
  ref=next(j for j in original if j['name']==q['name'])
  if runner.sha(OLD/(q['name']+'.vvc'))!=q['bitstream_sha256']:raise RuntimeError('baseline bitstream differs')
  if ref['asset_hashes'][str(runner.EXE)]!=records[0]['asset_hashes'][str(runner.EXE)]:raise RuntimeError('baseline encoder differs')
  if ref['raw_input']['coded_prefix_sha256']!=records[0]['raw_input']['coded_prefix_sha256']:raise RuntimeError('baseline source differs')
 report={'anchor_source':str(OLD/'smoke_assessment.json'),'points':anchor+points,'candidate':'expanded-development, monotonic, refit-all; unchanged coding engine/statistics/controller'}
 for key in ('mean_y_wspsnr','mean_y_psnr'):
  report[key+'_bd_rate_percent']=bd_rate([q[key] for q in anchor],[q['actual_bps'] for q in anchor],[q[key] for q in points],[q['actual_bps'] for q in points])
 (NEW/'assessment.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in report.items() if k!='points'}),flush=True)
