"""Isolated Linux C4 screening. Own-platform Anchor, frozen models, no result editing."""
import csv, hashlib, json, math, os, re, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import psutil

BASE=Path('/root/sibrc-ra32-beta-fixed5-20261015')
ORIGINAL=Path('/root/sibrc-ra32-beta-20261015')
PREVIOUS=Path('/data/vtmrc-vvenc-ra32-20261014')
FROZEN=Path('/data/vtmrc-vvenc-tune-20261014')
EXE=ORIGINAL/'vvenc/bin/release-static/vvencFFapp'
METRIC=FROZEN/'metrics-build/metrics360'
DEC=Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/umake/gcc-11.4/x86_64/release/DecoderApp')
SPHERE=Path('/root/VTM-23.0-paper-scc-rc-anchor-fit/cfg-360Lib/360Lib/sphere_655362.txt')
CFG=PREVIOUS/'ra.cfg';STATS=FROZEN/'assets/stats.txt';MODEL=FROZEN/'assets/models/C4/model'
sys.path.insert(0,str(FROZEN/'vvenc/tools/sibrc'))
from evaluate import bd_rate
N=32
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

def source(s):return Path('/data/360seqFull_32f')/s['filename']

def command(s,prefix,rate,offset):
    cmd=[str(EXE),'--preset','faster','-c',str(CFG),'-i',str(source(s)),'-s',f"{s['width']}x{s['height']}",'-fr',str(s['fps']),'-f','32','-b',str(prefix)+'.vvc',
         '--InputBitDepth='+str(s['depth']),'--InternalBitDepth=10','--OutputBitDepth=10','--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0','--VTMTargetBitrate='+str(rate),'--VTMRCTrace='+str(prefix)+'.vtm.csv']
    if rate<0:
        cmd=[x for x in cmd if not x.startswith(('--VTMTargetBitrate=','--VTMRCTrace='))]+['--QP='+str(-rate)]
    beta=offset[2] if offset is not None and len(offset)>2 else 5
    if offset is not None:cmd+=['--SIBRCMode=3','--SIBRCStats='+str(STATS),'--SIBRCModel='+str(ORIGINAL/'models'/'B5'/'model'),'--SIBRCTrace='+str(prefix)+'.sibrc.csv','--SIBRCFeature=4','--SIBRCMinOffset='+str(offset[0]),'--SIBRCMaxOffset='+str(offset[1])]
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
    need=8_000_000_000 if s['width']>=8192 else (4_500_000_000 if s['width']>=6144 else 2_500_000_000)
    with lock:
        while reserved+need>36_000_000_000 or psutil.virtual_memory().available<need+1_000_000_000:lock.wait(5)
        reserved+=need
    start=time.perf_counter();peak=0
    try:
        print('START',s['name'],label,point,flush=True)
        with prefix.with_suffix('.log').open('w') as log:
            proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,SIBRC_IB_BETA=label[1:]))
            while proc.poll() is None:
                try:peak=max(peak,psutil.Process(proc.pid).memory_info().rss)
                except psutil.Error:pass
                time.sleep(.5)
        text=prefix.with_suffix('.log').read_text(errors='replace');pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))))
        r=dict(sequence=s['name'],spec=s,label=label,point=point,target_bps=rate,offset=offset,command=cmd,elapsed_seconds=time.perf_counter()-start,peak_rss_bytes=peak,returncode=proc.returncode,pocs=pocs,verified=proc.returncode==0 and pocs==list(range(32)) and 'Total Time:' in text,outputs_sha256={str(p):sha(p) for p in outputs if p.exists()},prefix=str(prefix),platform='Linux')
        r['actual_bps']=outputs[0].stat().st_size*8*s['fps']/32 if outputs[0].exists() else 0
        kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
        r['ra_frame_types']=kinds;r['ra_verified']=len(kinds)==32 and 'I' in kinds and 'B' in kinds;r['verified']=r['verified'] and r['ra_verified']
        save(record,r);assert r['verified'],text[-2000:]
        if offset is not None:subprocess.run([sys.executable,str(FROZEN/'vvenc/tools/sibrc/verify_intra_contract.py'),str(prefix),'--output',str(prefix)+'.contract.json'],check=True,stdout=subprocess.DEVNULL)
        print('PASS',s['name'],label,point,flush=True);return r
    finally:
        with lock:reserved-=need;lock.notify_all()

