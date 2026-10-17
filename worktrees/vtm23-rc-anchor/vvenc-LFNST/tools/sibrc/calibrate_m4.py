"""Frozen-statistics, matched-row M4 independent R/D calibration (no encoding)."""
import argparse, csv, json, hashlib, math
from pathlib import Path
from collections import Counter
import numpy as np
import calibrate
FEATURES=('C0','C1','C2','C3','C4','plane','geo','satd')
FLOOR=1e-12

def canonical_hash(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def group_key(r): return (r['source_sequence'],int(r['window_start']),int(r['poc']))
def row_key(r): return group_key(r)+(int(r['ctu']),float(r.get('actual_qp',r.get('qp'))),r['kind'],float(r.get('requested_qp',r.get('qp',r.get('actual_qp')))))
def matched_rows(rows):
 seen=set(); result=[]; reasons=Counter()
 for r in rows:
  key=row_key(r)
  if key in seen: raise ValueError('duplicate source/window/POC/CTU/QP/kind key')
  seen.add(key)
  if r['source_sequence'] not in ('DrivingInCity','DrivingInCountry'): raise ValueError('development sources only')
  if r['kind'] not in ('I','P'): raise ValueError('unsupported picture kind')
  if not all(math.isfinite(float(r[k])) and float(r[k])>0 for k in ('bits','weighted_mse')): reasons['invalid_label']+=1; continue
  if not all(math.isfinite(float(r['feature_'+f])) and float(r['feature_'+f])>=0 for f in FEATURES): reasons['invalid_feature']+=1; continue
  if not math.isfinite(key[4]): reasons['invalid_qp']+=1; continue
  result.append(r)
 return sorted(result,key=row_key),dict(reasons)
def split_rows(rows,manifest=None):
 groups=sorted({group_key(r) for r in rows})
 if manifest is None:
  # Independent last window per source; all local POCs and QPs stay together.
  last={s:max(w for ss,w,p in groups if ss==s) for s in {g[0] for g in groups}}
  hold={g for g in groups if g[1]==last[g[0]]}
 else:
  hold={tuple(g) for g in manifest['holdout_groups']}
  if set(map(tuple,manifest['all_groups']))!=set(groups): raise ValueError('split manifest groups differ from matched input')
 train=[r for r in rows if group_key(r) not in hold]; test=[r for r in rows if group_key(r) in hold]
 if not train or not test: raise ValueError('need independent training and holdout windows')
 for kind in {r['kind'] for r in rows}:
  if not any(r['kind']==kind for r in train) or not any(r['kind']==kind for r in test): raise ValueError('each kind requires training and holdout picture groups')
 return train,test

def model_features(qp,raw,scale,floor=FLOOR):
 return calibrate.features(np.asarray(qp),np.maximum(np.asarray(raw)/scale,floor))
def fit_model(train,test,feature,ridge=1e-6):
 raw=np.array([float(r['feature_'+feature]) for r in train]); positive=raw[raw>0]
 scale=float(np.exp(np.mean(np.log(positive)))) if len(positive) else 1.
 q=np.array([float(r.get('actual_qp',r.get('qp'))) for r in train]); normalized=np.maximum(raw/scale,FLOOR)
 # Same preregistered normalized domain for every descriptor, independent of holdout.
 domain=(-12,63,FLOOR,1e6)
 coeff={key:calibrate.fit(q,normalized,np.array([float(r[key]) for r in train]),ridge,monotonic=trend,domain=domain) for key,trend in [('bits','rate'),('weighted_mse','distortion')]}
 diagnostics={}
 for name,rows in [('train',train),('holdout',test)]:
  fq=np.array([float(r.get('actual_qp',r.get('qp'))) for r in rows]); fi=np.array([float(r['feature_'+feature]) for r in rows]); f=model_features(fq,fi,scale)
  errors={k:f@c-np.log([float(r[k]) for r in rows]) for k,c in coeff.items()}
  diagnostics[name]={'samples':len(rows),'groups':len({group_key(r) for r in rows}),'zero_count':int(np.sum(fi==0)),'floor_count':int(np.sum(fi/scale<=FLOOR)),'qp_extrapolation_count':int(np.sum((fq<q.min())|(fq>q.max()))),'log_rmse':{k:float(np.sqrt(np.mean(e*e))) for k,e in errors.items()}}
  extrapolation=(fq<q.min())|(fq>q.max())|(fi<raw.min())|(fi>raw.max())
  diagnostics[name].update(information_extrapolation_count=int(np.sum((fi<raw.min())|(fi>raw.max()))),extrapolation_fraction=float(np.mean(extrapolation)),normalized_constraint_domain_outside_fraction=float(np.mean((fq<domain[0])|(fq>domain[1])|(fi/scale>domain[3]))))
  for field in ('latitude','actual_qp'):
   bins={}
   for index,r in enumerate(rows):
    value=float(r.get(field,r.get('qp',0))); label=str(int(abs(value)//15)*15) if field=='latitude' else str(value)
    bins.setdefault(label,[]).append(index)
   diagnostics[name][field+'_log_rmse']={b:{k:float(np.sqrt(np.mean(e[idx]**2))) for k,e in errors.items()} for b,idx in bins.items()}
 corner=model_features([domain[0],domain[0],domain[1],domain[1]],[domain[2],domain[3],domain[2],domain[3]],1.)
 violations={}
 for key,name,sign in [('bits','rate',-1),('weighted_mse','distortion',1)]:
  c=coeff[key]; derivative=sign*(c[1]+c[3]*corner[:,2]+2*c[5]*corner[:,1]); violations[name]=int(np.sum(derivative<1e-6-1e-9))
 return {'monotonic_violation_count':violations,'scale':scale,'floor':FLOOR,'rate':coeff['bits'].tolist(),'distortion':coeff['weighted_mse'].tolist(),'diagnostics':diagnostics,'qp_support':[float(q.min()),float(q.max())],'raw_information_support':[float(raw.min()),float(raw.max())],'normalized_monotonic_domain':list(domain),'ridge':ridge}

def write_model(path,kind,feature,model):
 lines=['SIBRC_MODEL_V2','picture_type '+kind,'qp_mapping exp2_qp_minus4_over6','feature_selector '+str(FEATURES.index(feature)),'information_scale '+str(model['scale']),'information_floor '+str(model['floor']),'rate_unit ctu_bits','distortion_unit spherical_weighted_mse']
 lines += [key+' '+' '.join(map(str,model[key])) for key in ('rate','distortion')]
 path.write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main():
 p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--stats',required=True); p.add_argument('--output-dir',required=True); p.add_argument('--split-manifest'); p.add_argument('--ridge',type=float,default=1e-6); args=p.parse_args()
 if not math.isfinite(args.ridge) or args.ridge<0: raise ValueError('invalid ridge')
 with open(args.input,newline='',encoding='utf-8-sig') as f: original=list(csv.DictReader(f))
 rows,reasons=matched_rows(original); manifest=json.loads(Path(args.split_manifest).read_text()) if args.split_manifest else None
 train,test=split_rows(rows,manifest); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
 split={'all_groups':sorted({group_key(r) for r in rows}),'holdout_groups':sorted({group_key(r) for r in test})}; (out/'split.json').write_text(json.dumps(split,indent=2))
 common={'sample_key_sha256':canonical_hash([row_key(r) for r in rows]),'train_key_sha256':canonical_hash([row_key(r) for r in train]),'holdout_key_sha256':canonical_hash([row_key(r) for r in test]),'split_sha256':canonical_hash(split),'stats_sha256':calibrate.digest(args.stats),'input_sha256':calibrate.digest(args.input),'filter_reasons':reasons,'input_samples':len(original),'matched_samples':len(rows),'arguments':vars(args),'schema':'M4_V2','beta':5,'split_protocol':'last independent window per source; source/window/POC grouped across all QPs','scale_protocol':'train-only positive geometric mean; normalized floor','refit_all':False}
 models={}; equivalence={}
 for kind in ('I','P'):
  tr=[r for r in train if r['kind']==kind]; te=[r for r in test if r['kind']==kind]
  if len(tr)<6 or not te: raise ValueError('need six train rows and holdout for '+kind)
  models[kind]={}
  for feature in FEATURES:
   model=fit_model(tr,te,feature,args.ridge); models[kind][feature]=model; directory=out/feature; directory.mkdir(exist_ok=True); path=directory/('model.'+kind); write_model(path,kind,feature,model)
   (directory/('model.'+kind+'.json')).write_text(json.dumps(dict(common,kind=kind,feature=feature,feature_selector=FEATURES.index(feature),**model),indent=2))
  a,b=models[kind]['C2'],models[kind]['C3']; qr=[float(r.get('actual_qp',r.get('qp'))) for r in tr+te]
  fa=model_features(qr,[float(r['feature_C2']) for r in tr+te],a['scale']); fb=model_features(qr,[float(r['feature_C3']) for r in tr+te],b['scale'])
  differences={k:float(np.max(np.abs(fa@a[k]-fb@b[k]))) for k in ('rate','distortion')}
  equivalence[kind]={'scale_ratio':a['scale']/b['scale'],'max_standardized_feature_difference':float(np.max(np.abs(fa-fb))),'max_log_prediction_difference':differences,'prediction_gate_pass':max(differences.values())<=1e-8,'controller_replay_required':True}
 (out/'provenance.json').write_text(json.dumps(common,indent=2)); (out/'equivalence.json').write_text(json.dumps(equivalence,indent=2))
if __name__=='__main__': main()



