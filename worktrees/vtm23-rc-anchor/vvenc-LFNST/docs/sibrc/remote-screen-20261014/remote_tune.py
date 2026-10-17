"""Isolated Linux C4 screening. Own-platform Anchor, frozen models, no result editing."""
import csv, hashlib, json, math, os, re, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import psutil

BASE=Path('/data/vtmrc-vvenc-tune-20261014')
EXE=BASE/'vvenc/bin/release-static/vvencFFapp'
METRIC=BASE/'metrics-build/metrics360'
DEC=Path('/data/ibrc_st_direct_wref/VTM-23.0/bin/umake/gcc-11.4/x86_64/release/DecoderApp')
SPHERE=Path('/root/VTM-23.0-paper-scc-rc-anchor-fit/cfg-360Lib/360Lib/sphere_655362.txt')
CFG=BASE/'assets/ldp.cfg';STATS=BASE/'assets/stats.txt';MODEL=BASE/'assets/models/C4/model'
sys.path.insert(0,str(BASE/'vvenc/tools/sibrc'))
from evaluate import bd_rate
N=17
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

def source(s):return Path('/data/360seqFull_17f')/s['filename']

def command(s,prefix,rate,offset):
    cmd=[str(EXE),'--preset','faster','-c',str(CFG),'-i',str(source(s)),'-s',f"{s['width']}x{s['height']}",'-fr',str(s['fps']),'-f','17','-b',str(prefix)+'.vvc',
         '--InputBitDepth='+str(s['depth']),'--InternalBitDepth=10','--OutputBitDepth=10','--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0','--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0','--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0','--VTMTargetBitrate='+str(rate),'--VTMRCTrace='+str(prefix)+'.vtm.csv']
    if offset is not None:cmd+=['--SIBRCMode=3','--SIBRCStats='+str(STATS),'--SIBRCModel='+str(MODEL),'--SIBRCTrace='+str(prefix)+'.sibrc.csv','--SIBRCFeature=4','--SIBRCMinOffset='+str(offset[0]),'--SIBRCMaxOffset='+str(offset[1])]
    return cmd

def encode(job):
    global reserved
    s,label,point,rate,offset=job;d=BASE/'runs'/s['name']/label;d.mkdir(parents=True,exist_ok=True)
    prefix=d/('R'+str(point));record=prefix.with_suffix('.run.json');cmd=command(s,prefix,rate,offset)
    outputs=[prefix.with_suffix('.vvc'),prefix.with_suffix('.vtm.csv')]
    if offset is not None:outputs.append(prefix.with_suffix('.sibrc.csv'))
    if record.exists():
        r=json.loads(record.read_text());assert r['verified'] and r['command']==cmd
        assert all(sha(p)==h for p,h in r['outputs_sha256'].items());return r
    if any(p.exists() for p in outputs):raise RuntimeError('Partial output requires inspection '+str(prefix))
    need=4_500_000_000 if s['width']>=8192 else (2_500_000_000 if s['width']>=6144 else 1_500_000_000)
    with lock:
        while reserved+need>40_000_000_000 or psutil.virtual_memory().available<need+1_000_000_000:lock.wait(5)
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
        r=dict(sequence=s['name'],spec=s,label=label,point=point,target_bps=rate,offset=offset,command=cmd,elapsed_seconds=time.perf_counter()-start,peak_rss_bytes=peak,returncode=proc.returncode,pocs=pocs,verified=proc.returncode==0 and pocs==list(range(17)) and 'Total Time:' in text,outputs_sha256={str(p):sha(p) for p in outputs if p.exists()},prefix=str(prefix),platform='Linux')
        r['actual_bps']=outputs[0].stat().st_size*8*s['fps']/17 if outputs[0].exists() else 0
        save(record,r);assert r['verified'],text[-2000:]
        if offset is not None:subprocess.run([sys.executable,str(BASE/'vvenc/tools/sibrc/verify_intra_contract.py'),str(prefix),'--output',str(prefix)+'.contract.json'],check=True,stdout=subprocess.DEVNULL)
        print('PASS',s['name'],label,point,flush=True);return r
    finally:
        with lock:reserved-=need;lock.notify_all()