def quality(r):
    s=r['spec'];prefix=Path(r['prefix']);dest=prefix.with_suffix('.quality.json')
    if dest.exists():
        q=json.loads(dest.read_text());assert q['bitstream_sha256']==sha(prefix.with_suffix('.vvc'));return q
    scratch=Path('/dev/shm/sibrc-beta-fixed5-recon-20261015');scratch.mkdir(exist_ok=True)
    rec=scratch/(s['name']+'-'+r['label']+'-R'+str(r['point'])+'.yuv');assert not rec.exists(),'Partial reconstruction '+str(rec)
    expected=s['width']*s['height']*3*32
    while shutil.disk_usage(scratch).free<expected+700_000_000 or psutil.virtual_memory().available<expected+2_000_000_000:
        print('WAIT DISK',expected,flush=True);time.sleep(30)
    try:
        with prefix.with_suffix('.decode.log').open('w') as f:subprocess.run([str(DEC),'-b',str(prefix.with_suffix('.vvc')),'-o',str(rec)],stdout=f,stderr=subprocess.STDOUT,check=True)
        assert rec.stat().st_size==expected
        raw=prefix.with_suffix('.spherical.json')
        subprocess.run([str(METRIC),str(source(s)),str(rec),str(s['width']),str(s['height']),'32',str(SPHERE),str(raw),'4','all',str(s['depth'])],check=True)
        q=json.loads(raw.read_text());ps=[];ws=[];pixels=s['width']*s['height'];weight=np.cos(np.pi*((np.arange(s['height'])+.5)/s['height']-.5))[:,None]
        with source(s).open('rb') as a,rec.open('rb') as b:
            for k in range(32):
                x=np.frombuffer(a.read(pixels*(2 if s['depth']==10 else 1)),dtype='<u2' if s['depth']==10 else np.uint8).reshape(s['height'],s['width']).astype(float)
                y=np.frombuffer(b.read(pixels*2),dtype='<u2').reshape(s['height'],s['width']).astype(float)
                if s['depth']==8:x*=4
                error=(x-y)**2;mse=error.mean();wmse=(error*weight).sum()/(weight.sum()*s['width'])
                ps.append(10*math.log10(1020**2/mse));ws.append(10*math.log10(1020**2/wmse))
                a.seek(pixels//2*(2 if s['depth']==10 else 1),1);b.seek(pixels,1)
        q.update(picture_y_psnr=ps,picture_y_wspsnr=ws)
        for key in ('psnr','wspsnr','spsnr','cpppsnr'):
            assert len(q['picture_y_'+key])==32 and all(math.isfinite(x) for x in q['picture_y_'+key]);q['mean_y_'+key]=float(np.mean(q['picture_y_'+key]))
        by_poc={int(p):int(v) for p,v in re.findall(r'POC\s+(\d+).*?\)\s+(\d+) bits',prefix.with_suffix('.log').read_text())};bits=[by_poc[p] for p in range(32)];assert len(bits)==32 and sum(bits)==prefix.with_suffix('.vvc').stat().st_size*8
        q.update(sequence=s['name'],label=r['label'],point=r['point'],frames=32,target_bps=r['target_bps'],actual_bps=r['actual_bps'],bitstream_sha256=sha(prefix.with_suffix('.vvc')),source_prefix_sha256=s['source_prefix_sha256'],reconstruction_sha256=sha(rec),metrics_exe_sha256=sha(METRIC),sphere_sha256=sha(SPHERE),picture_bits=bits,source_bitdepth=s['depth'],fps=s['fps'],cpp_dimensions=[s['width'],s['height']],metric_peak_10bit=1020)
        save(dest,q);print('QUALITY',s['name'],r['label'],r['point'],q['mean_y_spsnr'],flush=True);return q
    finally:
        # Cleanup only this job's own disposable reconstruction after success.
        if dest.exists() and rec.exists():rec.unlink()

def compare(a,b):
    return {k:bd_rate([q['mean_y_'+k] for q in a],[q['actual_bps'] for q in a],[q['mean_y_'+k] for q in b],[q['actual_bps'] for q in b]) for k in ('wspsnr','spsnr','cpppsnr','psnr')}

