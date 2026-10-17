"""Deterministic synthetic closed-loop experiment, with four rates and decoder checks."""
import argparse,csv,hashlib,json,math,subprocess,time
from pathlib import Path
import numpy as np
from test_closed_loop import SERIAL

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def generate(path,frames,width,height):
    yy,xx=np.mgrid[:height,:width]
    cy,cx=np.mgrid[:height//2,:width//2]
    with Path(path).open('wb') as f:
        for t in range(frames):
            lum=100+35*np.sin((xx+2*t)/11)+25*np.cos((yy-t)/8)+((xx//8+yy//8)%2)*25
            lum+=((xx*17+yy*13)%23)-11
            moving=((xx-(t*3)%(width+40)+20)**2+(yy-height//2)**2)<24**2
            lum[moving]+=45
            u=128+20*np.sin((cx+t)/13)+np.zeros_like(cy)
            v=128+16*np.cos((cy-t)/17)+np.zeros_like(cx)
            for plane in (lum,u,v): f.write(np.clip(np.round(plane),0,255).astype(np.uint8).tobytes())

def validate(trace,frames):
    rows=list(csv.DictReader(Path(trace).open()))
    pics=[];pending=None;next_ctu=0;seq_left=None
    qps=[];lambdas=[];minimum=0
    for r in rows:
        event=r['event']; key=(int(r['poc']),int(r['ctu']))
        if event=='begin':
            assert pending is None and next_ctu==0
            if seq_left is None: seq_left=int(r['seq_left'])
        elif event=='decision':
            assert pending is None and key[1]==next_ctu,(event,key,next_ctu)
            pending=(key,int(r['pic_left']))
            qps.append(int(r['qp'])); lambdas.append(float(r['lambda']))
            assert math.isfinite(lambdas[-1]) and lambdas[-1]>0
        elif event=='feedback':
            assert pending and pending[0]==key
            assert int(r['pic_left'])==pending[1]-int(r['bits'])
            minimum=min(minimum,int(r['pic_left']))
            pending=None;next_ctu+=1
        elif event=='picture':
            assert pending is None and next_ctu>0
            assert int(r['seq_left'])==seq_left-int(r['bits'])
            seq_left=int(r['seq_left']); pics.append(r);next_ctu=0
    assert len(pics)==frames and pending is None
    return dict(frames=len(pics),rc_bits=sum(int(r['bits']) for r in pics),sequence_remaining_bits=seq_left,
                minimum_ctu_remaining_bits=minimum,qp_min=min(qps),qp_max=max(qps),
                lambda_min=min(lambdas),lambda_max=max(lambdas),ctu_decisions=len(qps))

def run(args,folder,clip,rate,label):
    stream=folder/(label+'.vvc'); trace=folder/(label+'.csv');rec=folder/(label+'.yuv')
    command=[str(args.encoder),'--preset','faster','-s',f'{args.width}x{args.height}','-fr','30',
             '-f',str(args.frames),'-i',str(clip),'-b',str(stream),'-o',str(rec),
             '--GOPSize=8','--PicReordering=0','--POC0IDR=1','--DecodingRefreshType=0','--IntraPeriod=-1',
             '--OutputBitDepth=10','--VTMTargetBitrate='+str(rate),'--VTMRCTrace='+str(trace)]+SERIAL
    start=time.monotonic();result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (folder/(label+'.log')).write_text(result.stdout,encoding='utf-8')
    if result.returncode: raise RuntimeError(result.stdout[-5000:])
    stats=validate(trace,args.frames);stats.update(target_bps=rate,seconds=time.monotonic()-start,
        rc_bps=stats['rc_bits']*30/args.frames,annex_b_bps=stream.stat().st_size*8*30/args.frames,
        stream_sha256=sha(stream),trace_sha256=sha(trace),command=command)
    stats['error_percent']=100*(stats['rc_bps']/rate-1)
    orig=np.fromfile(clip,dtype=np.uint8).reshape(args.frames,-1)[:,:args.width*args.height].astype(np.float64)
    recon=np.fromfile(rec,dtype=np.uint16).reshape(args.frames,-1)[:,:args.width*args.height].astype(np.float64)/4
    mse=float(np.mean((orig-recon)**2));stats['psnr_y_db']=10*math.log10(255**2/mse)
    if args.decoder:
        decoded=folder/(label+'.decoded.yuv')
        decoder_command=[str(args.decoder),'-b',str(stream),'-o',str(decoded)]
        decoded_result=subprocess.run(decoder_command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (folder/(label+'.decode.log')).write_text(decoded_result.stdout,encoding='utf-8')
        assert decoded_result.returncode==0,decoded_result.stdout[-3000:]
        assert decoded.stat().st_size==rec.stat().st_size
        assert sha(decoded)==sha(rec),'Decoder output differs from encoder reconstruction'
        stats['decode_matches_reconstruction']=True
    return stats

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--encoder',type=Path,required=True)
    parser.add_argument('--decoder',type=Path);parser.add_argument('--output',type=Path,default=Path('build-vtmrc/smoke'))
    parser.add_argument('--frames',type=int,default=129);parser.add_argument('--width',type=int,default=256)
    parser.add_argument('--height',type=int,default=192);parser.add_argument('--rates',type=int,nargs='+',default=[30000,60000,120000,240000])
    args=parser.parse_args();args.encoder=args.encoder.resolve();args.output.mkdir(parents=True,exist_ok=True)
    clip=args.output/'synthetic.yuv';generate(clip,args.frames,args.width,args.height)
    all_results=[]
    for rate in args.rates:
        result=run(args,args.output,clip,rate,'rate_'+str(rate));all_results.append(result)
        print(json.dumps({k:result[k] for k in ['target_bps','rc_bps','error_percent','psnr_y_db','qp_min','qp_max'] }),flush=True)
    repeat=run(args,args.output,clip,args.rates[-1],'repeat_'+str(args.rates[-1]))
    deterministic=repeat['stream_sha256']==all_results[-1]['stream_sha256'] and repeat['trace_sha256']==all_results[-1]['trace_sha256']
    monotonic=all(b['rc_bps']>a['rc_bps'] and b['psnr_y_db']>=a['psnr_y_db'] for a,b in zip(all_results,all_results[1:]))
    report=dict(clip_sha256=sha(clip),width=args.width,height=args.height,frames=args.frames,frame_rate=30,
                scope='Synthetic low-delay closed-loop test; not a long-sequence convergence claim',
                results=all_results,deterministic=deterministic,rd_monotonic=monotonic)
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    assert deterministic,'Repeated bitstream/trace mismatch'
    assert monotonic,'Four-rate RD monotonicity failed'
    print('PASS: ordered closed-loop budgets, repeated determinism and RD monotonicity',flush=True)
if __name__=='__main__':main()
