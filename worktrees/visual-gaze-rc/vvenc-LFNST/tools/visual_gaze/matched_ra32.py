"""32-frame strip-only experiment paired with frozen SIBRC-thread Anchors.

No new CQP ladder or formal Anchors. Small explicit mode-off compatibility gates
protect reuse across encoder branches; their limited empirical scope is recorded.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import csv
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from batch_strip import prefix_hash
from evaluate import bd_rate
from prepare import sha
from run_experiment import run

METRICS=('psnr','ws_psnr','s_psnr_nn','cpp_psnr')


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8');temp.replace(path)


def method_command(anchor,exe,features,prefix,reconstruction):
    cmd=anchor.copy();cmd[0]=str(exe)
    cmd[cmd.index('-b')+1]=str(prefix)+'.vvc'
    cmd=[('--VTMRCTrace='+str(prefix)+'.vtm.csv') if v.startswith('--VTMRCTrace=') else v for v in cmd]
    return cmd+['-o',str(reconstruction),'--VisualGazeMode=1',
                '--VisualGazeFeatures='+str(features),'--VisualGazeTrace='+str(prefix)+'.gaze.csv']


def summary(expected,reports,failures):
    complete=set(expected)==set(reports)
    keys=[m+'_bd_rate_percent' for m in METRICS]
    valid=complete and all(math.isfinite(reports[n]['comparisons'].get(k,float('nan'))) for n in expected for k in keys)
    return dict(configuration='RA32 / 32 coded frames / NumRefPics=1',modes=[0,1],
        expected_sequences=len(expected),completed_sequences=len(reports),failures=failures,
        missing=[n for n in expected if n not in reports],per_sequence={n:r['comparisons'] for n,r in reports.items()},
        average={k:sum(reports[n]['comparisons'][k] for n in expected)/len(expected) for k in keys} if valid else None,
        average_basis='all fourteen sequences, equal weight; no selective exclusions',
        anchor_basis='frozen SIBRC-thread anchors, targets and complete commands; no cross-window reuse',timing_comparable=False)


def verify_record(record):
    if not record.get('verified') or not record.get('ra_verified') or record['pocs']!=list(range(32)):
        raise ValueError('invalid 32-frame RA reference run')
    for path,digest in record['outputs_sha256'].items():
        if sha(path)!=digest:raise ValueError('reference output changed: '+path)


def compress_trace(path):
    path=Path(path);digest=sha(path);dest=Path(str(path)+'.gz')
    with path.open('rb') as source,gzip.open(dest,'wb',compresslevel=6) as out:shutil.copyfileobj(source,out)
    result=dict(path=str(dest),uncompressed_sha256=digest,gzip_sha256=sha(dest))
    path.unlink();return result


def native_cpp(report,python_frames):
    for key in ('picture_y_spsnr','picture_y_cpppsnr'):
        values=report.get(key,[])
        if len(values)!=32 or not all(math.isfinite(v) for v in values):raise ValueError('incomplete native quality')
    if len(python_frames)!=32 or max(abs(x['s_psnr_nn']-y) for x,y in zip(python_frames,report['picture_y_spsnr']))>1e-8:
        raise ValueError('S-PSNR convention mismatch')
    return sum(report['picture_y_cpppsnr'])/32


class Resources:
    def __init__(self,capacity,scratch):self.capacity=capacity;self.scratch=scratch;self.reserved=0;self.cv=threading.Condition()
    def acquire(self,need,scratch_need=0):
        import psutil
        with self.cv:
            while self.reserved+need>self.capacity or psutil.virtual_memory().available<need+1500000000 or shutil.disk_usage(self.scratch).free<scratch_need+512000000:
                self.cv.wait(5)
            self.reserved+=need
    def release(self,need):
        with self.cv:self.reserved-=need;self.cv.notify_all()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','encoder','decoder','metric','sphere','output','scratch-root'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--workers',type=int,choices=range(1,9),default=6)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);a.scratch_root.mkdir(parents=True,exist_ok=True)
    cfg=a.reference/'ra.cfg'
    required={'GOPSize':'32','PicReordering':'1','POC0IDR':'1','IntraPeriod':'32','DecodingRefreshType':'1','CTUSize':'128','NumRefPics':'1','NumRefPicsSCC':'0'}
    parsed=dict(line.split(':',1) for line in cfg.read_text().splitlines() if ':' in line)
    if any(parsed.get(k,'').strip()!=v for k,v in required.items()):raise ValueError('reference RA configuration differs')
    roots=sorted((a.reference/'runs').glob('*/anchor'))
    if len(roots)!=14:raise ValueError('expected fourteen frozen Anchor ladders')
    cases={};reference_hashes={}
    for folder in roots:
        name=folder.parent.name;rows=[]
        for point in range(1,5):
            runfile=folder/f'R{point}.run.json';quality=folder/f'R{point}.quality.json'
            r=json.loads(runfile.read_text());q=json.loads(quality.read_text());verify_record(r)
            if q['frames']!=32 or q['target_bps']!=r['target_bps'] or q['bitstream_sha256']!=sha(r['prefix']+'.vvc') or q['source_prefix_sha256']!=r['spec']['source_prefix_sha256']:
                raise ValueError('reference quality/run mismatch')
            if q['sphere_sha256']!=sha(a.sphere) or q['metrics_exe_sha256']!=sha(a.metric):raise ValueError('reference metric identity differs')
            for m in ('psnr','wspsnr','spsnr','cpppsnr'):
                if len(q['picture_y_'+m])!=32 or not all(math.isfinite(x) for x in q['picture_y_'+m]):raise ValueError('incomplete reference quality')
            rows.append((r,q));reference_hashes[str(runfile)]=sha(runfile);reference_hashes[str(quality)]=sha(quality)
        s=rows[0][0]['spec'];src=Path(rows[0][0]['command'][rows[0][0]['command'].index('-i')+1])
        if any(r['spec']['source_prefix_sha256']!=s['source_prefix_sha256'] for r,q in rows):raise ValueError('mixed reference source')
        count=s['width']*s['height']*3//2*(2 if s['depth']==10 else 1)*32
        if prefix_hash(src,count)!=s['source_prefix_sha256']:raise ValueError('reference source changed')
        cases[name]=dict(spec=s,source=src,rows=rows)
        print('Reference verified:',name,flush=True)
    deps=[a.encoder,a.decoder,a.metric,a.sphere,cfg]+[Path(__file__).with_name(n) for n in ('matched_ra32.py','prepare.py','evaluate.py','batch_strip.py','run_experiment.py')]
    manifest=dict(frames=32,configuration=required,method='visual gaze strip-only mode1',mu_m=1,mu_s=1,workers=a.workers,
        dependencies={str(f):sha(f) for f in deps},reference_records=reference_hashes,
        sources={n:dict(c['spec'],actual_path=str(c['source'])) for n,c in cases.items()})
    mf=a.output/'manifest.json'
    if mf.exists() and json.loads(mf.read_text())!=manifest:raise ValueError('experiment identity changed')
    save(mf,manifest)
    # Three representative resolutions/depths plus the user-identified City R1.
    gates=['DrivingInCity','AerialCity','Balboa','ChairliftRide']
    gatefile=a.output/'compatibility-approved.json'
    if not gatefile.exists():
        evidence=[]
        for name in gates:
            r,q=cases[name]['rows'][0];pref=a.output/'compatibility'/name;pref.parent.mkdir(exist_ok=True)
            cmd=r['command'].copy();cmd[0]=str(a.encoder);cmd[cmd.index('-b')+1]=str(pref)+'.vvc'
            cmd=[('--VTMRCTrace='+str(pref)+'.vtm.csv') if v.startswith('--VTMRCTrace=') else v for v in cmd]
            run(cmd,Path(str(pref)+'.log'))
            same=sha(str(pref)+'.vvc')==q['bitstream_sha256']
            row=dict(sequence=name,point=1,command=cmd,bitstream_identical=same,sha256=sha(str(pref)+'.vvc'),trace=compress_trace(str(pref)+'.vtm.csv'))
            evidence.append(row);save(a.output/'compatibility-evidence.json',evidence)
            if not same:raise ValueError('mode-off compatibility gate failed: '+name)
        save(gatefile,dict(passed=True,encoder_sha256=sha(a.encoder),scope='four representative R1 streams only; not a proof for all source/target combinations',evidence=evidence))
    else:
        gate=json.loads(gatefile.read_text())
        if not gate['passed'] or gate['encoder_sha256']!=sha(a.encoder):raise ValueError('invalid saved compatibility gate')
    resources=Resources(24000000000,a.scratch_root);reports={};failures={};expected=list(cases)
    def publish():save(a.output/'summary.json',summary(expected,reports,failures))
    def worker(name):
        case=cases[name];s=case['spec'];folder=a.output/name;folder.mkdir(exist_ok=True);features=folder/'features.txt'
        featuremeta=features.with_suffix('.txt.json')
        cache=json.loads(featuremeta.read_text()) if featuremeta.exists() else {}
        if not(features.exists() and cache.get('output_sha256')==sha(features) and cache.get('input_sha256')==s['source_prefix_sha256'] and cache.get('geometry')==[s['width'],s['height'],128,10,32] and cache.get('mu_m')==1 and cache.get('mu_s')==1 and cache.get('motion_search')==4):
            need=5000000000 if s['width']>=8192 else 2500000000
            resources.acquire(need)
            try:
                print('Features:',name,flush=True)
                run([sys.executable,str(Path(__file__).with_name('prepare.py')),'features','--input',case['source'],
                    '--width',s['width'],'--height',s['height'],'--ctu',128,'--bitdepth',10,'--input-bitdepth',s['depth'],
                    '--frames',32,'--mu-m',1,'--mu-s',1,'--output',features],folder/'prepare.log')
            finally:resources.release(need)
        points=[]
        for point,(reference,aq) in enumerate(case['rows'],1):
            prefix=folder/f'R{point}';record=prefix.with_suffix('.result.json')
            if record.exists():
                row=json.loads(record.read_text())
                if row['stream_sha256']!=sha(prefix.with_suffix('.vvc')) or row['features_sha256']!=sha(features):raise ValueError('saved method artifacts changed')
                for trace in row['traces']:
                    if sha(trace['path'])!=trace['gzip_sha256']:raise ValueError('compressed trace changed')
                points.append(row);continue
            encoder_need=8000000000 if s['width']>=8192 else (4500000000 if s['width']>=6144 else 2500000000)
            rawbytes=s['width']*s['height']*3*32;need=encoder_need+2*rawbytes
            while shutil.disk_usage(a.output).free<800000000:print('WAIT DISK',name,flush=True);time.sleep(30)
            resources.acquire(need,2*rawbytes)
            try:
                with tempfile.TemporaryDirectory(prefix='matched-',dir=a.scratch_root) as temp:
                    rec=Path(temp)/'encoder.yuv';decoded=Path(temp)/'decoded.yuv'
                    cmd=method_command(reference['command'],a.encoder,features,prefix,rec)
                    save(prefix.with_suffix('.command.json'),cmd);print('Encode:',name,point,flush=True)
                    elapsed=run(cmd,prefix.with_suffix('.log'))
                    text=prefix.with_suffix('.log').read_text(errors='replace')
                    pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))))
                    kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
                    if pocs!=list(range(32)) or len(kinds)!=32 or 'I' not in kinds or 'B' not in kinds:raise ValueError('not complete 32-frame I/B RA')
                    metriccmd=[sys.executable,str(Path(__file__).with_name('evaluate.py')),'--input',case['source'],'--reconstruction',rec,
                        '--trace',str(prefix)+'.vtm.csv','--bitstream',str(prefix)+'.vvc','--width',s['width'],'--height',s['height'],
                        '--frames',32,'--input-bitdepth',s['depth'],'--target-bps',reference['target_bps'],'--fps',s['fps'],
                        '--delay',32,'--sphere',a.sphere,'--output',str(prefix)+'.metrics.json']
                    run(metriccmd,prefix.with_suffix('.metrics.log'));mq=json.loads(prefix.with_suffix('.metrics.json').read_text())
                    if mq['input_sha256']!=s['source_prefix_sha256']:raise ValueError('metric source identity changed')
                    run([a.decoder,'-b',str(prefix)+'.vvc','-o',decoded],prefix.with_suffix('.decode.log'))
                    if decoded.stat().st_size!=rawbytes or sha(decoded)!=sha(rec):raise ValueError('independent decoder mismatch')
                    decoded.unlink()
                    native=prefix.with_suffix('.spherical.json')
                    run([a.metric,case['source'],rec,s['width'],s['height'],32,a.sphere,native,2,'all',s['depth']],prefix.with_suffix('.spherical.log'))
                    nq=json.loads(native.read_text());values=mq['quality_mean_db']
                    values['cpp_psnr']=native_cpp(nq,mq['frames'])
                    traces=[compress_trace(str(prefix)+suffix) for suffix in ('.vtm.csv','.gaze.csv')]
                    row=dict(sequence=name,point=point,target_bps=reference['target_bps'],actual_bps=mq['actual_bps'],
                        quality=values,bitrate_error_percent=mq['bitrate_error_percent'],seconds=elapsed,command=cmd,
                        stream_sha256=sha(str(prefix)+'.vvc'),features_sha256=sha(features),traces=traces,
                        reconstruction_sha256=sha(rec),decoder_matches_reconstruction=True,pocs=pocs,ra_frame_types=kinds,
                        reused_anchor_quality=aq,reused_anchor_record_sha256=reference_hashes[str(a.reference/'runs'/name/'anchor'/f'R{point}.run.json')])
                    save(record,row);points.append(row);print('Verified:',name,point,flush=True)
            finally:resources.release(need)
        comparisons={}
        amap={'psnr':'psnr','ws_psnr':'wspsnr','s_psnr_nn':'spsnr','cpp_psnr':'cpppsnr'}
        for metric in METRICS:
            try:comparisons[metric+'_bd_rate_percent']=bd_rate([q['actual_bps'] for r,q in case['rows']],
                [q['mean_y_'+amap[metric]] for r,q in case['rows']],[r['actual_bps'] for r in points],[r['quality'][metric] for r in points])
            except ValueError as error:comparisons[metric+'_unavailable']=str(error)
        report=dict(sequence=name,frames=32,config_sha256=sha(cfg),anchor_reused=True,results=points,comparisons=comparisons)
        save(folder/'report.json',report);return report
    publish()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(worker,name):name for name in cases}
        for future in as_completed(futures):
            name=futures[future]
            try:reports[name]=future.result();print('Complete:',name,reports[name]['comparisons'],flush=True)
            except Exception as error:failures[name]=str(error);print('Failed:',name,str(error)[-1200:],flush=True)
            publish()
    if failures:raise RuntimeError('Method batch incomplete; no complete average reported')


if __name__=='__main__':main()