def quality(r):
    s=r['spec'];prefix=Path(r['prefix']);dest=prefix.with_suffix('.quality.json')
    if dest.exists():
        q=json.loads(dest.read_text());assert q['bitstream_sha256']==sha(prefix.with_suffix('.vvc'));return q
    rec=prefix.with_suffix('.recon.yuv');assert not rec.exists(),'Partial reconstruction '+str(rec)
    expected=s['width']*s['height']*3*17
    assert shutil.disk_usage(BASE).free>expected+2_000_000_000,'Insufficient reconstruction disk'
    try:
        with prefix.with_suffix('.decode.log').open('w') as f:subprocess.run([str(DEC),'-b',str(prefix.with_suffix('.vvc')),'-o',str(rec)],stdout=f,stderr=subprocess.STDOUT,check=True)
        assert rec.stat().st_size==expected
        raw=prefix.with_suffix('.spherical.json')
        subprocess.run([str(METRIC),str(source(s)),str(rec),str(s['width']),str(s['height']),'17',str(SPHERE),str(raw),'2','all',str(s['depth'])],check=True)
        q=json.loads(raw.read_text());ps=[];ws=[];pixels=s['width']*s['height'];weight=np.cos(np.pi*((np.arange(s['height'])+.5)/s['height']-.5))[:,None]
        with source(s).open('rb') as a,rec.open('rb') as b:
            for k in range(17):
                x=np.frombuffer(a.read(pixels*(2 if s['depth']==10 else 1)),dtype='<u2' if s['depth']==10 else np.uint8).reshape(s['height'],s['width']).astype(float)
                y=np.frombuffer(b.read(pixels*2),dtype='<u2').reshape(s['height'],s['width']).astype(float)
                if s['depth']==8:x*=4
                error=(x-y)**2;mse=error.mean();wmse=(error*weight).sum()/(weight.sum()*s['width'])
                ps.append(10*math.log10(1020**2/mse));ws.append(10*math.log10(1020**2/wmse))
                a.seek(pixels//2*(2 if s['depth']==10 else 1),1);b.seek(pixels,1)
        q.update(picture_y_psnr=ps,picture_y_wspsnr=ws)
        for key in ('psnr','wspsnr','spsnr','cpppsnr'):
            assert len(q['picture_y_'+key])==17 and all(math.isfinite(x) for x in q['picture_y_'+key]);q['mean_y_'+key]=float(np.mean(q['picture_y_'+key]))
        bits=[int(x) for x in re.findall(r'POC\s+\d+.*?\)\s+(\d+) bits',prefix.with_suffix('.log').read_text())];assert len(bits)==17 and sum(bits)==prefix.with_suffix('.vvc').stat().st_size*8
        q.update(sequence=s['name'],label=r['label'],point=r['point'],frames=17,target_bps=r['target_bps'],actual_bps=r['actual_bps'],bitstream_sha256=sha(prefix.with_suffix('.vvc')),source_prefix_sha256=s['source_prefix_sha256'],reconstruction_sha256=sha(rec),metrics_exe_sha256=sha(METRIC),sphere_sha256=sha(SPHERE),picture_bits=bits,source_bitdepth=s['depth'],fps=s['fps'],cpp_dimensions=[s['width'],s['height']],metric_peak_10bit=1020)
        save(dest,q);print('QUALITY',s['name'],r['label'],r['point'],q['mean_y_spsnr'],flush=True);return q
    finally:
        # Cleanup only this job's own disposable reconstruction after success.
        if dest.exists() and rec.exists():rec.unlink()

def compare(a,b):
    return {k:bd_rate([q['mean_y_'+k] for q in a],[q['actual_bps'] for q in a],[q['mean_y_'+k] for q in b],[q['actual_bps'] for q in b]) for k in ('wspsnr','spsnr','cpppsnr','psnr')}

def main():
    plan=json.loads((BASE/'plan.json').read_text());specs=plan['sequences']
    save(BASE/'resource-plan.json',dict(cpu_count=os.cpu_count(),encoder_worker_cap=24,encoder_memory_budget_bytes=40000000000,metric_jobs=2,metric_workers_per_job=2,memory_available=psutil.virtual_memory().available))
    for s in specs:
        size=s['width']*s['height']*3//2*17*(2 if s['depth']==10 else 1)
        assert sha(source(s),size)==s['source_prefix_sha256'],'Remote original-prefix mismatch '+s['name']
    assets={str(p):sha(p) for p in (EXE,METRIC,DEC,CFG,STATS,Path(str(MODEL)+'.I'),Path(str(MODEL)+'.P'))};save(BASE/'frozen-assets.json',assets)
    # Platform smoke gate before the large queue: recompute a native Linux pair.
    smoke=[(specs[0],label,1,specs[0]['targets'][0],offset) for label,offset in [('anchor',None),('C4',[-2,2])]]
    sr=[encode(j) for j in smoke];sq=[quality(r) for r in sr]
    save(BASE/'smoke-approved.json',dict(pass_test=True,source_prefix_verified=True,linux_pair_metrics_finite=True,controller_intra_contract=True,linux_anchor_R1_sha=sr[0]['outputs_sha256'][str(Path(sr[0]['prefix']).with_suffix('.vvc'))],windows_anchor_R1_sha=specs[0]['local_anchor_R1_bitstream_sha256'],scope='Linux baseline is recomputed; cross-platform bit equality is recorded, not assumed'))
    jobs=[]
    for s in specs:
        variants=[('anchor',None),('C4',[-2,2])]+[('offset_%s_%s'%tuple(off),off) for off in plan['offsets']]
        for label,offset in variants:
            for n,rate in enumerate(s['targets'],1):jobs.append((s,label,n,rate,offset))
    with ThreadPoolExecutor(max_workers=24) as pool:records=list(pool.map(encode,jobs))
    # At most two reconstructions; per-stream official metric has two workers.
    with ThreadPoolExecutor(max_workers=2) as pool:points=list(pool.map(quality,records))
    summary={};requests=[]
    for s in specs:
        qs=[q for q in points if q['sequence']==s['name']];anchor=[q for q in qs if q['label']=='anchor'];variants={}
        for label in sorted({q['label'] for q in qs if q['label']!='anchor'}):
            variants[label]=compare(anchor,[q for q in qs if q['label']==label])
            if label!='C4' and all(variants[label][k]<-.01 for k in ('wspsnr','spsnr','cpppsnr')):requests.append(dict(sequence=s['name'],label=label,screen_bd=variants[label],requires='original independent window64 frames64..80 and same-window Anchor'))
        summary[s['name']]=dict(bd=variants,development_sequence=True,calibration_member=s['name'] in ('DrivingInCity','DrivingInCountry'))
    save(BASE/'screen-summary.json',summary);save(BASE/'holdout-requests.json',requests)
    print('COMPLETE REMOTE SCREEN; HOLDOUT REQUIRED',len(requests),flush=True)

if __name__=='__main__':main()
