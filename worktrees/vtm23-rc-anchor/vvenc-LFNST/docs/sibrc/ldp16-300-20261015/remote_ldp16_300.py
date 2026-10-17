"""Isolated Linux C4 screening. Own-platform Anchor, frozen models, no result editing."""
import gzip, csv, hashlib, json, math, os, re, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import psutil

BASE=Path('/root/sibrc-ldp16-300-20261015')
INPUT=Path('/dev/shm/sibrc-ldp16-300-input-20261015')
SCRATCH=Path('/dev/shm/sibrc-ldp16-300-recon-20261015');SCRATCH.mkdir(parents=True,exist_ok=True)
FROZEN=Path('/data/vtmrc-vvenc-tune-20261014')
EXE=FROZEN/'vvenc/bin/release-static/vvencFFapp'
METRIC=FROZEN/'metrics-build/metrics360'
DEC=Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/umake/gcc-11.4/x86_64/release/DecoderApp')
SPHERE=Path('/root/VTM-23.0-paper-scc-rc-anchor-fit/cfg-360Lib/360Lib/sphere_655362.txt')
CFG=BASE/'ldp16.cfg';STATS=FROZEN/'assets/stats.txt';MODEL=FROZEN/'assets/models/C4/model'
sys.path.insert(0,str(FROZEN/'vvenc/tools/sibrc'))
from evaluate import bd_rate
N=300
lock=threading.Condition();reserved=0

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)

def sha(path,limit=None):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        while limit is None or limit>0:
            x=f.read(8388608 if limit is None else min(limit,8388608))
            if not x:break
            h.update(x)
            if limit is not None:limit-=len(x)
    if limit not in (None,0):raise RuntimeError('Truncated input '+str(path))
    return h.hexdigest()

def source(s):return INPUT/s['filename']

def command(s,prefix,rate,offset):
    cmd=[str(EXE),'--preset','faster','-c',str(CFG),'-i',str(source(s)),'-s',f"{s['width']}x{s['height']}",'-fr',str(s['fps']),'-f','300','-b',str(prefix)+'.vvc',
         '--InputBitDepth='+str(s['depth']),'--InternalBitDepth=10','--OutputBitDepth=10','--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0','--VTMTargetBitrate='+str(rate),'--VTMRCTrace='+str(prefix)+'.vtm.csv']
    if rate<0:
        cmd=[x for x in cmd if not x.startswith(('--VTMTargetBitrate=','--VTMRCTrace='))]+['--QP='+str(-rate)]
    if offset is not None:cmd+=['--SIBRCMode=3','--SIBRCStats='+str(STATS),'--SIBRCModel='+str(MODEL),'--SIBRCTrace='+str(prefix)+'.sibrc.csv','--SIBRCFeature=4','--SIBRCMinOffset='+str(offset[0]),'--SIBRCMaxOffset='+str(offset[1])]
    return cmd

def encode(job):
    global reserved
    s,label,point,rate,offset=job;d=BASE/'runs'/s['name']/label;d.mkdir(parents=True,exist_ok=True)
    prefix=d/('R'+str(point));record=prefix.with_suffix('.run.json');cmd=command(s,prefix,rate,offset)
    outputs=[prefix.with_suffix('.vvc'),prefix.with_suffix('.vtm.csv')]
    if rate<0:outputs=outputs[:1]
    if offset is not None:outputs.append(prefix.with_suffix('.sibrc.csv'))
    if record.exists():
        r=json.loads(record.read_text());assert r['verified'] and r['command']==cmd
        assert all(sha(p)==h for p,h in r['outputs_sha256'].items());return r
    if any(p.exists() for p in outputs):raise RuntimeError('Partial output requires inspection '+str(prefix))
    need=4_500_000_000 if s['width']>=8192 else (2_500_000_000 if s['width']>=6144 else 1_500_000_000)
    with lock:
        while reserved+need>36_000_000_000 or psutil.virtual_memory().available<need+1_000_000_000:lock.wait(5)
        reserved+=need
    start=time.perf_counter();peak=0
    try:
        print('START',s['name'],label,point,flush=True)
        with prefix.with_suffix('.log').open('w') as log:
            proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            while proc.poll() is None:
                try:peak=max(peak,psutil.Process(proc.pid).memory_info().rss)
                except psutil.Error:pass
                time.sleep(.5)
        text=prefix.with_suffix('.log').read_text(errors='replace');pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))))
        r=dict(sequence=s['name'],spec=s,label=label,point=point,target_bps=rate,offset=offset,command=cmd,elapsed_seconds=time.perf_counter()-start,peak_rss_bytes=peak,returncode=proc.returncode,pocs=pocs,verified=proc.returncode==0 and pocs==list(range(N)) and 'Total Time:' in text,outputs_sha256={str(p):sha(p) for p in outputs if p.exists()},prefix=str(prefix),platform='Linux')
        r['actual_bps']=outputs[0].stat().st_size*8*s['fps']/N if outputs[0].exists() else 0
        kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
        r['ldp_framekind']=kinds==['I']+['P']*(N-1);r['verified']=r['verified'] and r['ldp_framekind']
        save(record,r);assert r['verified'],text[-2000:]
        if offset is not None:subprocess.run([sys.executable,str(FROZEN/'vvenc/tools/sibrc/verify_intra_contract.py'),str(prefix),'--output',str(prefix)+'.contract.json'],check=True,stdout=subprocess.DEVNULL)
        
        compressed={}
        for f in outputs[1:]:
            z=Path(str(f)+'.gz')
            with f.open('rb') as a,gzip.open(z,'wb',compresslevel=3) as b:shutil.copyfileobj(a,b)
            with gzip.open(z,'rb') as a:
                h=hashlib.sha256()
                for chunk in iter(lambda:a.read(8388608),b''):h.update(chunk)
            assert h.hexdigest()==r['outputs_sha256'][str(f)]
            compressed[str(z)]=sha(z);f.unlink()
        r['original_trace_sha256']={k:v for k,v in r['outputs_sha256'].items() if not k.endswith('.vvc')}
        r['outputs_sha256']={str(outputs[0]):sha(outputs[0]),**compressed};save(record,r)
        print('PASS',s['name'],label,point,flush=True);return r
    finally:
        with lock:reserved-=need;lock.notify_all()

