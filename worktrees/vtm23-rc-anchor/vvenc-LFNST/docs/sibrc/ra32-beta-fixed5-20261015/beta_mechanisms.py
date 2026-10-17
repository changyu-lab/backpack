import json,time,math
from pathlib import Path
import numpy as np
import pandas as pd
OLD=Path('/root/sibrc-ra32-beta-20261015');FIX=Path('/root/sibrc-ra32-beta-fixed5-20261015');BETAS=[2,3,5,8,12,18,20]
KEY=['poc','ctu','kind']
def stats(x):
 x=np.asarray(x,dtype=float);x=x[np.isfinite(x)]
 return dict(n=len(x),mean=float(np.mean(x)),std=float(np.std(x)),q05=float(np.quantile(x,.05)),q50=float(np.quantile(x,.5)),q95=float(np.quantile(x,.95))) if len(x) else dict(n=0)
def corr(a,b):
 a=np.asarray(a,float);b=np.asarray(b,float);m=np.isfinite(a)&np.isfinite(b);a=a[m];b=b[m]
 if len(a)<2 or np.std(a)==0 or np.std(b)==0:return dict(n=len(a),pearson=None,spearman=None)
 return dict(n=len(a),pearson=float(np.corrcoef(a,b)[0,1]),spearman=float(pd.Series(a).corr(pd.Series(b),method='spearman')))
def pred_error(pred,actual):
 pred=np.asarray(pred,float);actual=np.asarray(actual,float);m=np.isfinite(pred)&np.isfinite(actual)&(pred>0)&(actual>0);p=pred[m];a=actual[m]
 return dict(valid_rows=int(sum(m)),excluded_rows=int(len(m)-sum(m)),log_RMSE=float(np.sqrt(np.mean(np.log(p/a)**2))),median_absolute_relative_error=float(np.median(np.abs(p/a-1))),normalized_absolute_error=float(np.sum(np.abs(p-a))/np.sum(a))) if len(p) else dict(valid_rows=0,excluded_rows=len(m))
def analyze(suite,base):
 specs=json.loads((OLD/'sources.json').read_text());out=[]
 for spec in specs:
  for pt in range(1,5):
   b=pd.read_csv(OLD/'runs'/spec['name']/'B5'/('R%d.sibrc.csv'%pt));assert not b.duplicated(KEY).any()
   for beta in BETAS:
    path=(OLD if beta==5 else base)/'runs'/spec['name']/('B'+str(beta))/('R%d.sibrc.csv'%pt)
    d=pd.read_csv(path);assert not d.duplicated(KEY).any();j=d.merge(b,on=KEY,suffixes=('', '_B5'),validate='one_to_one');assert len(j)==len(d)==len(b)
    for kind in ['all','I','P']:
     x=j if kind=='all' else j[j['kind']==kind]
     if len(x)==0:continue
     off=x['offset'].to_numpy();baseoff=x['offset_B5'].to_numpy()
     row=dict(suite=suite,sequence=spec['name'],point=pt,beta=beta,kind=kind,rows=len(x),descriptor=stats(x['feature_C4']),descriptor_correlation_with_B5=corr(x['feature_C4'],x['feature_C4_B5']),offset_agreement=float(np.mean(off==baseoff)),offset_changed=float(np.mean(off!=baseoff)),actual_qp_agreement=float(np.mean(x['actual_qp']==x['actual_qp_B5'])),offset_lower_boundary=float(np.mean(off==-2)),offset_upper_boundary=float(np.mean(off==2)),offset_any_boundary=float(np.mean(np.abs(off)==2)),fallback_rate=float(np.mean(x['fallback']!=0)),online_rate_prediction=pred_error(x['predicted_bits'],x['bits']),online_distortion_prediction=pred_error(x['predicted_sse'],x['weighted_mse']*x['area']))
     out.append(row)
 (FIX/(suite+'-mechanisms.json')).write_text(json.dumps(dict(scope='Matched CTUs in closed-loop encodes; reconstructed references and RC states can differ. Prediction fields include online feedback corrections. Offset boundary rates use configured -2,+2; not feasible-action clipping boundaries.',active_frequency_band_ratio=None,active_frequency_band_ratio_reason='Per-band rho/activation not present in existing traces; cannot recover from aggregate feature.',rows=out),indent=2))
 print('MECHANISMS PASS',suite,len(out),flush=True)
def collection():
 cols=['poc','ctu','kind','actual_qp','bits','weighted_mse','feature_C4'];tables={}
 for beta in BETAS:
  parts=[]
  for record in sorted((OLD/'collect'/('B'+str(beta))).rglob('*.run.json')):
   r=json.loads(record.read_text());d=pd.read_csv(r['prefix']+'.sibrc.csv.gz',usecols=cols)
   d['source_sequence']=r['sequence'];d['window']=r['window'];d['requested_qp']=r['qp'];parts.append(d)
  tables[beta]=pd.concat(parts,ignore_index=True)
 keys=['source_sequence','window','requested_qp','poc','ctu','kind'];b=tables[5];assert not b.duplicated(keys).any();rows=[]
 for beta,d in tables.items():
  j=d.merge(b,on=keys,suffixes=('', '_B5'),validate='one_to_one');assert len(j)==len(d)==len(b)
  assert np.array_equal(j['bits'],j['bits_B5']) and np.array_equal(j['actual_qp'],j['actual_qp_B5']) and np.allclose(j['weighted_mse'],j['weighted_mse_B5'],rtol=0,atol=0)
  for kind in ['I','P']:
   x=j[j['kind']==kind];rows.append(dict(beta=beta,kind=kind,rows=len(x),feature=stats(x['feature_C4']),correlation_B5=corr(x['feature_C4'],x['feature_C4_B5'])))
 (FIX/'collection-descriptor-mechanisms.json').write_text(json.dumps(dict(scope='Same mode2 encoded bitstreams and matched CTU labels across beta; includes all collected rows, not model-valid-only filter',rows=rows,per_band_activation_available=False),indent=2))
 print('COLLECTION MECHANISMS PASS',flush=True)
if __name__=='__main__':
 analyze('recalibrated',OLD);collection()
 while not (FIX/'summary.json').exists():time.sleep(30)
 analyze('fixed5',FIX)
