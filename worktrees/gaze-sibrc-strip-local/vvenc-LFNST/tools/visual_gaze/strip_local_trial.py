"""Independent AerialCity RA32 strip-local trial; run locally on the Linux host.

Never uses SSH. Refuses nonempty output directories: every invocation has its own
manifest, compatibility streams, four target results, and five compressed traces.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

from batch_strip import prefix_hash
from collab_trial import (clone_command, close, csv_rows, join_feedback, load,
                          verify_features, verify_quality)
from evaluate import bd_rate
from matched_ra32 import METRICS, Resources, compress_trace, native_cpp, save
from prepare import sha
from run_experiment import run

NAME='AerialCity'
NATIVE=dict(psnr='psnr',ws_psnr='wspsnr',s_psnr_nn='spsnr',cpp_psnr='cpppsnr')
REASONS={0:'none',1:'invalid_prediction',2:'negative_or_nonfinite_budget',3:'below_minimum',4:'search_failed'}
TRACES=('vtm','sibrc','gaze','collab','strip')


def prepare_output(output,scratch,frozen):
    """Reject overlap and reuse before creating any experimental artifacts."""
    output=Path(output).resolve();scratch=Path(scratch).resolve()
    if output==scratch or output in scratch.parents or scratch in output.parents:
        raise ValueError('output and scratch must be separate directories')
    for root in map(lambda p:Path(p).resolve(),frozen):
        for path in (output,scratch):
            if path==root or root in path.parents or path in root.parents:
                raise ValueError('output/scratch overlaps frozen references')
    if output.exists() and any(output.iterdir()):
        raise ValueError('nonempty output refused; no resume: select a new independent directory')
    output.mkdir(parents=True,exist_ok=True);scratch.mkdir(parents=True,exist_ok=True)


def set_flags(command,flags):
    cmd=[v for v in command if v.split('=',1)[0].lstrip('-') not in flags]
    return cmd+['--'+key+'='+str(value) for key,value in flags.items()]


def owned_command(command,encoder,prefix,reconstruction):
    # Remove legacy experimental flags before cloning. Other frozen arguments,
    # including models, GOP, targets, refs, and picture controls, stay verbatim.
    cmd=[str(v) for v in command if not str(v).startswith(('--GazeSibrcStripTrace=','--GazeSibrcStripLocal='))]
    cmd=clone_command(cmd,encoder,prefix,reconstruction)
    suffixes=dict(SIBRCResidual='.residual.bin',SummaryOutFilename='.summary.txt',SummaryPicFilenameBase='.summary-picture',tracefile='.debug.trace')
    for i,value in enumerate(cmd):
        key=value.split('=',1)[0].lstrip('-')
        if key in suffixes and '=' in value and value.split('=',1)[1]:cmd[i]='--'+key+'='+str(prefix)+suffixes[key]
    return cmd


def method_command(command,encoder,prefix,reconstruction,features):
    cmd=owned_command(command,encoder,prefix,reconstruction)
    return set_flags(cmd,dict(VisualGazeMode=1,VisualGazeFeatures=features,
        VisualGazeTrace=str(prefix)+'.gaze.csv',GazeSibrcAlpha=1,GazeSibrcStripLocal=1,
        GazeSibrcTrace=str(prefix)+'.collab.csv',GazeSibrcStripTrace=str(prefix)+'.strip.csv'))


def stats(values):
    return dict(min=min(values),max=max(values),mean=sum(values)/len(values)) if values else None


def verify_row_formula(rows,features,width,height):
    cols=math.ceil(width/128);count=cols*math.ceil(height/128)
    latitude=[]
    for row in range(math.ceil(height/128)):
        ys=range(row*128,min((row+1)*128,height))
        latitude.append(sum(math.sin((y+.5)*math.pi/height) for y in ys)/len(ys)*cols)
    average=sum(latitude)/len(latitude)
    pixels=[min(128,width-(ctu%cols)*128)*min(128,height-(ctu//cols)*128) for ctu in range(count)]
    for r in rows:
        poc=int(r['poc']);ctu=int(r['ctu'])
        if ctu%cols:continue
        end=min(ctu+cols,count)
        all_features=sum(features[poc,c] for c in range(ctu,count))
        strip_features=sum(features[poc,c] for c in range(ctu,end))
        if all_features==0:all_features=sum(pixels[ctu:]);strip_features=sum(pixels[ctu:end])
        expected=float(r['frame_before'])*strip_features/all_features*latitude[ctu//cols]/average
        if not close(r['strip_target'],expected):raise ValueError('row target differs from frozen feature/latitude formula')


def verify_corrections(rows,sibrc):
    for r in rows:
        poc=int(r['poc']);ctu=int(r['ctu'])
        for before,after in (('rate_correction_before','rate_bias'),('dist_correction_before','dist_bias')):
            expected=0 if ctu==0 else float(sibrc[poc,ctu-1][after])
            if before not in r or not close(r[before],expected):raise ValueError('SIBRC correction reset or continuity mismatch: '+before)


def frozen_feature_values(path,width,height):
    count=math.ceil(width/128)*math.ceil(height/128);result={}
    with Path(path).open() as stream:
        next(stream)
        for line in stream:
            poc,ctu,spatial,temporal=line.split();key=int(poc),int(ctu)
            if key in result:raise ValueError('duplicate frozen feature CTU')
            result[key]=(float(spatial),float(temporal))
    if set(result)!={(p,c) for p in range(32) for c in range(count)}:raise ValueError('frozen feature coverage differs')
    if any(not math.isfinite(v) or v<0 for pair in result.values() for v in pair):raise ValueError('invalid frozen feature')
    return result


def check_strip_trace(path,width,height,companions=None,features=None):
    """Check actual debits/boundaries, retaining raw infeasibility diagnostics."""
    cols=math.ceil(width/128);count=cols*math.ceil(height/128)
    fields={'poc','ctu','strip_begin','strip_end','strip_target','strip_before','strip_after',
            'frame_before','frame_after','bits','minimum_bits','maximum_bits','predicted_remaining',
            'fallback_reason','base_qp','qp','base_lambda','lambda','offset','fallback'}
    integers={'poc','ctu','strip_begin','strip_end','fallback_reason','base_qp','qp','offset','fallback','bits'}
    indexed={};previous={};targets={};totals={};reasons=Counter();active=0;range_counts=Counter();bad_budget=0
    for row in csv_rows(path):
        if not fields.issubset(row):raise ValueError('incomplete strip trace columns')
        v={k:float(row[k]) for k in fields}
        for correction in ('rate_correction_before','dist_correction_before'):
            if correction in row:v[correction]=float(row[correction])
        if any(not math.isfinite(v[k]) or v[k]!=int(v[k]) for k in integers):raise ValueError('invalid integer strip trace field')
        key=(int(v['poc']),int(v['ctu']));poc,ctu=key
        if key in indexed or poc not in range(32) or ctu not in range(count):raise ValueError('duplicate/out-of-range strip CTU')
        begin=ctu//cols*cols;end=min(begin+cols,count);strip=(poc,begin)
        if v['strip_begin']!=begin or v['strip_end']!=end:raise ValueError('wrong strip search boundaries')
        reason=int(v['fallback_reason'])
        if reason not in REASONS:raise ValueError('unknown fallback reason')
        if v['fallback'] not in (0,1) or bool(reason)!=bool(v['fallback']):raise ValueError('fallback flag/reason differs')
        bounds=[v[k] for k in ('minimum_bits','maximum_bits','predicted_remaining')]
        if not all(math.isfinite(x) for x in bounds):
            if reason!=1:raise ValueError('nonfinite model prediction without invalid_prediction reason')
            range_counts['invalid_prediction']+=1
        else:
            if v['minimum_bits']>v['maximum_bits'] or v['minimum_bits']<0:raise ValueError('invalid model rate interval')
            range_counts['prediction_below_minimum']+=v['predicted_remaining']<v['minimum_bits']
            range_counts['prediction_above_maximum']+=v['predicted_remaining']>v['maximum_bits']
            if math.isfinite(v['strip_before']):
                range_counts['budget_below_minimum']+=v['strip_before']<v['minimum_bits']
                range_counts['budget_above_maximum']+=v['strip_before']>v['maximum_bits']
        finite_budget=all(math.isfinite(v[k]) for k in ('strip_target','strip_before','strip_after'))
        if not finite_budget:
            if reason!=2:raise ValueError('nonfinite strip budget without budget fallback')
            bad_budget+=1
        if not all(math.isfinite(v[k]) for k in ('frame_before','frame_after','base_lambda','lambda')):raise ValueError('nonfinite controller fields')
        if v['bits']<0 or not close(v['frame_before']-v['frame_after'],v['bits']):raise ValueError('frame debit mismatch')
        if finite_budget and not close(v['strip_before']-v['strip_after'],v['bits']):raise ValueError('strip debit mismatch')
        if strip not in targets:targets[strip]=v['strip_target'];totals[strip]=0
        elif not (close(targets[strip],v['strip_target']) or math.isnan(targets[strip]) and math.isnan(v['strip_target'])):raise ValueError('strip target changed within row')
        if ctu==begin and finite_budget and not close(v['strip_target'],v['strip_before']):raise ValueError('strip initial budget differs from target')
        if ctu:
            if poc not in previous or previous[poc]['ctu']!=ctu-1 or not close(previous[poc]['frame_after'],v['frame_before']):raise ValueError('discontinuous frame feedback')
            before=previous[poc]['strip_after'] if ctu!=begin else v['strip_before']
            if ctu!=begin and math.isfinite(before) and math.isfinite(v['strip_before']) and not close(before,v['strip_before']):raise ValueError('discontinuous strip feedback')
        if v['qp']-v['base_qp']!=v['offset']:raise ValueError('final QP offset differs')
        if v['base_lambda']<=0 or v['lambda']<=0 or not close(v['lambda'],v['base_lambda']*2**(v['offset']/3)):raise ValueError('final lambda scaling differs')
        indexed[key]=v;previous[poc]=v;totals[strip]+=v['bits'];reasons[str(reason)]+=1;active+=v['offset']!=0
    if len(indexed)!=32*count:raise ValueError('incomplete 32-frame CTU coverage')
    joined={}
    if companions:
        collab={}
        for row in csv_rows(companions['collab']):
            v={k:float(value) for k,value in row.items()}
            key=(int(v['poc']),int(v['ctu']))
            if key in collab:raise ValueError('duplicate collaboration CTU')
            collab[key]=v
        if set(collab)!=set(indexed):raise ValueError('collaboration coverage differs')
        for key,c in collab.items():
            s=indexed[key]
            if c['alpha']!=1 or not close(c['mixed_target'],c['strip_target']):raise ValueError('strip CTU initial target not used')
            for col in ('base_qp','qp','base_lambda','lambda','frame_before','frame_after','bits'):
                if not close(c[col],s[col]):raise ValueError('strip/collaboration mismatch: '+col)
            if not close(c['sibrc_offset'],s['offset']) or not close(c['sibrc_fallback'],s['fallback']):raise ValueError('strip controller action differs')
        joined=join_feedback(collab,companions,width,1)
        gaze={(int(r['poc']),int(r['ctu'])):r for r in csv_rows(companions['gaze'])}
        sibrc={(int(r['poc']),int(r['ctu'])):r for r in csv_rows(companions['sibrc'])}
        verify_corrections(indexed.values(),sibrc)
        selected_features={}
        frozen=frozen_feature_values(features,width,height) if features else None
        for key,s in indexed.items():
            selected_features[key]=float(gaze[key]['feature'])
            if frozen and not close(selected_features[key],frozen[key][0 if sibrc[key]['kind']=='I' else 1]):raise ValueError('gaze feature differs from frozen input')
            begin=int(s['strip_begin']);end=int(s['strip_end'])
            tail=sum(float(gaze[key[0],c]['feature']) for c in range(key[1],end))
            weight=selected_features[key]
            if tail==0:
                pixels=lambda c:min(128,width-c%cols*128)*min(128,height-c//cols*128)
                tail=sum(pixels(c) for c in range(key[1],end));weight=pixels(key[1])
            expected=max(1,math.floor(s['strip_before']*weight/tail+.5))
            if not close(collab[key]['mixed_target'],expected):raise ValueError('CTU initial target differs from row feature proportion')
            for col in ('strip_before','strip_after','bits'):
                if not close(gaze[key][col],s[col]):raise ValueError('strip/gaze feedback differs: '+col)
        verify_row_formula(indexed.values(),selected_features,width,height)
        joined.update(row_formula_verified=True,frozen_features_verified=bool(frozen),correction_continuity_verified=True)
    deviations=[totals[key]-target for key,target in targets.items() if math.isfinite(target)]
    percentages=[100*(totals[key]-target)/target for key,target in targets.items() if math.isfinite(target) and target>0]
    ineligible=[]
    if not active:ineligible.append('sibrc_inactive')
    if joined.get('gaze_zero_feature_fallback_ctus'):ineligible.append('gaze_zero_feature_fallback')
    return dict(ctus=len(indexed),strips=len(targets),pocs=list(range(32)),
        strip_boundaries_verified=True,strip_debits_verified=True,frame_debits_verified=True,
        row_targets_fixed=True,sibrc_active_ctus=active,fallback_reason_counts={str(k):reasons[str(k)] for k in REASONS},
        fallback_reason_labels={str(k):v for k,v in REASONS.items()},prediction_range_counts=dict(range_counts),
        nonfinite_budget_ctus=bad_budget,strip_target_actual_deviation_bits=stats(deviations),
        strip_target_actual_deviation_percent=stats(percentages),eligible=not ineligible,ineligible_reasons=ineligible,
        **joined)


def references(a):
    """AerialCity-only loader; no dependency on the old two-sequence loader."""
    hashes={}
    def pin(path):
        path=Path(path);hashes[str(path)]=sha(path)
    cfg=a.reference/'ra.cfg'
    required=dict(GOPSize='32',PicReordering='1',POC0IDR='1',IntraPeriod='32',DecodingRefreshType='1',CTUSize='128',NumRefPics='1',NumRefPicsSCC='0')
    parsed=dict(line.split(':',1) for line in cfg.read_text().splitlines() if ':' in line)
    if any(parsed.get(k,'').strip()!=v for k,v in required.items()):raise ValueError('RA32 refs1 configuration differs')
    pin(cfg);frozen=a.reference/'frozen-assets.json'
    for path,digest in load(frozen).items():
        if sha(path)!=digest:raise ValueError('frozen asset changed: '+path)
        hashes[path]=digest
    pin(frozen);groups={}
    for method in ('anchor','C4'):
        group=[]
        for point in range(1,5):
            prefix=a.reference/'runs'/NAME/method/('R'+str(point))
            rp=prefix.with_suffix('.run.json');qp=prefix.with_suffix('.quality.json')
            r=load(rp);q=load(qp);verify_quality(r,q,a.sphere,a.metric);cmd=r['command']
            if Path(cmd[cmd.index('-c')+1]).resolve()!=cfg.resolve() or cmd[cmd.index('-f')+1]!='32':raise ValueError('actual RA/frame configuration differs')
            if Path(cmd[cmd.index('-i')+1]).name!=r['spec']['filename']:raise ValueError('source filename differs')
            if method=='C4' and any(flag not in cmd for flag in ('--SIBRCMode=3','--SIBRCFeature=4','--SIBRCMinOffset=-2','--SIBRCMaxOffset=2')):raise ValueError('frozen C4 settings differ')
            for path,digest in r['outputs_sha256'].items():hashes[path]=digest
            for arg in cmd:
                if arg.startswith(('--SIBRCStats=','--SIBRCModel=')):
                    asset=Path(arg.split('=',1)[1]);files=list(asset.rglob('*')) if asset.is_dir() else [asset] if asset.is_file() else list(asset.parent.glob(asset.name+'*'))
                    files=[p for p in files if p.is_file()]
                    if not files:raise ValueError('missing model/stats files')
                    for path in files:pin(path)
            pin(rp);pin(qp);group.append((r,q))
        groups[method]=group
    s=groups['C4'][0][0]['spec'];cmd=groups['C4'][0][0]['command'];source=Path(cmd[cmd.index('-i')+1])
    for r,q in groups['anchor']+groups['C4']:
        if r['spec']!=s or Path(r['command'][r['command'].index('-i')+1]).resolve()!=source.resolve():raise ValueError('source identity differs between reference points')
    if [r['target_bps'] for r,q in groups['anchor']]!=[r['target_bps'] for r,q in groups['C4']]:raise ValueError('reference targets differ')
    if s['width']!=3840 or s['height']!=1920:raise ValueError('expected AerialCity 3840x1920')
    size=s['width']*s['height']*3//2*(2 if s['depth']==10 else 1)*32
    if prefix_hash(source,size)!=s['source_prefix_sha256']:raise ValueError('source prefix changed')
    features=a.strip_reference/NAME/'features.txt';verify_features(features,s);pin(features);pin(str(features)+'.json')
    return dict(spec=s,source=source,features=features,groups=groups),hashes


def wait_output_space(output):
    while shutil.disk_usage(output).free<128*1024**2:
        print('Waiting for 128 MiB free output space:',output,flush=True);time.sleep(5)


def gates(a,case,identity,resources):
    """Compare both executables with owned outputs for every legacy path."""
    anchor=case['groups']['anchor'][0][0]['command'];c4=case['groups']['C4'][0][0]['command']
    definitions=[('anchor',anchor,{}),('gaze_only',anchor,dict(VisualGazeMode=1,VisualGazeFeatures=case['features'])),
        ('sibrc_only',c4,{}),('combined_zero',c4,dict(VisualGazeMode=1,VisualGazeFeatures=case['features'],GazeSibrcAlpha=0)),
        ('combined_point1',c4,dict(VisualGazeMode=1,VisualGazeFeatures=case['features'],GazeSibrcAlpha=.1))]
    evidence=[];s=case['spec'];rawbytes=s['width']*s['height']*3*32;need=2500000000+rawbytes
    for label,command,flags in definitions:
        runs=[]
        for variant,encoder in (('old',a.old_encoder),('new',a.encoder)):
            prefix=a.output/'compatibility'/label/variant;prefix.parent.mkdir(parents=True,exist_ok=True)
            wait_output_space(a.output);resources.acquire(need,rawbytes)
            try:
                with tempfile.TemporaryDirectory(prefix='strip-gate-',dir=a.scratch_root) as temp:
                    cmd=owned_command(command,encoder,prefix,Path(temp)/'rec.yuv')
                    extra=dict(flags)
                    if extra.get('VisualGazeMode'):extra['VisualGazeTrace']=str(prefix)+'.gaze.csv'
                    if 'GazeSibrcAlpha' in extra:extra['GazeSibrcTrace']=str(prefix)+'.collab.csv'
                    cmd=set_flags(cmd,extra)
                    save(prefix.with_suffix('.command.json'),cmd);seconds=run(cmd,prefix.with_suffix('.log'))
                    runs.append(dict(variant=variant,command=cmd,seconds=seconds,stream=str(prefix)+'.vvc',sha256=sha(str(prefix)+'.vvc'),
                        traces=[compress_trace(p) for p in prefix.parent.glob(prefix.name+'.*.csv')]))
            finally:resources.release(need)
        same=runs[0]['sha256']==runs[1]['sha256']
        evidence.append(dict(label=label,bitstream_identical=same,runs=runs));save(a.output/'compatibility-evidence.json',evidence)
        if not same:raise ValueError('legacy bitstream compatibility failed: '+label)
    save(a.output/'compatibility-approved.json',dict(identity=identity,passed=True,sequence=NAME,point=1,evidence=evidence,
        scope='five old/new legacy paths at AerialCity R1 only; limited empirical compatibility'))


def quality_crosscheck(mq,nq):
    values=dict(mq['quality_mean_db']);values['cpp_psnr']=native_cpp(nq,mq['frames'])
    for metric in ('psnr','ws_psnr','s_psnr_nn'):
        key='picture_y_'+NATIVE[metric]
        if key not in nq and metric!='s_psnr_nn':continue
        native=nq.get(key,[])
        if len(native)!=32 or any(not math.isfinite(v) for v in native):raise ValueError('incomplete native metric: '+metric)
        if len(mq['frames'])!=32 or max(abs(f[metric]-v) for f,v in zip(mq['frames'],native))>1e-8:raise ValueError('Python/native metric differs: '+metric)
    if any(not math.isfinite(values[k]) for k in METRICS):raise ValueError('nonfinite quality')
    return values


def point(a,case,index,identity,resources):
    s=case['spec'];reference,cq=case['groups']['C4'][index-1]
    folder=a.output/NAME;folder.mkdir(exist_ok=True);prefix=folder/('R'+str(index));record=prefix.with_suffix('.result.json')
    rawbytes=s['width']*s['height']*3*32;need=2500000000+2*rawbytes
    wait_output_space(a.output);resources.acquire(need,2*rawbytes)
    try:
        with tempfile.TemporaryDirectory(prefix='strip-local-',dir=a.scratch_root) as temp:
            rec=Path(temp)/'encoder.yuv';decoded=Path(temp)/'decoded.yuv'
            cmd=method_command(reference['command'],a.encoder,prefix,rec,case['features']);save(prefix.with_suffix('.command.json'),cmd)
            seconds=run(cmd,prefix.with_suffix('.log'));text=prefix.with_suffix('.log').read_text(errors='replace')
            pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))));kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
            if pocs!=list(range(32)) or len(kinds)!=32 or 'I' not in kinds or 'B' not in kinds:raise ValueError('not complete 32-frame I/B RA')
            activity=check_strip_trace(str(prefix)+'.strip.csv',s['width'],s['height'],{key:str(prefix)+'.'+key+'.csv' for key in ('vtm','sibrc','gaze','collab')},case['features'])
            evaluate=[sys.executable,str(Path(__file__).with_name('evaluate.py')),'--input',case['source'],'--reconstruction',rec,'--trace',str(prefix)+'.vtm.csv','--bitstream',str(prefix)+'.vvc','--width',s['width'],'--height',s['height'],'--frames',32,'--input-bitdepth',s['depth'],'--target-bps',reference['target_bps'],'--fps',s['fps'],'--delay',32,'--sphere',a.sphere,'--output',str(prefix)+'.metrics.json']
            run(evaluate,prefix.with_suffix('.metrics.log'));mq=load(str(prefix)+'.metrics.json')
            if mq['input_sha256']!=s['source_prefix_sha256']:raise ValueError('metric source differs')
            decoder=[a.decoder,'-b',str(prefix)+'.vvc','-o',decoded];run(decoder,prefix.with_suffix('.decode.log'))
            if rec.stat().st_size!=rawbytes or decoded.stat().st_size!=rawbytes or sha(decoded)!=sha(rec):raise ValueError('independent decoder mismatch')
            decoded.unlink();native=[a.metric,case['source'],rec,s['width'],s['height'],32,a.sphere,str(prefix)+'.spherical.json',2,'all',s['depth']]
            run(native,prefix.with_suffix('.spherical.log'));nq=load(str(prefix)+'.spherical.json');values=quality_crosscheck(mq,nq)
            traces=[compress_trace(str(prefix)+'.'+key+'.csv') for key in TRACES]
            artifacts={str(p):sha(p) for p in folder.glob(prefix.name+'.*') if p!=record}
            row=dict(identity=identity,sequence=NAME,point=index,alpha=1,strip_local=True,target_bps=reference['target_bps'],actual_bps=mq['actual_bps'],bitrate_error_percent=mq['bitrate_error_percent'],quality=values,seconds=seconds,command=cmd,
                evaluate_command=list(map(str,evaluate)),decoder_command=list(map(str,decoder)),native_command=list(map(str,native)),
                reconstruction_sha256=sha(rec),decoder_matches_reconstruction=True,pocs=pocs,ra_frame_types=kinds,
                quality_validation=dict(python_metrics_frames=32,native_s_cpp_frames=32,s_psnr_nn_crosschecked_frames=32,native_psnr_ws_available=all('picture_y_'+key in nq for key in ('psnr','wspsnr'))),
                activity=activity,stream_sha256=sha(str(prefix)+'.vvc'),features_sha256=sha(case['features']),traces=traces,artifacts=artifacts,
                relative_C4_db={m:values[m]-cq['mean_y_'+NATIVE[m]] for m in METRICS},relative_C4_bitrate_percent=100*(mq['actual_bps']/cq['actual_bps']-1))
            save(record,row);return row
    finally:resources.release(need)


def summarize(case,points,failures):
    complete=len(points)==4 and {p['point'] for p in points}==set(range(1,5)) and not failures
    comparisons=None;seconds=None;timings={}
    if complete:
        points=sorted(points,key=lambda p:p['point']);comparisons={};seconds=sum(p['seconds'] for p in points)
        for baseline in ('anchor','C4'):
            refs=case['groups'][baseline]
            for metric in METRICS:
                key=baseline+'_'+metric+'_bd_rate_percent'
                try:comparisons[key]=bd_rate([q['actual_bps'] for r,q in refs],[q['mean_y_'+NATIVE[metric]] for r,q in refs],[p['actual_bps'] for p in points],[p['quality'][metric] for p in points])
                except ValueError as error:comparisons[key+'_unavailable']=str(error)
            # Archived wall seconds may describe different host contention.
            old=[r.get('elapsed_seconds',r.get('seconds')) for r,q in refs]
            total=sum(old) if all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in old) else None
            timings[baseline]=dict(archived_seconds_sum=total,delta_t_percent=100*(seconds/total-1) if total else None)
    return dict(scope='AerialCity development only; four frozen targets; no holdout claim',frames=32,refs=1,
        expected_points=4,completed_points=len(points),failures=failures,comparisons=comparisons,seconds_sum=seconds,
        archived_timing=timings,timing_comparable=False,timing_caveat='wall seconds against archived runs; host/build/contention may differ',
        points=points,ineligible_points=[dict(point=p['point'],reasons=p['activity']['ineligible_reasons']) for p in points if not p['activity']['eligible']],
        inclusion_basis='all four targets retained including fallback/inactivity; no selective exclusions')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('encoder','decoder','metric','sphere','output','scratch-root'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--old-encoder',type=Path,default=Path('/root/gaze_sibrc_collab_20261016/src/bin/release-static/vvencFFapp'))
    parser.add_argument('--reference',type=Path,default=Path('/data/vtmrc-vvenc-ra32-20261014'))
    parser.add_argument('--strip-reference',type=Path,default=Path('/root/visual_gaze_ra32f_matched_20261015/results'))
    parser.add_argument('--workers',type=int,choices=range(1,9),default=4);a=parser.parse_args()
    prepare_output(a.output,a.scratch_root,[a.reference,a.strip_reference]);case,hashes=references(a)
    deps=[a.encoder,a.old_encoder,a.decoder,a.metric,a.sphere]+list(Path(__file__).parent.glob('*.py'))
    manifest=dict(frames=32,refs=1,sequences=[NAME],points=[1,2,3,4],alpha=1,strip_local=True,
        method='feature row budget; SIBRC search current CTU to row end using raw remaining row budget',
        dependencies={str(p):sha(p) for p in deps},references=hashes,source=dict(case['spec'],path=str(case['source'])),
        selected_commands={method:[r['command'] for r,q in rows] for method,rows in case['groups'].items()},
        resume_supported=False,workers=a.workers)
    save(a.output/'manifest.json',manifest);identity=sha(a.output/'manifest.json')
    import psutil
    capacity=min(24000000000,psutil.virtual_memory().total-1500000000)
    if capacity<2500000000+2*case['spec']['width']*case['spec']['height']*3*32:raise ValueError('insufficient total RAM capacity')
    resources=Resources(capacity,a.scratch_root);gates(a,case,identity,resources)
    points=[];failures={};save(a.output/'summary.json',summarize(case,points,failures))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(point,a,case,index,identity,resources):index for index in range(1,5)}
        for future in as_completed(futures):
            index=futures[future]
            try:points.append(future.result());print('Verified:',NAME,index,flush=True)
            except Exception as error:failures[str(index)]=str(error);print('Failed:',NAME,index,str(error),flush=True)
            save(a.output/'summary.json',summarize(case,points,failures))
    if failures:raise RuntimeError('AerialCity trial incomplete; four-point comparisons withheld')


if __name__=='__main__':main()
