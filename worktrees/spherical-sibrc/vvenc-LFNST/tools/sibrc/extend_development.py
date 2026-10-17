"""Prespecified development-only extension after fit-domain diagnostics."""
import csv,json,subprocess
from pathlib import Path
from run_local import DATA,ROOT,PY,job,execute
if __name__=='__main__':
 jobs=[job('collect_extended_'+s+'_QP'+str(q),s,16,6400000,2,q) for q in (42,47,52,17) for s in ('DrivingInCity','DrivingInCountry')]
 (DATA/'extended_development_jobs.json').write_text(json.dumps(jobs,indent=2),encoding='utf8')
 results=[execute(j) for j in jobs]
 (DATA/'extended_development_results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
 with (DATA/'development_samples.csv').open() as f:rows=list(csv.DictReader(f))
 for j in jobs:
  with (DATA/(j['name']+'.sibrc.csv')).open() as f:
   for r in csv.DictReader(f):r['source_sequence']=j['source_sequence'];r['sequence']=j['source_sequence'];r['run_id']=j['name'];rows.append(r)
 samples=DATA/'extended_development_samples.csv'
 with samples.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 modeldir=DATA/'extended-calibration';modeldir.mkdir(exist_ok=True)
 for kind in ('I','P'):
  for variant in ('unconstrained','monotonic'):
   cmd=[PY,str(ROOT/'tools/sibrc/calibrate.py'),'model','--input',str(samples),'--metadata',str(DATA/'development_metadata.json'),'--kind',kind,'--equator-degrees','15','--output',str(modeldir/(variant+'.'+kind))]
   if variant=='monotonic':cmd+=['--monotonic','--monotonic-domain','-12','63','1e-12','36459']
   subprocess.run(cmd,check=True)
 print('PASS extended development calibration; no evaluation sequence used',flush=True)
