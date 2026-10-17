"""Finite CTU-contrast diagnostics; these are not differentiable codec derivatives."""
import numpy as np
from scipy.stats import rankdata

def contrast(better,worse,poc):
 a=np.asarray(better['wsse'],float);b=np.asarray(worse['wsse'],float)
 ar=np.asarray(better['picture_bits'],float);br=np.asarray(worse['picture_bits'],float)
 if a.shape!=b.shape or ar.shape!=a.shape or br.shape!=a.shape or a.ndim!=1 or not 0<=poc<len(a):raise ValueError('frame geometry mismatch')
 if not all(np.all(np.isfinite(x)) for x in [a,b,ar,br]):raise ValueError('nonfinite measurements')
 if not np.array_equal(a[:poc],b[:poc]) or not np.array_equal(ar[:poc],br[:poc]):raise ValueError('pre-probe frames changed')
 now=float(b[poc]-a[poc]);future=float(np.sum(b[poc+1:]-a[poc+1:]));cost=float(ar[poc]-br[poc]);total=float(np.sum(ar-br))
 return {'current_sse_reduction':now,'future_sse_reduction':future,'current_extra_bits':cost,'future_extra_bits':total-cost,'total_extra_bits':total,'amplification':future/now if now>0 else None,'future_benefit_per_current_bit':future/cost if cost>0 else None,'all_frame_sse_reduction':now+future}

def select_ctus(rows,poc,per_group=4):
 lookup={(int(r['poc']),int(r['ctu'])):r for r in rows}
 def available(r):
  if int(r.get('scene_reset',0)):return False
  for back in range(1,int(r['chain'])+1):
   past=lookup.get((poc-back,int(r['ctu'])))
   if past is None or not np.isfinite(float(past['beta'])) or float(past['beta'])<0:return False
   if back<int(r['chain']) and int(past.get('scene_reset',0)):return False
  return True
 eligible=[r for r in rows if int(r['poc'])==poc and int(r['history_valid']) and int(r['bits'])>=32 and available(r)]
 groups={'low':[r for r in eligible if float(r['wt'])<1-1e-9],'neutral':[r for r in eligible if abs(float(r['wt'])-1)<=1e-9],'high':[r for r in eligible if float(r['wt'])>1+1e-9]}
 rng=np.random.default_rng(20261016);selected=[]
 for name,group in groups.items():
  group=sorted(group,key=lambda r:int(r['ctu']))
  if len(group)<per_group:raise ValueError('insufficient weight diversity: '+name+'='+str(len(group)))
  ids=sorted(rng.choice(len(group),per_group,replace=False).tolist())
  selected.extend([dict(group[i],stratum=name) for i in ids])
 return selected

def ranking(weights,response,permutations=19999):
 a=np.asarray(weights,float);b=np.asarray(response,float)
 if len(a)!=len(b) or len(a)<2:raise ValueError('insufficient paired samples')
 if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):raise ValueError('nonfinite ranking data')
 ra=rankdata(a);rb=rankdata(b);ra-=np.mean(ra);rb-=np.mean(rb);den=float(np.linalg.norm(ra)*np.linalg.norm(rb))
 if den==0:return {'spearman':None,'permutation_two_sided_p':None,'n':len(a),'reason':'constant ranks'}
 observed=float(np.dot(ra,rb)/den);rng=np.random.default_rng(20261016);extreme=0
 for _ in range(permutations):extreme+=abs(float(np.dot(ra,rng.permutation(rb))/den))>=abs(observed)-1e-15
 return {'spearman':observed,'permutation_two_sided_p':(extreme+1)/(permutations+1),'n':len(a),'permutations':permutations,'interpretation':'descriptive stratified one-frame sample; no population inference'}
