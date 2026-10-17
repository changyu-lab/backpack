"""Independent SIBRC calibration. Residual input: little-endian float64 N x32x32."""
import argparse, csv, json, hashlib
from pathlib import Path
import numpy as np
from scipy.fft import dctn

ANGLES=(0,15,30,45,60,75,85)

def area_resample(a,m):
 edges=np.arange(m+1)*32/m
 w=np.maximum(0,np.minimum(edges[1:,None],np.arange(32)[None,:]+1)-np.maximum(edges[:-1,None],np.arange(32)[None,:]))/(32/m)
 return np.asarray(a)@w.T

def statistics(blocks,angle):
 m=max(1,int(np.floor(32*np.cos(np.deg2rad(angle))+.5)))
 x=dctn(blocks,type=2,norm='ortho',axes=(-2,-1))/32
 y=dctn(area_resample(blocks,m),type=2,norm='ortho',axes=(-2,-1))/np.sqrt(32*m)
 xx=x[:,:,:m]; xc=xx-xx.mean(axis=0); yc=y-y.mean(axis=0)
 vx=np.mean(xc*xc,axis=0); vy=np.mean(yc*yc,axis=0); cov=np.mean(xc*yc,axis=0)
 rho=np.zeros((32,32)); gain=rho.copy()
 valid=(vx>1e-24)&(vy>1e-24)
 rho[:,:m]=np.minimum(np.divide(cov*cov,vx*vy,out=np.zeros_like(vx),where=valid),1-1e-6)
 gain[:,:m]=np.clip(np.divide(vy,vx,out=np.zeros_like(vx),where=vx>1e-24),0,1000)
 return rho,gain

def features(qp,info):
 x=(np.asarray(qp)-4)*np.log(2)/6; z=np.log(np.maximum(info,1e-12))
 return np.column_stack((np.ones_like(x),x,z,x*z,z*z,x*x))

