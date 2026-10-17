"""ERP luma quality and BD-rate, with no quality-range extrapolation."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
from scipy.interpolate import PchipInterpolator

def bd_rate(q1,r1,q2,r2):
 def curve(q,r):
  q=np.asarray(q,dtype=float); r=np.asarray(r,dtype=float); idx=np.argsort(q); q=q[idx]; r=r[idx]
  if len(q)<2 or not np.all(np.isfinite(q)) or not np.all(np.isfinite(r)) or np.any(r<=0) or np.any(np.diff(q)<=0): raise ValueError('curves require unique finite qualities and positive rates')
  return q,PchipInterpolator(q,np.log(r),extrapolate=False)
 a,pa=curve(q1,r1); b,pb=curve(q2,r2); lo=max(a[0],b[0]); hi=min(a[-1],b[-1])
 if hi<=lo: raise ValueError('quality ranges do not overlap')
 return float(100*np.expm1((pb.integrate(lo,hi)-pa.integrate(lo,hi))/(hi-lo)))

def picture_mse(src,rec):
 d=(np.asarray(src,dtype=float)-np.asarray(rec,dtype=float))**2
 w=np.cos(np.pi*((np.arange(d.shape[0])+.5)/d.shape[0]-.5))
 return float(d.mean()),float(np.sum(d*w[:,None])/(w.sum()*d.shape[1]))

def quality(source,recon,width,height,frames,spherical=True):
 ps=[]; ws=[]; pixels=width*height; chroma= pixels//2
 source_hash=hashlib.sha256(); recon_hash=hashlib.sha256()
 if width%2 or height%2: raise ValueError('420 dimensions must be even')
 with open(source,'rb') as a,open(recon,'rb') as b:
  for _ in range(frames):
   source_luma=a.read(pixels); recon_luma=b.read(pixels*2)
   source_hash.update(source_luma); recon_hash.update(recon_luma)
   x=np.frombuffer(source_luma,dtype=np.uint8); y=np.frombuffer(recon_luma,dtype='<u2')
   if len(x)!=pixels or len(y)!=pixels: raise ValueError('truncated luma frame')
   if np.any(y>1023): raise ValueError('reconstruction outside 10-bit range')
   mse,wmse=picture_mse(x.reshape(height,width),y.reshape(height,width)/4.)
   ps.append(float('inf') if mse==0 else 10*np.log10(255**2/mse)); ws.append(float('inf') if wmse==0 else 10*np.log10(255**2/wmse))
   source_chroma=a.read(chroma); recon_chroma=b.read(chroma*2)
   if len(source_chroma)!=chroma or len(recon_chroma)!=chroma*2: raise ValueError('truncated chroma frame')
   source_hash.update(source_chroma); recon_hash.update(recon_chroma)
 result = {'source_prefix_sha256':source_hash.hexdigest(),'reconstruction_prefix_sha256':recon_hash.hexdigest(),'frames':frames,'mean_y_psnr':float(np.mean(ps)),'mean_y_wspsnr':float(np.mean(ws)),'picture_y_psnr':ps,'picture_y_wspsnr':ws}
 if spherical:
  from spherical_metrics import spherical_quality
  result.update(spherical_quality(source,recon,width,height,frames))
 return result

def main():
 p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
 q=sub.add_parser('quality'); q.add_argument('--source',required=True); q.add_argument('--recon',required=True); q.add_argument('--width',type=int,required=True); q.add_argument('--height',type=int,required=True); q.add_argument('--frames',type=int,required=True); q.add_argument('--bitstream',required=True); q.add_argument('--fps',type=float,required=True); q.add_argument('--output',required=True)
 b=sub.add_parser('bd-rate'); b.add_argument('--anchor',required=True); b.add_argument('--candidate',required=True); b.add_argument('--quality-key')
 a=p.parse_args()
 if a.command=='quality':
  if a.frames<=0 or a.fps<=0: raise ValueError('frames/fps must be positive')
  result=quality(a.source,a.recon,a.width,a.height,a.frames); result['actual_bps']=Path(a.bitstream).stat().st_size*8*a.fps/a.frames; Path(a.output).write_text(json.dumps(result,indent=2))
 else:
  anchor=json.loads(Path(a.anchor).read_text()); candidate=json.loads(Path(a.candidate).read_text())
  keys=[a.quality_key] if a.quality_key else ['mean_y_wspsnr','mean_y_spsnr','mean_y_cpppsnr']
  values={key:bd_rate([x[key] for x in anchor],[x['actual_bps'] for x in anchor],[x[key] for x in candidate],[x['actual_bps'] for x in candidate]) for key in keys}
  print(json.dumps({'bd_rate_percent':values[a.quality_key] if a.quality_key else values}))
if __name__=='__main__': main()
