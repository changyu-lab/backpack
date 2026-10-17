"""Independent two-sequence development trial: frozen C4 with mixed CTU budgets.

Run on the remote Linux host; this program never connects to SSH or edits inputs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

from batch_strip import prefix_hash
from evaluate import bd_rate
from matched_ra32 import METRICS, Resources, compress_trace, native_cpp, save, verify_record
from prepare import sha
from run_experiment import run

SEQUENCES = ('DrivingInCity', 'DrivingInCountry')
ALPHAS = (.10, .25)
NATIVE = dict(psnr='psnr', ws_psnr='wspsnr', s_psnr_nn='spsnr', cpp_psnr='cpppsnr')


def clone_command(command, encoder, prefix, reconstruction, features=None, alpha=None):
    """Clone frozen arguments, changing only executable and owned output paths."""
    cmd = list(map(str, command)); cmd[0] = str(encoder)
    cmd[cmd.index('-b')+1] = str(prefix)+'.vvc'
    if '-o' in cmd: cmd[cmd.index('-o')+1] = str(reconstruction)
    else: cmd += ['-o', str(reconstruction)]
    suffixes = {'VTMRCTrace': '.vtm.csv', 'SIBRCTrace': '.sibrc.csv',
                'VisualGazeTrace': '.gaze.csv', 'GazeSibrcTrace': '.collab.csv'}
    cmd = ['--'+key+'='+str(prefix)+suffixes[key] if
           (key := value.split('=', 1)[0].lstrip('-')) in suffixes else value for value in cmd]
    if features is not None:
        cmd += ['--VisualGazeMode=1', '--VisualGazeFeatures='+str(features)]
        if not any(v.startswith('--VisualGazeTrace=') for v in cmd):
            cmd += ['--VisualGazeTrace='+str(prefix)+'.gaze.csv']
    if alpha is not None:
        cmd += ['--GazeSibrcAlpha='+str(alpha), '--GazeSibrcTrace='+str(prefix)+'.collab.csv']
    return cmd


def csv_rows(path):
    opener=gzip.open if str(path).endswith('.gz') else open
    with opener(path,'rt',newline='') as source:return list(csv.DictReader(source))


def close(a,b):return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-7)


def join_feedback(collab, companions, width, alpha):
    """Join actual controller decisions/feedback, including skip-QP observations."""
    def index(rows, columns):
        result={}
        for row in rows:
            if not set(columns).issubset(row):raise ValueError('incomplete companion trace columns')
            key=(int(row['poc']),int(row['ctu']))
            if key in result:raise ValueError('duplicate companion CTU')
            if any(not math.isfinite(float(row[c])) for c in columns):raise ValueError('nonfinite companion trace')
            result[key]=row
        if set(result)!=set(collab):raise ValueError('companion CTU coverage differs')
        return result
    vtm=csv_rows(companions['vtm'])
    vcols=('poc','ctu','bits','qp','lambda','pic_left')
    decision=index([r for r in vtm if r['event']=='decision'],vcols)
    feedback=index([r for r in vtm if r['event']=='feedback'],vcols)
    for event in ('begin','picture'):
        rows=[r for r in vtm if r['event']==event]
        if len(rows)!=32 or {int(r['poc']) for r in rows}!=set(range(32)):
            raise ValueError('incomplete VTM picture events')
    sibrc=index(csv_rows(companions['sibrc']),('poc','ctu','bits','qp','base_qp','offset',
                 'lambda','base_lambda','actual_qp','fallback','pic_left'))
    gaze=index(csv_rows(companions['gaze']),('poc','ctu','bits','target','base_qp','qp','base_lambda',
                 'lambda','strip_before','strip_after','zero_feature_fallback')) if alpha else {}
    actual_diff=skip=gaze_fallback=0;previous_strip={};cols=math.ceil(width/128)
    def equal(row,column,value):
        if not close(row[column],value):raise ValueError('companion feedback mismatch: '+column)
    for key,c in collab.items():
        d=decision[key];f=feedback[key];s=sibrc[key]
        for column,value in [('bits',c['mixed_target']),('qp',c['base_qp']),('lambda',c['base_lambda']),('pic_left',c['frame_before'])]:equal(d,column,value)
        for column,value in [('bits',c['bits']),('lambda',c['lambda']),('pic_left',c['frame_after'])]:equal(f,column,value)
        for column,other in [('bits','bits'),('qp','qp'),('base_qp','base_qp'),('offset','sibrc_offset'),
                             ('lambda','lambda'),('base_lambda','base_lambda'),('fallback','sibrc_fallback'),('pic_left','frame_after')]:
            equal(s,column,c[other])
        equal(s,'actual_qp',f['qp'])
        actual_diff+=float(s['actual_qp'])!=c['qp'];skip+=float(s['actual_qp'])==-999
        if alpha:
            g=gaze[key]
            for column,value in [('bits',c['bits']),('target',c['strip_target']),('base_qp',c['base_qp']),
                                 ('qp',c['base_qp']),('base_lambda',c['base_lambda']),('lambda',c['base_lambda'])]:equal(g,column,value)
            if not close(float(g['strip_before'])-float(g['strip_after']),c['bits']):
                raise ValueError('gaze strip debit differs from coded bits')
            if key[1]%cols and not close(g['strip_before'],previous_strip[key[0]]):
                raise ValueError('discontinuous gaze strip budget')
            previous_strip[key[0]]=float(g['strip_after'])
            gaze_fallback+=float(g['zero_feature_fallback'])!=0
    return dict(feedback_join_verified=True,gaze_debits_verified=bool(alpha),
                actual_decision_qp_difference_ctus=actual_diff,skip_feedback_ctus=skip,
                gaze_zero_feature_fallback_ctus=gaze_fallback)


def check_trace(path, width, height, alpha, companions=None):
    """Hard-fail corruption; retain inactivity/fallback as eligibility evidence."""
    count = math.ceil(width/128)*math.ceil(height/128)
    seen={}; mixed=active=fallback=0;previous={}
    columns={'poc','ctu','alpha','original_target','strip_target','mixed_target',
             'base_qp','qp','base_lambda','lambda','sibrc_offset','sibrc_fallback',
             'frame_before','frame_after','bits'}
    rows=csv_rows(path)
    if not rows or not columns.issubset(rows[0]):raise ValueError('incomplete collaboration trace columns')
    for row in rows:
            values={key:float(row[key]) for key in columns}
            if not all(math.isfinite(v) for v in values.values()):raise ValueError('nonfinite collaboration trace')
            integer_columns=columns-{'alpha','base_lambda','lambda'}
            if any(values[key]!=int(values[key]) for key in integer_columns):
                raise ValueError('fractional integer trace field')
            identity=(int(values['poc']),int(values['ctu']))
            if identity in seen or identity[0] not in range(32) or identity[1] not in range(count):
                raise ValueError('duplicate or out-of-range CTU')
            seen[identity]=values
            if abs(values['alpha']-alpha)>1e-10:raise ValueError('wrong trace alpha')
            original=values['original_target']; strip=values['strip_target']; actual=values['mixed_target']
            expected=math.floor((1-alpha)*original+alpha*strip+.5) if alpha else original
            if original<1 or actual!=expected or (alpha and strip<1) or (not alpha and strip!=-1):
                raise ValueError('mixed target differs from specified blend/bypass')
            if values['frame_before']-values['frame_after']!=values['bits'] or values['bits']<0:
                raise ValueError('frame budget debit differs from coded bits')
            if values['qp']-values['base_qp']!=values['sibrc_offset']:
                raise ValueError('QP differs from SIBRC offset')
            if values['base_lambda']<=0 or values['lambda']<=0 or not close(
                    values['lambda'],values['base_lambda']*2**(values['sibrc_offset']/3)):
                raise ValueError('invalid SIBRC lambda scale')
            if identity[1] and (identity[0] not in previous or
                    previous[identity[0]]!=(identity[1]-1,values['frame_before'])):
                raise ValueError('discontinuous frame CTU budget')
            previous[identity[0]]=(identity[1],values['frame_after'])
            mixed += actual!=original
            active += values['sibrc_offset']!=0
            fallback += values['sibrc_fallback']!=0
    if len(seen)!=32*count:raise ValueError('incomplete 32-frame CTU coverage')
    joined=join_feedback(seen,companions,width,alpha) if companions else dict(feedback_join_verified=False)
    reasons=[]
    if alpha and not mixed:reasons.append('mixed_budget_inactive')
    if not active:reasons.append('sibrc_inactive')
    if joined.get('gaze_zero_feature_fallback_ctus'):reasons.append('gaze_zero_feature_fallback')
    return dict(ctus=len(seen),pocs=list(range(32)),mixed_active_ctus=mixed,
                sibrc_active_ctus=active,sibrc_fallback_ctus=fallback,
                frame_debits_verified=True,blend_verified=True,eligible=not reasons,
                ineligible_reasons=reasons,**joined)


def load(path):return json.loads(Path(path).read_text())


def verify_trace_artifact(trace):
    if sha(trace['path'])!=trace['gzip_sha256']:raise ValueError('compressed trace changed')
    digest=hashlib.sha256()
    with gzip.open(trace['path'],'rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    if digest.hexdigest()!=trace['uncompressed_sha256']:raise ValueError('raw trace identity differs')


def wait_output_space(output):
    while shutil.disk_usage(output).free<800000000:
        print('Waiting for free output disk:',output,flush=True)
        time.sleep(30)


def immutable_manifest(path, value):
    if path.exists():
        if load(path)!=value:raise ValueError('experiment identity changed; use a new independent output directory')
    else:save(path,value)
    return sha(path)


def verify_quality(record, quality, sphere, metric):
    verify_record(record)
    if (quality['frames']!=32 or quality['target_bps']!=record['target_bps'] or
        quality['source_prefix_sha256']!=record['spec']['source_prefix_sha256'] or
        quality['bitstream_sha256']!=sha(record['prefix']+'.vvc') or
        quality['sphere_sha256']!=sha(sphere) or quality['metrics_exe_sha256']!=sha(metric)):
        raise ValueError('reference quality identity differs')
    for name in NATIVE.values():
        values=quality['picture_y_'+name]
        if len(values)!=32 or not all(math.isfinite(v) for v in values):raise ValueError('incomplete reference metric')
        if abs(sum(values)/32-quality['mean_y_'+name])>1e-8:raise ValueError('reference metric mean mismatch')


def verify_features(features, spec):
    meta=load(Path(str(features)+'.json'))
    if (meta['output_sha256']!=sha(features) or meta['input_sha256']!=spec['source_prefix_sha256'] or
        meta['geometry']!=[spec['width'],spec['height'],128,10,32] or
        meta['mu_m']!=1 or meta['mu_s']!=1 or meta['motion_search']!=4):
        raise ValueError('frozen strip feature identity/geometry/coefficients differ')
    with features.open() as stream:
        header='VGFEATURES 1 '+' '.join(map(str,meta['geometry']))
        if stream.readline().strip()!=header:raise ValueError('frozen feature header differs')


def references(a):
    hashes={};cases={}
    def pin(path):hashes[str(path)]=sha(path)
    cfg=a.reference/'ra.cfg'
    required={'GOPSize':'32','PicReordering':'1','POC0IDR':'1','IntraPeriod':'32',
              'DecodingRefreshType':'1','CTUSize':'128','NumRefPics':'1','NumRefPicsSCC':'0'}
    parsed=dict(line.split(':',1) for line in cfg.read_text().splitlines() if ':' in line)
    if any(parsed.get(k,'').strip()!=v for k,v in required.items()):raise ValueError('RA32 refs1 configuration differs')
    pin(cfg)
    frozen=a.reference/'frozen-assets.json'
    for path,digest in load(frozen).items():
        if sha(path)!=digest:raise ValueError('historical frozen asset changed: '+path)
        hashes[path]=digest
    pin(frozen)
    for name in SEQUENCES:
        groups={}
        for method in ('anchor','C4'):
            group=[]
            for point in range(1,5):
                prefix=a.reference/'runs'/name/method/f'R{point}'
                rp=prefix.with_suffix('.run.json');qp=prefix.with_suffix('.quality.json')
                r=load(rp);q=load(qp);verify_quality(r,q,a.sphere,a.metric)
                cmd=r['command']
                if Path(cmd[cmd.index('-c')+1]).resolve()!=cfg.resolve():raise ValueError('actual RA config differs')
                if Path(cmd[cmd.index('-i')+1]).name!=r['spec']['filename']:raise ValueError('actual source filename differs')
                if method=='C4':
                    for flag in ('--SIBRCMode=3','--SIBRCFeature=4','--SIBRCMinOffset=-2','--SIBRCMaxOffset=2'):
                        if flag not in cmd:raise ValueError('frozen C4 setting differs: '+flag)
                if r['command'][r['command'].index('-f')+1]!='32':raise ValueError('reference frame count differs')
                for path,digest in r['outputs_sha256'].items():hashes[path]=digest
                for flag in ('-c','-i'):
                    dependency=Path(r['command'][r['command'].index(flag)+1])
                    if flag=='-c':pin(dependency)
                for arg in r['command']:
                    if arg.startswith(('--SIBRCStats=','--SIBRCModel=')):
                        asset=Path(arg.split('=',1)[1])
                        if asset.is_dir():
                            files=sorted(p for p in asset.rglob('*') if p.is_file())
                            if not files:raise ValueError('empty model directory')
                            for path in files:pin(path)
                        elif asset.is_file():pin(asset)
                        else:
                            files=sorted(asset.parent.glob(asset.name+'*'))
                            if not files:raise ValueError('missing frozen model files')
                            for path in files:
                                if path.is_file():pin(path)
                pin(rp);pin(qp);group.append((r,q))
            groups[method]=group
        s=groups['C4'][0][0]['spec'];cmd=groups['C4'][0][0]['command']
        source=Path(cmd[cmd.index('-i')+1]);size=s['width']*s['height']*3//2*(2 if s['depth']==10 else 1)*32
        if prefix_hash(source,size)!=s['source_prefix_sha256']:raise ValueError('source prefix changed')
        features=a.strip_reference/name/'features.txt';verify_features(features,s)
        pin(features);pin(Path(str(features)+'.json'))
        strips=[]
        for point in range(1,5):
            path=a.strip_reference/name/f'R{point}.result.json';r=load(path)
            if (r['stream_sha256']!=sha(a.strip_reference/name/f'R{point}.vvc') or
                r['features_sha256']!=sha(features) or r['pocs']!=list(range(32)) or
                not r['decoder_matches_reconstruction']):raise ValueError('strip reference changed')
            if (r['target_bps']!=groups['anchor'][point-1][0]['target_bps'] or
                r['reused_anchor_quality']!=groups['anchor'][point-1][1]):raise ValueError('strip/Anchor identity differs')
            for trace in r['traces']:verify_trace_artifact(trace);pin(Path(trace['path']))
            pin(path);pin(a.strip_reference/name/f'R{point}.vvc');strips.append(r)
        for r,q in groups['anchor']+groups['C4']:
            if Path(r['command'][r['command'].index('-i')+1]).resolve()!=source.resolve():raise ValueError('actual source paths differ')
            if r['spec']!=s:raise ValueError('reference sources/targets differ')
        if [r['target_bps'] for r,q in groups['anchor']]!=[r['target_bps'] for r,q in groups['C4']]:
            raise ValueError('C4 target ladder differs')
        cases[name]=dict(spec=s,source=source,features=features,groups=groups,strips=strips)
    return cases,hashes


def gates(a, cases, identity, resources):
    gatefile=a.output/'compatibility-approved.json'
    if gatefile.exists():
        gate=load(gatefile)
        if gate.get('identity')!=identity or not gate.get('passed') or len(gate['evidence'])!=4:
            raise ValueError('saved gate identity differs')
        for row in gate['evidence']:
            if sha(row['stream'])!=row['expected_sha256']:raise ValueError('saved gate bitstream changed')
            for trace in row['traces']:verify_trace_artifact(trace)
        return
    case=cases[SEQUENCES[0]];s=case['spec'];evidence=[]
    anchor,aq=case['groups']['anchor'][0];c4,cq=case['groups']['C4'][0];strip=case['strips'][0]
    definitions=[('disabled',anchor['command'],aq['bitstream_sha256'],None,None),
                 ('gaze_only',strip['command'],strip['stream_sha256'],None,None),
                 ('sibrc_only',c4['command'],cq['bitstream_sha256'],None,None),
                 ('combined_zero',c4['command'],cq['bitstream_sha256'],case['features'],0)]
    for label,old,expected,features,alpha in definitions:
        prefix=a.output/'compatibility'/label;prefix.parent.mkdir(exist_ok=True)
        wait_output_space(a.output)
        resources.acquire(3500000000,2*s['width']*s['height']*3*32)
        try:
            with tempfile.TemporaryDirectory(prefix='gate-',dir=a.scratch_root) as temp:
                cmd=clone_command(old,a.encoder,prefix,Path(temp)/'rec.yuv',features,alpha)
                save(prefix.with_suffix('.command.json'),cmd);run(cmd,prefix.with_suffix('.log'))
                if sha(str(prefix)+'.vvc')!=expected:raise ValueError('compatibility gate failed: '+label)
                if alpha==0:check_trace(str(prefix)+'.collab.csv',s['width'],s['height'],0)
                traces=[compress_trace(path) for path in prefix.parent.glob(prefix.name+'.*.csv')]
                evidence.append(dict(label=label,command=cmd,stream=str(prefix)+'.vvc',expected_sha256=expected,traces=traces))
                save(a.output/'compatibility-evidence.json',evidence)
        finally:resources.release(3500000000)
    save(gatefile,dict(passed=True,identity=identity,sequence=SEQUENCES[0],point=1,evidence=evidence,
                       scope='one representative development R1; limited empirical compatibility'))


def point(a,case,name,index,alpha,identity,resources):
    s=case['spec'];reference,cq=case['groups']['C4'][index-1]
    folder=a.output/name/('alpha'+str(alpha));folder.mkdir(parents=True,exist_ok=True)
    prefix=folder/f'R{index}';record=prefix.with_suffix('.result.json')
    if record.exists():
        row=load(record)
        if (row.get('sequence'),row.get('point'),row.get('alpha'),row.get('target_bps'))!=(name,index,alpha,reference['target_bps']):
            raise ValueError('saved point tuple differs')
        if not row.get('decoder_matches_reconstruction') or row.get('pocs')!=list(range(32)) or len(row.get('traces',[]))!=4 or not row.get('artifacts'):
            raise ValueError('incomplete saved point evidence')
        if row['identity']!=identity or row['stream_sha256']!=sha(str(prefix)+'.vvc'):
            raise ValueError('saved point identity/stream changed')
        for path,digest in row['artifacts'].items():
            if sha(path)!=digest:raise ValueError('saved point artifact changed')
        for trace in row['traces']:verify_trace_artifact(trace)
        mq=load(str(prefix)+'.metrics.json');nq=load(str(prefix)+'.spherical.json')
        quality=dict(mq['quality_mean_db'],cpp_psnr=native_cpp(nq,mq['frames']))
        if row['quality']!=quality or row['actual_bps']!=mq['actual_bps']:raise ValueError('saved point metrics differ')
        paths={key:str(prefix)+'.'+key+'.csv.gz' for key in ('vtm','sibrc','gaze')}
        activity=check_trace(str(prefix)+'.collab.csv.gz',s['width'],s['height'],alpha,paths)
        if row['activity']!=activity:raise ValueError('saved activity evidence differs')
        return row
    # Incomplete point outputs stay visible; only this point's own paths are retried.
    rawbytes=s['width']*s['height']*3*32;need=2500000000+2*rawbytes
    wait_output_space(a.output)
    resources.acquire(need,2*rawbytes)
    try:
        with tempfile.TemporaryDirectory(prefix='collab-',dir=a.scratch_root) as temp:
            rec=Path(temp)/'encoder.yuv';decoded=Path(temp)/'decoded.yuv'
            cmd=clone_command(reference['command'],a.encoder,prefix,rec,case['features'],alpha)
            save(prefix.with_suffix('.command.json'),cmd)
            seconds=run(cmd,prefix.with_suffix('.log'))
            text=prefix.with_suffix('.log').read_text(errors='replace')
            pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))))
            kinds=re.findall(r'POC\s+\d+.*?\(.*?\b([IPB])-SLICE',text)
            if pocs!=list(range(32)) or len(kinds)!=32 or 'I' not in kinds or 'B' not in kinds:
                raise ValueError('not complete 32-frame I/B RA')
            activity=check_trace(str(prefix)+'.collab.csv',s['width'],s['height'],alpha,
                {key:str(prefix)+'.'+key+'.csv' for key in ('vtm','sibrc','gaze')})
            evaluate=[sys.executable,str(Path(__file__).with_name('evaluate.py')),
                      '--input',case['source'],'--reconstruction',rec,'--trace',str(prefix)+'.vtm.csv',
                      '--bitstream',str(prefix)+'.vvc','--width',s['width'],'--height',s['height'],
                      '--frames',32,'--input-bitdepth',s['depth'],'--target-bps',reference['target_bps'],
                      '--fps',s['fps'],'--delay',32,'--sphere',a.sphere,'--output',str(prefix)+'.metrics.json']
            run(evaluate,prefix.with_suffix('.metrics.log'));mq=load(str(prefix)+'.metrics.json')
            if mq['input_sha256']!=s['source_prefix_sha256']:raise ValueError('metric source differs')
            decoder=[a.decoder,'-b',str(prefix)+'.vvc','-o',decoded]
            run(decoder,prefix.with_suffix('.decode.log'))
            if decoded.stat().st_size!=rawbytes or rec.stat().st_size!=rawbytes or sha(decoded)!=sha(rec):
                raise ValueError('independent decoder mismatch')
            native=[a.metric,case['source'],rec,s['width'],s['height'],32,a.sphere,str(prefix)+'.spherical.json',2,'all',s['depth']]
            run(native,prefix.with_suffix('.spherical.log'));nq=load(str(prefix)+'.spherical.json')
            values=mq['quality_mean_db'];values['cpp_psnr']=native_cpp(nq,mq['frames'])
            if any(not math.isfinite(values[k]) for k in METRICS):raise ValueError('nonfinite trial quality')
            traces=[compress_trace(str(prefix)+suffix) for suffix in ('.vtm.csv','.sibrc.csv','.gaze.csv','.collab.csv')]
            artifacts={str(path):sha(path) for path in folder.glob(prefix.name+'.*') if path!=record}
            row=dict(identity=identity,sequence=name,point=index,alpha=alpha,target_bps=reference['target_bps'],
                     actual_bps=mq['actual_bps'],bitrate_error_percent=mq['bitrate_error_percent'],quality=values,
                     relative_C4_db={m:values[m]-cq['mean_y_'+NATIVE[m]] for m in METRICS},
                     relative_C4_bitrate_percent=(mq['actual_bps']/cq['actual_bps']-1)*100,
                     seconds=seconds,command=cmd,evaluate_command=list(map(str,evaluate)),
                     decoder_command=list(map(str,decoder)),native_command=list(map(str,native)),
                     reconstruction_sha256=sha(rec),decoder_matches_reconstruction=True,pocs=pocs,
                     ra_frame_types=kinds,activity=activity,stream_sha256=sha(str(prefix)+'.vvc'),
                     features_sha256=sha(case['features']),traces=traces,artifacts=artifacts)
            save(record,row);return row
    finally:resources.release(need)


def summarize(cases, points, failures):
    comparisons={};complete=len(points)==16 and not failures
    for name in SEQUENCES:
        for alpha in ALPHAS:
            rows=sorted([p for p in points if p['sequence']==name and p['alpha']==alpha],key=lambda r:r['point'])
            if len(rows)!=4:continue
            result={}
            for baseline in ('anchor','C4'):
                refs=cases[name]['groups'][baseline]
                for metric in METRICS:
                    key=baseline+'_'+metric+'_bd_rate_percent'
                    try:result[key]=bd_rate([q['actual_bps'] for r,q in refs],
                          [q['mean_y_'+NATIVE[metric]] for r,q in refs],
                          [r['actual_bps'] for r in rows],[r['quality'][metric] for r in rows])
                    except ValueError as error:result[key+'_unavailable']=str(error)
            comparisons[name+':'+str(alpha)]=result
    averages={}
    for alpha in ALPHAS:
        keys=[b+'_'+m+'_bd_rate_percent' for b in ('anchor','C4') for m in METRICS]
        groups=[comparisons.get(n+':'+str(alpha),{}) for n in SEQUENCES]
        averages[str(alpha)]={k:sum(g[k] for g in groups)/2 for k in keys} if complete and all(
            k in g and math.isfinite(g[k]) for k in keys for g in groups) else None
    return dict(scope='two development sequences; not independent holdout',frames=32,refs=1,
                alphas=ALPHAS,expected_points=16,completed_points=len(points),failures=failures,
                comparisons=comparisons,average=averages,points=points,
                ineligible_points=[dict(sequence=p['sequence'],point=p['point'],alpha=p['alpha'],reasons=p['activity']['ineligible_reasons']) for p in points if p.get('activity',{}).get('eligible') is False],
                average_basis='both sequences, equal weight, all four targets; no selective exclusion',
                timing_comparable=False,formal_anchor_reruns=0,formal_CQP_reruns=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('encoder','decoder','metric','sphere','output','scratch-root'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--reference',type=Path,default=Path('/data/vtmrc-vvenc-ra32-20261014'))
    parser.add_argument('--strip-reference',type=Path,default=Path('/root/visual_gaze_ra32f_matched_20261015/results'))
    parser.add_argument('--workers',type=int,choices=range(1,9),default=2)
    a=parser.parse_args()
    for old in (a.reference,a.strip_reference):
        if any(path.resolve()==old.resolve() or old.resolve() in path.resolve().parents
               for path in (a.output,a.scratch_root)):
            raise ValueError('outputs/scratch must be independent of frozen references')
    a.output.mkdir(parents=True,exist_ok=True);a.scratch_root.mkdir(parents=True,exist_ok=True)
    cases,hashes=references(a)
    dependencies=[a.encoder,a.decoder,a.metric,a.sphere]+list(Path(__file__).parent.glob('*.py'))
    manifest=dict(frames=32,refs=1,sequences=SEQUENCES,alphas=ALPHAS,
                  method='round((1-alpha)*bVTM+alpha*bStrip), then frozen C4 final QP/lambda',
                  dependencies={str(p):sha(p) for p in dependencies},references=hashes,
                  sources={n:dict(c['spec'],path=str(c['source'])) for n,c in cases.items()})
    # JSON normalization keeps tuples stable across resumed processes.
    identity=immutable_manifest(a.output/'manifest.json',json.loads(json.dumps(manifest)))
    import psutil
    # Reservations have a fixed ceiling; actual available RAM is checked for
    # every acquisition so a busy host can later recover without restarting.
    capacity=min(24000000000,psutil.virtual_memory().total-1500000000)
    resources=Resources(capacity,a.scratch_root);gates(a,cases,identity,resources)
    points=[];failures={}
    save(a.output/'summary.json',summarize(cases,points,failures))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(point,a,cases[name],name,index,alpha,identity,resources):(name,index,alpha)
                 for name in SEQUENCES for alpha in ALPHAS for index in range(1,5)}
        for future in as_completed(futures):
            key=str(futures[future])
            try:points.append(future.result());print('Verified:',key,flush=True)
            except Exception as error:failures[key]=str(error);print('Failed:',key,str(error),flush=True)
            save(a.output/'summary.json',summarize(cases,points,failures))
    if failures:raise RuntimeError('development trial incomplete; complete averages withheld')


if __name__=='__main__':main()