def fit(qp,info,value,ridge=1e-6,monotonic=None,domain=None):
 f=features(qp,info); scale=np.sqrt(np.mean(f*f,axis=0)); scale=np.maximum(scale,1e-12)
 a=f/scale; b=np.log(value)
 penalty=np.eye(6)*np.sqrt(ridge); penalty[0,0]=0
 aa=np.vstack((a,penalty)); bb=np.concatenate((b,np.zeros(6)))
 unconstrained=np.linalg.lstsq(aa,bb,rcond=None)[0]
 if monotonic is None: return unconstrained/scale
 if monotonic not in ('rate','distortion'): raise ValueError('monotonic must be rate or distortion')
 sign=-1 if monotonic=='rate' else 1
 if domain is None: domain=(float(np.min(qp)),float(np.max(qp)),float(np.min(info)),float(np.max(info)))
 qlo,qhi,ilo,ihi=domain
 if not np.all(np.isfinite(domain)) or qlo>qhi or ilo>ihi or ilo<0: raise ValueError('invalid monotonic domain')
 x=np.array([qlo,qlo,qhi,qhi]); z=np.array([ilo,ihi,ilo,ihi]); corners=features(x,z)
 # Derivative is affine in x,z, so the four corners cover the rectangle exactly.
 derivative=np.column_stack((np.zeros(4),np.ones(4),np.zeros(4),corners[:,2],np.zeros(4),2*corners[:,1]))
 constraint=sign*derivative/scale; margin=1e-6
 # Six variables and four affine inequalities form a small convex QP.
 # Enumerating the 16 possible active sets avoids line-search failures.
 hessian=(aa.T@aa)/len(bb); linear=(aa.T@bb)/len(bb)
 norms=np.maximum(np.linalg.norm(constraint,axis=1),1e-12)
 normalized=constraint/norms[:,None]; bounds=np.full(4,margin)/norms
 best=None; best_cost=float('inf')
 for mask in range(16):
  active=[j for j in range(4) if mask&(1<<j)]
  if active:
   ac=normalized[active]
   matrix=np.block([[hessian,-ac.T],[ac,np.zeros((len(active),len(active)))]])
   rhs=np.concatenate((linear,bounds[active]))
   try: solution=np.linalg.solve(matrix,rhs)
   except np.linalg.LinAlgError: solution=np.linalg.lstsq(matrix,rhs,rcond=None)[0]
   if np.max(np.abs(matrix@solution-rhs))>1e-8*(1+np.max(np.abs(rhs))): continue
   candidate=solution[:6]
   if np.min(solution[6:])<-1e-8: continue
  else: candidate=unconstrained
  if not np.all(np.isfinite(candidate)) or np.min(constraint@candidate)<margin-1e-9: continue
  cost=float(np.sum((aa@candidate-bb)**2))
  if cost<best_cost: best=candidate; best_cost=cost
 if best is None: raise ValueError('constrained fit failed: no feasible KKT active set')
 return best/scale

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
 p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
 s=sub.add_parser('stats'); s.add_argument('--input',required=True); s.add_argument('--metadata',required=True); s.add_argument('--output',required=True)
 s.add_argument('--residual-scale',type=float,default=1,help='multiply residuals to 8-bit units; 10-bit uses 0.25')
 r=sub.add_parser('model'); r.add_argument('--refit-all',action='store_true'); r.add_argument('--monotonic',action='store_true'); r.add_argument('--monotonic-domain',nargs=4,type=float,metavar=('QP_MIN','QP_MAX','I_MIN','I_MAX'));  r.add_argument('--input',required=True); r.add_argument('--metadata',required=True); r.add_argument('--output',required=True); r.add_argument('--kind',choices=['I','P'],required=True); r.add_argument('--ridge',type=float,default=1e-6); r.add_argument('--holdout-fraction',type=float,default=.25); r.add_argument('--equator-degrees',type=float,default=90)
 args=p.parse_args(); meta=json.loads(Path(args.metadata).read_text(encoding='utf-8-sig'))
 if not meta.get('sequences') or any(x not in ('DrivingInCity','DrivingInCountry') for x in meta['sequences']): raise ValueError('metadata sequences must contain development sequences only')
 provenance={'source_sha256':digest(args.input),'source_metadata':meta,'arguments':vars(args)}
 if args.command=='stats':
  raw=np.fromfile(args.input,dtype='<f8')
  if raw.size%1024 or raw.size<2048 or not np.all(np.isfinite(raw)): raise ValueError('need at least two finite complete residual blocks')
  blocks=raw.reshape(-1,32,32)*args.residual_scale
  with open(args.output,'w') as out:
   out.write('SIBRC_STATS_V1\n7\n')
   for angle in ANGLES:
    rho,g=statistics(blocks,angle); out.write(str(angle)+'\n'); np.savetxt(out,np.column_stack((rho.ravel(),g.ravel())),fmt='%.17g')
  provenance.update(raw_samples=len(blocks),rho2_cap=.999999,gain_cap=1000,normalization='orthonormal DCT-II / sqrt(pixels)',holdout='none: paired population statistics',equator_regularization='perfect rho² capped at 1-1e-6')
 else:
  with open(args.input,newline='') as f: rows=list(csv.DictReader(f))
  for row in rows:
   source=row.get('source_sequence') or row.get('sequence')
   if source not in ('DrivingInCity','DrivingInCountry') or source not in meta['sequences']: raise ValueError('every CSV row must identify an allowed development source_sequence (or exact sequence name)')
   row['_source']=source
  domain_rows=[row for row in rows if row['kind']==args.kind and float(row['bits'])>0 and float(row['weighted_mse'])>0]
  monotonic_domain=args.monotonic_domain
  if args.monotonic and monotonic_domain is None:
   if not domain_rows: raise ValueError('no development samples for constraint domain')
   dq=[float(row['qp']) for row in domain_rows]; di=[float(row['ieff']) for row in domain_rows]; monotonic_domain=[min(dq),max(dq),min(di),max(di)]
  rows=[row for row in rows if row['kind']==args.kind and abs(float(row.get('latitude',0)))<=args.equator_degrees and float(row['bits'])>0 and float(row['weighted_mse'])>0]
  if len(rows)<12: raise ValueError('insufficient positive samples')
  # Keep all QPs/runs for one source picture on the same side of holdout.
  groups=sorted({(row['_source'],int(row['poc'])) for row in rows})
  if len(groups)<2: raise ValueError('need at least two whole-picture groups')
  if not 0<args.holdout_fraction<1: raise ValueError('holdout fraction must lie in (0,1)')
  hold=set(groups[-max(1,int(np.ceil(len(groups)*args.holdout_fraction))):])
  train=[r for r in rows if (r['_source'],int(r['poc'])) not in hold]; test=[r for r in rows if (r['_source'],int(r['poc'])) in hold]
  q=np.array([float(r['qp']) for r in train]); i=np.array([float(r['ieff']) for r in train])
  if len(train)<6: raise ValueError('need six training samples')
  coeff=[fit(q,i,np.array([float(r[key]) for r in train]),args.ridge,monotonic=('rate' if key=='bits' else 'distortion') if args.monotonic else None,domain=monotonic_domain) for key in ('bits','weighted_mse')]
  ftest=features(np.array([float(r['qp']) for r in test]),np.array([float(r['ieff']) for r in test]))
  if args.monotonic: provenance['monotonic_constraint']={'domain_qp_information':monotonic_domain,'derivative_margin':1e-6,'domain_source':'explicit CLI' if args.monotonic_domain else 'all allowed development input before latitude filter','method':'convex ridge least squares; exhaustive four-constraint KKT active sets'}
  provenance.update(train_samples=len(train),holdout_samples=len(test),holdout_groups=sorted(hold),qp_domain=[float(q.min()),float(q.max())],information_domain=[float(i.min()),float(i.max())],holdout_log_rmse={key:float(np.sqrt(np.mean((ftest@c-np.log([float(r[key]) for r in test]))**2))) for key,c in zip(('bits','weighted_mse'),coeff)})
  if args.refit_all:
   # Freeze diagnostics before any formerly held-out rows enter the final objective.
   provenance['holdout_metrics_before_refit']=dict(provenance['holdout_log_rmse'])
   provenance['holdout_coefficients_before_refit']={'rate':coeff[0].tolist(),'distortion':coeff[1].tolist()}
   final_q=np.array([float(row['qp']) for row in rows]); final_i=np.array([float(row['ieff']) for row in rows])
   coeff=[fit(final_q,final_i,np.array([float(row[key]) for row in rows]),args.ridge,monotonic=('rate' if key=='bits' else 'distortion') if args.monotonic else None,domain=monotonic_domain) for key in ('bits','weighted_mse')]
   provenance.update(final_fit_samples=len(rows),final_qp_domain=[float(final_q.min()),float(final_q.max())],final_information_domain=[float(final_i.min()),float(final_i.max())],final_model_validation='held-out metrics apply to pre-refit model only; final coefficients use all latitude-selected development samples')
  lines=['SIBRC_MODEL_V1','picture_type '+args.kind,'qp_mapping exp2_qp_minus4_over6','information_floor 1e-12','rate_unit ctu_bits','distortion_unit spherical_weighted_mse']
  lines+=['rate '+' '.join(map(str,coeff[0])),'distortion '+' '.join(map(str,coeff[1]))]
  Path(args.output).write_text('\n'.join(lines)+'\n')
 Path(args.output+'.json').write_text(json.dumps(provenance,indent=2))

if __name__=='__main__': main()
