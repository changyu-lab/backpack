import argparse,csv,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('prefix');p.add_argument('--expect',choices=['safe','unsafe'],default='safe');p.add_argument('--output');a=p.parse_args()
prefix=Path(a.prefix);begins={int(r['poc']):int(r['qp']) for r in csv.DictReader(Path(str(prefix)+'.vtm.csv').open()) if r['event']=='begin'}
previous={};bad=[];outside=[];n=0
for r in csv.DictReader(Path(str(prefix)+'.sibrc.csv').open()):
 if r['kind']!='I':continue
 n+=1;poc=int(r['poc']);qp=begins[poc];prev=previous.get(poc);lo=qp-2;hi=qp+2
 if prev is not None:lo=max(lo,prev-1);hi=min(hi,prev+1)
 if lo>hi:bad.append({'poc':poc,'ctu':int(r['ctu']),'previous_actual_qp':prev,'min_qp':lo,'max_qp':hi})
 applied=int(r['qp']);actual=int(r['actual_qp'])
 if applied<max(-12,qp-2) or applied>min(63,qp+2):outside.append({'poc':poc,'ctu':int(r['ctu']),'applied_qp':applied,'picture_qp':qp})
 if actual>-999:previous[poc]=actual
result={'intra_ctus':n,'invalid_intersections':len(bad),'unsafe_applied_qps':len(outside),'first_invalid':bad[:10],'first_unsafe':outside[:10]}
print(json.dumps(result,indent=2));safe=n>0 and not bad and not outside
if a.output:Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf8')
sys.exit(0 if (safe if a.expect=='safe' else n>0 and not safe) else 1)
