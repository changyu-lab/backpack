"""Zhao SPL2022 saliency on coding-domain ORIGINAL (pre-TF) YUV420.
DC/AC equal weights, previous original reference, minmax normalization and
edge replication to complete 4x4 blocks are explicitly engineering conventions.
"""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from scipy.fft import dctn, idctn


def normalize(a):
    lo, hi = float(a.min()), float(a.max())
    return np.zeros_like(a) if hi-lo <= 1e-12 * max(1., abs(hi)) else (a-lo)*(255./(hi-lo))


def blocks(y):
    h,w=y.shape
    p=np.pad(y,((0,(-h)%4),(0,(-w)%4)),mode='edge')
    return p.reshape(p.shape[0]//4,4,p.shape[1]//4,4).transpose(0,2,1,3)


def local_saliency(y, gamma_dc=.5, gamma_ac=.5):
    c=dctn(blocks(y),axes=(-2,-1),norm='ortho').reshape((y.shape[0]+3)//4,(y.shape[1]+3)//4,16)
    h,w=c.shape[:2]
    result=np.zeros((h,w)); count=np.zeros((h,w))
    # Nine vectorized shifts include the zero-valued center difference.
    for dy in (-1,0,1):
        for dx in (-1,0,1):
            a=(slice(max(0,-dy),min(h,h-dy)),slice(max(0,-dx),min(w,w-dx)))
            b=(slice(max(0,dy),min(h,h+dy)),slice(max(0,dx),min(w,w+dx)))
            delta=c[a]-c[b]
            result[a]+=gamma_dc*np.abs(delta[:,:,0])+gamma_ac*np.sqrt(np.sum(delta[:,:,1:]**2,axis=2))
            count[a]+=1
    return result/count


def extract(y, previous, ctu=128, gamma_dc=.5, gamma_ac=.5):
    if ctu<=0 or ctu%4: raise ValueError('CTU must be positive and divisible by four')
    y=np.asarray(y,dtype=np.float64)
    if previous is not None and previous.shape!=y.shape: raise ValueError('reference dimensions mismatch')
    g=idctn(np.sign(dctn(y,norm='ortho')),norm='ortho')**2
    ss=.5*blocks(normalize(g)).mean(axis=(-2,-1))+.5*normalize(local_saliency(y,gamma_dc,gamma_ac))
    st=np.zeros_like(ss) if previous is None else blocks((y-previous)**2).mean(axis=(-2,-1))
    h,w=y.shape; spatial=[]; temporal=[]; centers=[]
    for cy in range(0,h,ctu):
        for cx in range(0,w,ctu):
            z=(slice(cy//4,(min(cy+ctu,h)+3)//4),slice(cx//4,(min(cx+ctu,w)+3)//4))
            spatial.append(ss[z].mean()); temporal.append(st[z].mean())
            centers.append((cy+min(cy+ctu,h))/2.)
    spatial=normalize(np.array(spatial)); temporal=normalize(np.array(temporal))
    joint=.5*(spatial+temporal)
    region=(np.abs(np.array(centers)-h/2.)<.6*h/2.) & (joint>joint.mean())
    return np.column_stack((spatial,temporal,joint,region))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--width',type=int,required=True); p.add_argument('--height',type=int,required=True)
    p.add_argument('--bitdepth',type=int,choices=[8,10],required=True); p.add_argument('--frames',type=int,required=True)
    p.add_argument('--ctu',type=int,default=128); p.add_argument('--skip',type=int,default=0)
    p.add_argument('--gamma-dc',type=float,default=.5); p.add_argument('--gamma-ac',type=float,default=.5)
    a=p.parse_args()
    if min(a.width,a.height,a.frames)<=0 or a.width%2 or a.height%2 or a.skip<0: p.error('invalid YUV420 dimensions/count/skip')
    if not all(np.isfinite(v) and v>=0 for v in (a.gamma_dc,a.gamma_ac)) or a.gamma_dc+a.gamma_ac<=0: p.error('invalid weights')
    dtype=np.dtype('u1' if a.bitdepth==8 else '<u2'); pixels=a.width*a.height
    frame_bytes=pixels*3//2*dtype.itemsize
    if a.input.stat().st_size < (a.skip+a.frames)*frame_bytes: p.error('truncated input')
    a.output.mkdir(parents=True,exist_ok=True)
    previous=None; digest=hashlib.sha256(); start=time.perf_counter(); cpu=time.process_time()
    with a.input.open('rb') as stream:
        stream.seek(a.skip*frame_bytes)
        for poc in range(a.frames):
            raw=stream.read(frame_bytes); digest.update(raw)
            y=np.frombuffer(raw,dtype=dtype,count=pixels).reshape(a.height,a.width).astype(np.float64)
            if y.max()>2**a.bitdepth-1: raise ValueError('input sample exceeds bitdepth')
            features=extract(y,previous,a.ctu,a.gamma_dc,a.gamma_ac)
            with (a.output/f'poc_{poc}.csv').open('w',newline='',encoding='ascii') as f:
                f.write(f'# zhao2022 width={a.width} height={a.height} ctu={a.ctu} poc={poc}\n')
                writer=csv.writer(f); writer.writerow(['poc','ctu_addr','x','y','SS','ST','SST','region'])
                cols=(a.width+a.ctu-1)//a.ctu
                for addr,(ss,st,sst,r) in enumerate(features):
                    writer.writerow([poc,addr,addr%cols*a.ctu,addr//cols*a.ctu,format(ss,'.17g'),format(st,'.17g'),format(sst,'.17g'),int(r)])
            previous=y
            print(f'POC {poc}: CTUs={len(features)} demand={int(features[:,3].sum())}',flush=True)
    manifest={k:str(v) if isinstance(v,Path) else v for k,v in vars(a).items()}
    manifest.update(input_processed_prefix_sha256=digest.hexdigest(),wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,
        domain='coding-domain original before temporal filter',reference='previous original; first selected frame ST=0',
        neighborhood='center plus available eight neighbors; NL=9 interior',gamma_source='engineering equal weights; reference25 unavailable',
        transform='DCT-II/IDCT orthonormal float64',boundary='edge replicate incomplete 4x4; clipped CTU center; actual blocks',
        normalization='minmax [0,255], constant zero',version=1)
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')

if __name__=='__main__': main()