def quality(r):
    s=r['spec'];prefix=Path(r['prefix']);dest=prefix.with_suffix('.quality.json')
    if dest.exists():
        q=json.loads(dest.read_text());assert q['bitstream_sha256']==sha(prefix.with_suffix('.vvc'));return q
    rec=SCRATCH/(s['name']+'-'+r['label']+'-R'+str(r['point'])+'.recon.yuv');assert not rec.exists(),'Partial reconstruction '+str(rec)
    expected=s['width']*s['height']*3*N
    while shutil.disk_usage(SCRATCH).free<expected+700_000_000 or psutil.virtual_memory().available<expected+2_000_000_000:
        print('WAIT RECON MEMORY',flush=True);time.sleep(30)
    try:
        with prefix.with_suffix('.decode.log').open('w') as f:subprocess.run([str(DEC),'-b',str(prefix.with_suffix('.vvc')),'-o',str(rec)],stdout=f,stderr=subprocess.STDOUT,check=True)
        assert rec.stat().st_size==expected
        raw=prefix.with_suffix('.spherical.json')
        subprocess.run([str(METRIC),str(source(s)),str(rec),str(s['width']),str(s['height']),str(N),str(SPHERE),str(raw),'4','all',str(s['depth'])],check=True)
        q=json.loads(raw.read_text());ps=[];ws=[];pixels=s['width']*s['height'];weight=np.cos(np.pi*((np.arange(s['height'])+.5)/s['height']-.5))[:,None]
        with source(s).open('rb') as a,rec.open('rb') as b:
            for k in range(N):
                x=np.frombuffer(a.read(pixels*(2 if s['depth']==10 else 1)),dtype='<u2' if s['depth']==10 else np.uint8).reshape(s['height'],s['width']).astype(float)
                y=np.frombuffer(b.read(pixels*2),dtype='<u2').reshape(s['height'],s['width']).astype(float)
                if s['depth']==8:x*=4
                error=(x-y)**2;mse=error.mean();wmse=(error*weight).sum()/(weight.sum()*s['width'])
                ps.append(10*math.log10(1020**2/mse));ws.append(10*math.log10(1020**2/wmse))
                a.seek(pixels//2*(2 if s['depth']==10 else 1),1);b.seek(pixels,1)
        q.update(picture_y_psnr=ps,picture_y_wspsnr=ws)
        for key in ('psnr','wspsnr','spsnr','cpppsnr'):
            assert len(q['picture_y_'+key])==N and all(math.isfinite(x) for x in q['picture_y_'+key]);q['mean_y_'+key]=float(np.mean(q['picture_y_'+key]))
        bits=[int(x) for x in re.findall(r'POC\s+\d+.*?\)\s+(\d+) bits',prefix.with_suffix('.log').read_text())];assert len(bits)==N and sum(bits)==prefix.with_suffix('.vvc').stat().st_size*8
        q.update(sequence=s['name'],label=r['label'],point=r['point'],frames=N,target_bps=r['target_bps'],actual_bps=r['actual_bps'],bitstream_sha256=sha(prefix.with_suffix('.vvc')),source_prefix_sha256=s['source_prefix_sha256'],reconstruction_sha256=sha(rec),metrics_exe_sha256=sha(METRIC),sphere_sha256=sha(SPHERE),picture_bits=bits,source_bitdepth=s['depth'],fps=s['fps'],cpp_dimensions=[s['width'],s['height']],metric_peak_10bit=1020)
        save(dest,q);print('QUALITY',s['name'],r['label'],r['point'],q['mean_y_spsnr'],flush=True);return q
    finally:
        # Cleanup only this job's own disposable reconstruction after success.
        if dest.exists() and rec.exists():rec.unlink()

def compare(a,b):
    return {k:bd_rate([q['mean_y_'+k] for q in a],[q['actual_bps'] for q in a],[q['mean_y_'+k] for q in b],[q['actual_bps'] for q in b]) for k in ('wspsnr','spsnr','cpppsnr','psnr')}

def export_frames(specs):
    rows=[];errors=[]
    for spec in specs:
        for label in ('anchor','C4'):
            for point in range(1,5):
                prefix=BASE/'runs'/spec['name']/label/('R'+str(point))
                r=json.loads(prefix.with_suffix('.run.json').read_text());q=json.loads(prefix.with_suffix('.quality.json').read_text())
                assert r['verified'] and r['ldp_framekind'] and r['pocs']==list(range(N))
                assert all(sha(Path(f))==h for f,h in r['outputs_sha256'].items())
                assert len(q['picture_bits'])==N and q['bitstream_sha256']==sha(prefix.with_suffix('.vvc'))
                errors.append(dict(sequence=spec['name'],method=label,point=point,target_bps=r['target_bps'],actual_bps=r['actual_bps'],error_percent=100*(r['actual_bps']/r['target_bps']-1)))
                for poc in range(N):
                    row=dict(sequence=spec['name'],method=label,point=point,poc=poc,bits=q['picture_bits'][poc],bitrate_bps=q['picture_bits'][poc]*spec['fps'])
                    row.update({k:q['picture_y_'+k][poc] for k in ('psnr','wspsnr','spsnr','cpppsnr')});rows.append(row)
    for name,data in [('frames.csv',rows),('rate-errors.csv',errors)]:
        with (BASE/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    save(BASE/'final-validation.json',dict(status='PASS',frames_per_stream=N,comparison_streams=16,cqp_streams=8,frame_rows=len(rows),gopsize=16,source_scope='Uploaded exact first 300 frames only; complete upload SHA verified',development_sequences=['DrivingInCountry']))

def main():
    specs=[]
    for path in sorted(INPUT.glob('*.yuv')):
        m=re.fullmatch(r'(.+?)(?:_le)?_(\d+)x(\d+)_(\d+)fps_(8|10)bit_420_erp.yuv',path.name)
        assert m,path
        name,w,h,fps,depth=m.groups();spec=dict(name=name,width=int(w),height=int(h),fps=int(fps),depth=int(depth),filename=path.name)
        spec['source_prefix_sha256']=sha(path,int(w)*int(h)*3//2*N*(2 if int(depth)==10 else 1));specs.append(spec)
    assert len(specs)==2
    save(BASE/'sources.json',specs)
    assets={str(p):sha(p) for p in (EXE,METRIC,DEC,CFG,STATS,Path(str(MODEL)+'.I'),Path(str(MODEL)+'.P'))}
    if (BASE/'frozen-assets.json').exists():assert json.loads((BASE/'frozen-assets.json').read_text())==assets
    else:save(BASE/'frozen-assets.json',assets)
    all_summary={}
    with ThreadPoolExecutor(max_workers=28) as pool:
        cq=list(pool.map(encode,[(spec,'cqp',i,-qp,None) for spec in specs for i,qp in enumerate([37,32,27,22],1)]))
    jobs=[]
    for spec in specs:
        spec['targets']=[round(r['actual_bps']) for r in cq if r['sequence']==spec['name']]
        save(BASE/(spec['name']+'-targets.json'),spec)
        jobs += [(spec,label,i,rate,off) for label,off in [('anchor',None),('C4',[-2,2])] for i,rate in enumerate(spec['targets'],1)]
    with ThreadPoolExecutor(max_workers=28) as pool:records=list(pool.map(encode,jobs))
    for spec in specs:
        points=[quality(r) for r in records if r['sequence']==spec['name']]
        all_summary[spec['name']]=compare([q for q in points if q['label']=='anchor'],[q for q in points if q['label']=='C4'])
        save(BASE/'summary-progress.json',all_summary);print('COMPLETE SEQUENCE',spec['name'],flush=True)
    export_frames(specs)
    save(BASE/'summary.json',dict(bd=all_summary,scope='LDP GOP16 300 frames native inputs; fresh same-window CQP targets; frozen M4 C4 I/P; DrivingInCountry development sequence'))
    print('COMPLETE LDP16 300 TWO SEQUENCES',flush=True)
if __name__=='__main__':main()

