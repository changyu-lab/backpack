"""M4 frozen 64-frame protocol. No work starts without an explicit stage and build gate."""
import argparse, csv, hashlib, importlib.util, json, os, shutil, subprocess, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST')
BASE=Path('I:/vvenc-LFNST/.worktrees/m4-20261012')
CACHE=Path('D:/SIBRC-cache-20261010')
PY='F:/Anaconda/python.exe'
TRAIN=('DrivingInCity','DrivingInCountry')
VALIDATION=('AerialCity','PoleVault','BranCastle2')
MAIN_SELECTORS=(0,1,3,4,5,6,7)
LABELS=('C0','C1','C2','C3','C4','plane','geo','satd')
QPS=(17,22,27,32,37,42,47,52)
WINDOWS=(0,64,128,192)
FRAMES=64

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2),encoding='utf8');tmp.replace(path)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def collection_specs():
    return [dict(sequence=s,window_start=w,qp=q,frames=16,split='holdout' if w==192 else 'train') for s in TRAIN for w in WINDOWS for q in QPS]

def frame_rows_per_sequence():return FRAMES*4*(1+len(MAIN_SELECTORS))

def enrich_row(row,sequence,window,qp,run,source):
    r=dict(row);r.update(source_sequence=sequence,sequence=sequence,window_start=window,local_poc=row['poc'],run_id=run,requested_qp=qp,actual_qp=row.get('actual_qp',row['qp']),source_sha256=source['sha256'])
    return r

def row_key(r):return tuple(str(r[k]) for k in ('source_sequence','window_start','local_poc','ctu','requested_qp','actual_qp','kind'))

def helper():
    # Each invocation owns both helper modules; the historical runner's globals never leak.
    sys.path.insert(0,str(ROOT/'tools/sibrc'))
    spec=importlib.util.spec_from_file_location('m4_local_runner',ROOT/'tools/sibrc/run_local.py')
    local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)
    spec=importlib.util.spec_from_file_location('m4_legacy',Path(__file__).with_name('run_three_sibrc300.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.runner=local;m.BASE=BASE;m.CACHE=CACHE
    return m

def frozen(m):
    gate=BASE/'build-approved.json'
    if not gate.exists():raise RuntimeError('Root build review required: missing '+str(gate))
    approval=json.loads(gate.read_text())
    assets={str(BASE/n):sha(BASE/n) for n in ('encoder-m4.exe','ldp.cfg','stats.txt')}
    if approval.get('encoder_sha256')!=assets[str(BASE/'encoder-m4.exe')]:raise RuntimeError('Build approval does not match encoder')
    m.runner.EXE=BASE/'encoder-m4.exe'
    return assets

def source(seq,frames):
    w,h=(6144,3072) if seq=='BranCastle2' else (3840,1920)
    filename=seq+f'_{w}x{h}_30fps_8bit_420_erp.yuv'
    if seq=='PoleVault':filename='PoleVault_le_3840x1920_30fps_8bit_420_erp.yuv'
    original=Path('I:/Sequences360')/filename;cached=CACHE/filename
    CACHE.mkdir(exist_ok=True)
    if not cached.exists():
        pending=cached.with_suffix('.copying')
        if pending.exists():raise RuntimeError('Partial source copy requires inspection '+str(pending))
        before=original.stat();shutil.copyfile(original,pending)
        if sha(original)!=sha(pending) or original.stat().st_mtime_ns!=before.st_mtime_ns:raise RuntimeError('Source copy changed')
        pending.replace(cached)
    needed=w*h*3//2*frames
    if cached.stat().st_size<needed:raise RuntimeError('Source too short '+seq)
    manifest=BASE/'sources'/f'{seq}.json'
    if manifest.exists():
        provenance=json.loads(manifest.read_text())
        if provenance['sha256']!=sha(cached):raise RuntimeError('Cached source hash changed')
    else:
        # Existing SSD cache is explicitly checked against the original before trusting it.
        digest=sha(cached)
        if digest!=sha(original):raise RuntimeError('Cached source differs from original')
        provenance=dict(path=str(original),cache=str(cached),sha256=digest,file_bytes=cached.stat().st_size)
        save(manifest,provenance)
    return cached,w,h,provenance

def job(m,d,seq,src,w,h,name,frames,rate,mode,selector=None,window=0,qp=None):
    # Job construction is serial. Encoder execution does not mutate module configuration.
    j=m.make_job(d,seq,src,w,h,name,frames,rate,mode)
    j['command'][0]=str(BASE/'encoder-m4.exe')
    j['assets'][0]=str(BASE/'encoder-m4.exe')
    j['command']+=['--FrameSkip='+str(window),'--SIBRCMinOffset=-2','--SIBRCMaxOffset=2']
    if selector is not None:j['command']+=['--SIBRCFeature='+str(selector)]
    if qp is not None:j['command']+=['--SIBRCCalibrationQP='+str(qp)]
    if mode==3:
        prefix=BASE/'models'/LABELS[selector]/'model'
        j['command']=[x.replace('--SIBRCModel='+str(BASE/'model'),'--SIBRCModel='+str(prefix)) for x in j['command']]
        j['assets']=[str(prefix)+'.'+Path(x).suffix[1:] if Path(x).name in ('model.I','model.P') else x for x in j['assets']]
    j.update(window_start=window,requested_qp=qp,selector=selector)
    return j

def run_jobs(m,jobs,assets,sources):
    import psutil
    available=psutil.virtual_memory().available
    # Resolution-specific caps approved for short training / 64-frame validation.
    per_worker=2_000_000_000 if any(j['width']>=6144 for j in jobs) else 1_300_000_000
    reserve=700_000_000
    workers=min(2,int((available-reserve)//per_worker))
    if workers<1:raise RuntimeError('Insufficient available memory for conservative encoder budget')
    save(BASE/'resource-budget.json',dict(workers=workers,available=available,reserve=reserve,per_worker=per_worker))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda j:m.execute(j,dict(assets=assets,source=sources[j['source_sequence']])),jobs))

def collect(m,assets,smoke=False):
    if not smoke:
        gate=json.loads((BASE/'collection-smoke-approved.json').read_text())
        if gate['encoder_sha256']!=sha(BASE/'encoder-m4.exe') or gate['stats_sha256']!=sha(BASE/'stats.txt'):raise RuntimeError('Collection smoke approval assets changed')
    specs=collection_specs();specs=specs[:1] if smoke else specs
    jobs=[];sources={};BASE.mkdir(parents=True,exist_ok=True)
    for s in TRAIN:
        src,w,h,p=source(s,208);sources[s]=p
        d=BASE/('collect-smoke' if smoke else 'collect')/s;d.mkdir(parents=True,exist_ok=True)
        for a in (x for x in specs if x['sequence']==s):
            name=f"w{a['window_start']}_QP{a['qp']}"
            jobs.append(job(m,d,s,src,w,h,name,2 if smoke else 16,5000000,2,4,a['window_start'],a['qp']))
    save(BASE/('collect-smoke-jobs.json' if smoke else 'collect-jobs.json'),jobs)
    records=run_jobs(m,jobs,assets,sources)
    rows=[];keys=set()
    for r in records:
        with Path(r['log']).with_suffix('.sibrc.csv').open(newline='') as f:
            for raw in csv.DictReader(f):
                row=enrich_row(raw,r['source_sequence'],r['window_start'],r['requested_qp'],r['name'],sources[r['source_sequence']])
                key=row_key(row)
                if key in keys:raise RuntimeError('Duplicate training row '+str(key))
                keys.add(key);rows.append(row)
    out=BASE/('smoke-samples.csv' if smoke else 'development_samples.csv')
    with out.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    save(out.with_suffix('.metadata.json'),dict(rows=len(rows),jobs=len(records),rowset_sha256=hashlib.sha256(json.dumps(sorted(keys)).encode()).hexdigest(),sources=sources,stats_sha256=sha(BASE/'stats.txt'),windows=WINDOWS,qps=QPS,frames_per_window=2 if smoke else 16,offset=[-2,2],validation_frames=64))
    if smoke:
        smoke_equivalence(m,assets,sources,jobs[0],records[0])

def fit():
    meta=json.loads((BASE/'development_samples.metadata.json').read_text())
    if meta['jobs']!=64 or meta['frames_per_window']!=16:raise RuntimeError('Fit requires all 64 completed collection jobs')
    jobs=json.loads((BASE/'collect-jobs.json').read_text())
    if len(jobs)!=64:raise RuntimeError('Incomplete collection manifest')
    for j in jobs:
        record=json.loads(Path(j['log']).with_suffix('.run.json').read_text())
        if not record['verified'] or record['pocs']!=list(range(16)):raise RuntimeError('Incomplete collection record')
        if any(sha(p)!=digest for p,digest in record['outputs_sha256'].items()):raise RuntimeError('Changed collection output')
    checkpoint=BASE/'fit-run.json'
    inputs={str(p):sha(p) for p in (BASE/'development_samples.csv',BASE/'stats.txt',ROOT/'tools/sibrc/calibrate_m4.py')}
    if checkpoint.exists():
        record=json.loads(checkpoint.read_text())
        if record['inputs']!=inputs or any(sha(p)!=digest for p,digest in record['outputs'].items()):raise RuntimeError('Frozen fit checkpoint changed')
    else:
        if (BASE/'models').exists() and any((BASE/'models').iterdir()):raise RuntimeError('Partial model fit requires inspection')
        subprocess.run([PY,str(ROOT/'tools/sibrc/calibrate_m4.py'),'--input',str(BASE/'development_samples.csv'),'--stats',str(BASE/'stats.txt'),'--output-dir',str(BASE/'models')],check=True)
        outputs={str(p):sha(p) for p in (BASE/'models').rglob('*') if p.is_file()}
        save(checkpoint,dict(inputs=inputs,outputs=outputs))
    controller_replay()

def controller_replay():
    exe=ROOT/'build-vtmrc/sibrc-tests/Release/sibrc_m4_replay.exe'
    gate=BASE/'models/controller-replay.json'
    provenance=sha(BASE/'models/provenance.json')
    if gate.exists():
        record=json.loads(gate.read_text())
        if record['provenance_sha256']!=provenance or record['replay_exe_sha256']!=sha(exe) or record.get('input_csv_sha256')!=sha(BASE/'development_samples.csv'):raise RuntimeError('Changed controller replay assets')
        if record.get('pass') is not True:raise RuntimeError('Previous fitted controller replay failed; root review required')
        return
    paths=[BASE/'models'/label/('model.'+kind) for label in ('C2','C3') for kind in ('I','P')]
    command=[str(exe)]+[str(p) for p in paths]+[str(BASE/'development_samples.csv')]
    result=subprocess.run(command,capture_output=True,text=True)
    (BASE/'controller-replay.stdout.log').write_text(result.stdout,encoding='utf8')
    (BASE/'controller-replay.stderr.log').write_text(result.stderr,encoding='utf8')
    try:diagnostics=json.loads(result.stdout)
    except json.JSONDecodeError:raise RuntimeError('Controller replay invalid JSON; inspect logs')
    passed=result.returncode==0 and diagnostics.get('controller_replay_pass') is True
    save(gate,dict(**{'pass':passed},provenance_sha256=provenance,replay_exe_sha256=sha(exe),input_csv_sha256=sha(BASE/'development_samples.csv'),command=command,diagnostics=diagnostics))
    if not passed:raise RuntimeError('Fitted C2/C3 controller replay failed; root review required')

def smoke_equivalence(m,assets,sources,new_job,new_record):
    old=Path('I:/vvenc-LFNST/.worktrees/sibrc-three-300-20261010/encoder-frozen.exe')
    if not old.exists():raise RuntimeError('Frozen old encoder required for collection compatibility smoke')
    d=BASE/'smoke-compatibility';d.mkdir(exist_ok=True)
    j=dict(new_job);j['name']='old_C4';j['log']=str(d/'old_C4.log')
    oldprefix=str(d/'old_C4');newprefix=str(Path(new_job['log']).with_suffix(''))
    j['command']=[x.replace(newprefix,oldprefix) for x in j['command'] if not x.startswith('--SIBRCFeature=')]
    j['command'][0]=str(old);j['assets']=[str(old) if x==str(BASE/'encoder-m4.exe') else x for x in j['assets']]
    j['outputs']=[x.replace(newprefix,oldprefix) for x in j['outputs']]
    oldassets=dict(assets);oldassets[str(old)]=sha(old)
    r=m.execute(j,dict(assets=oldassets,source=sources[j['source_sequence']]))
    for suffix in ('.vvc','.vtm.csv'):
        if sha(newprefix+suffix)!=sha(oldprefix+suffix):raise RuntimeError('Collection altered encoding '+suffix)
    with open(newprefix+'.sibrc.csv',newline='') as f:a=list(csv.DictReader(f))
    with open(oldprefix+'.sibrc.csv',newline='') as f:b=list(csv.DictReader(f))
    if len(a)!=len(b):raise RuntimeError('Collection CTU count changed')
    for x,y in zip(a,b):
        if (x['poc'],x['ctu'],x['qp'],x['bits'])!=(y['poc'],y['ctu'],y['qp'],y['bits']):raise RuntimeError('Collection row identity changed')
        value=float(y['ieff'])
        if abs(float(x['ieff'])-value)>1e-10*(1+abs(value)):raise RuntimeError('Legacy C4 changed')
        if abs(float(x['feature_C2'])/4-float(x['feature_C3']))>1e-10*(1+abs(float(x['feature_C3']))):raise RuntimeError('C2/C3 trace equivalence failed')
    save(BASE/'collection-smoke-approved.json',dict(encoder_sha256=sha(BASE/'encoder-m4.exe'),old_encoder_sha256=sha(old),stats_sha256=sha(BASE/'stats.txt'),bitstream_equal=True,vtm_trace_equal=True,c4_compatible=True,c2_c3_equal=True,rows=len(a)))

def validate(m,assets,smoke=False):
    selectors=tuple(range(8)) if smoke else MAIN_SELECTORS
    replay=BASE/'models/equivalence.json'
    if not replay.exists():raise RuntimeError('Missing C2/C3 equivalence diagnostics')
    diagnostics=json.loads(replay.read_text())
    if not smoke:
        controller_path=BASE/'models/controller-replay.json'
        if not controller_path.exists():raise RuntimeError('Root must complete fitted-model controller replay before formal validation')
        controller=json.loads(controller_path.read_text())
        if controller.get('pass') is not True:raise RuntimeError('C2/C3 controller replay failed: root must review and authorize additional C2 experiment')
        if controller.get('provenance_sha256')!=sha(BASE/'models/provenance.json'):raise RuntimeError('Controller replay does not match fitted models')
        loader_gate=json.loads((BASE/'validation-smoke-approved.json').read_text())
        if loader_gate['encoder_sha256']!=sha(BASE/'encoder-m4.exe') or loader_gate['provenance_sha256']!=sha(BASE/'models/provenance.json'):raise RuntimeError('V2 loader smoke assets changed')
    # Full C2 encoding remains an explicit root decision when replay fails.
    save(BASE/('validation-smoke-protocol.json' if smoke else 'validation-protocol.json'),dict(frames=2 if smoke else 64,selectors=MAIN_SELECTORS,labels=[LABELS[i] for i in MAIN_SELECTORS],offset=[-2,2],target_origin='existing 300-frame CQP targets',frame_rows_per_sequence=frame_rows_per_sequence(),retuning=False,c2_equivalence=diagnostics,metrics=['WS-PSNR','S-PSNR-NN','CPP-PSNR','Y-PSNR']))
    for seq in VALIDATION:
        src,w,h,p=source(seq,64);d=BASE/('validation-smoke' if smoke else 'validation')/seq;d.mkdir(parents=True,exist_ok=True)
        old=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010') if seq=='AerialCity' else Path('I:/vvenc-LFNST/.worktrees/sibrc-three-300-20261010')/seq
        targets=json.loads((old/'targets.json').read_text())
        if len(targets)!=4 or any(r<=0 for r in targets):raise RuntimeError('Invalid frozen targets')
        save(d/'targets.json',dict(values=targets,origin=str(old/'targets.json'),sha256=sha(old/'targets.json')))
        jobs=[]
        for n,rate in enumerate(targets,1):
            jobs.append(job(m,d,seq,src,w,h,f'rc64_anchor_R{n}',2 if smoke else 64,rate,0))
            for selector in selectors:
                jobs.append(job(m,d,seq,src,w,h,f'rc64_{LABELS[selector]}_R{n}',2 if smoke else 64,rate,3,selector))
        if smoke:jobs=jobs[:9]
        stage_assets=dict(assets)
        for j in jobs:
            for a in j['assets']:stage_assets[a]=sha(a)
        save(d/'protocol.json',dict(assets=stage_assets,source=p,frames=2 if smoke else 64,targets=targets,offset=[-2,2]))
        records=run_jobs(m,jobs,stage_assets,{seq:p});points=[]
        for r in records:
            if r['selector'] is not None:
                subprocess.run([PY,str(ROOT/'tools/sibrc/verify_intra_contract.py'),str(d/r['name']),'--output',str(d/(r['name']+'.contract.json'))],check=True)
            points.append(m.decode_metrics(d,r,src,w,h,1,frames=r['frames']))
        save(d/'quality.json',points)
        if not smoke:finish(m,d,seq,points)
    if smoke:save(BASE/'validation-smoke-approved.json',dict(encoder_sha256=sha(BASE/'encoder-m4.exe'),provenance_sha256=sha(BASE/'models/provenance.json'),selectors=selectors,frames=2,all_intra_contracts_verified=True))
    if not smoke:
        all_results={s:json.loads((BASE/'validation'/s/'assessment.json').read_text())['bd_rate_percent'] for s in VALIDATION}
        save(BASE/'aggregate.json',dict(sequences=all_results,mean_percent={label:{metric:sum(all_results[s][label][metric] for s in VALIDATION)/3 for metric in ('wspsnr','spsnr','cpppsnr','psnr')} for label in (LABELS[i] for i in MAIN_SELECTORS)},scope='arithmetic mean of three complete sequence BD-rates'))

def finish(m,d,seq,points):
    anchor=[p for p in points if '_anchor_' in p['name']];result={}
    with (d/'frames.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['method','target_bps','poc','bits','wspsnr','spsnr','cpppsnr','psnr'])
        for p in points:
            label=p['name'].split('_')[1]
            for k in range(FRAMES):writer.writerow([label,p['target_bps'],k,p['picture_bits'][k]]+[p['picture_y_'+metric][k] for metric in ('wspsnr','spsnr','cpppsnr','psnr')])
    for selector in MAIN_SELECTORS:
        label=LABELS[selector];selected=[p for p in points if '_'+label+'_' in p['name']]
        bd={metric:m.bd_rate([p['mean_y_'+metric] for p in anchor],[p['actual_bps'] for p in anchor],[p['mean_y_'+metric] for p in selected],[p['actual_bps'] for p in selected]) for metric in ('wspsnr','spsnr','cpppsnr','psnr')}
        result[label]=bd
        # Separate assessments keep historical plot inputs compatible; relabel separately.
        save(d/label/'assessment.json',dict(sequence=seq,method_label='M4 '+label,points=anchor+selected,bd_rate_percent=bd))
        plot_source=Path(__file__).with_name('plot_compact_sibrc_panels.py').read_text(encoding='utf8')
        plot_source=plot_source.replace("('_full_', 'SIBRC'", "('_"+label+"_', 'SIBRC'")
        plot_source=plot_source.replace('ax.set_xticks([0, 50, 100, 150, 200, 250, 300])', 'ax.set_xticks([t for t in [0, 50, 100, 150, 200, 250, 300] if t < expected_frames] + [expected_frames])\n                ax.set_xlim(0, expected_frames)')
        plot_path=d/label/'plot_panels.py';plot_path.write_text(plot_source,encoding='utf8')
        subprocess.run([PY,str(plot_path),str(d/label/'assessment.json'),'--sequence-label',seq,'--expected-frames','64','--output-dir',str(d/label/'panels')],check=True)
    save(d/'assessment.json',dict(sequence=seq,frames=64,frame_csv_rows=frame_rows_per_sequence(),bd_rate_percent=result,scope='independent of calibration; historical validation sequences'))
    lines=['# '+seq+' M4 64-frame results','','Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.','','|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|','|---|---:|---:|---:|---:|']
    for label,bd in result.items():lines.append('|M4 '+label+'|'+'|'.join('%+.4f%%'%bd[k] for k in ('wspsnr','spsnr','cpppsnr','psnr'))+'|')
    lines+=['',f'frames.csv has {frame_rows_per_sequence()} data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.','Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.']
    (d/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    archive=ROOT/'docs/sibrc/m4-20261012'/seq;archive.mkdir(parents=True,exist_ok=True)
    for path in d.iterdir():
        if path.is_file() and (path.suffix in ('.json','.md') or path.name=='frames.csv'):shutil.copyfile(path,archive/path.name)
    for selector in MAIN_SELECTORS:shutil.copytree(d/LABELS[selector],archive/LABELS[selector],dirs_exist_ok=True)

def main():
    parser=argparse.ArgumentParser();stage=parser.add_mutually_exclusive_group(required=True)
    for name in ('collect','fit','validate','all'):stage.add_argument('--'+name,action='store_true')
    parser.add_argument('--smoke',action='store_true');a=parser.parse_args()
    m=helper();assets=frozen(m)
    if a.all:
        if a.smoke:raise RuntimeError('--all cannot use --smoke')
        if not (BASE/'collection-smoke-approved.json').exists():collect(m,assets,True)
        collect(m,assets);fit()
        if not (BASE/'validation-smoke-approved.json').exists():validate(m,assets,True)
        validate(m,assets)
    elif a.collect:collect(m,assets,a.smoke)
    elif a.fit:
        if a.smoke:raise RuntimeError('--fit --smoke is undefined; fit requires full common rowset')
        fit()
    else:validate(m,assets,a.smoke)

if __name__=='__main__':main()

