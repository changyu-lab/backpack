"""Fourteen ERP sequences, LDP16, 17 frames: VTMRC versus strip allocation.

Resume completed sequences only. Partial sequences are rerun in full. Missing or
invalid sequences never disappear from the denominator of the batch average.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from prepare import sha
from run_experiment import run

METRICS=('psnr_bd_rate_percent','ws_psnr_bd_rate_percent','s_psnr_nn_bd_rate_percent')


def sequence_info(path,frames):
    m=re.fullmatch(r'(.+)_(\d+)x(\d+)_(\d+)fps_(8|10)bit_420_erp.yuv',path.name)
    if not m:raise ValueError('unrecognized sequence filename: '+path.name)
    name,w,h,fps,depth=m.groups();w,h,fps,depth=map(int,(w,h,fps,depth))
    size=w*h*3//2*(1 if depth==8 else 2)*frames
    if path.stat().st_size<size:raise ValueError('source shorter than requested frames: '+name)
    return dict(name=name,input=str(path.absolute()),width=w,height=h,fps=fps,
                input_bitdepth=depth,frames=frames,ctu=128,prefix_bytes=size,
                source_size=path.stat().st_size,source_mtime_ns=path.stat().st_mtime_ns)


def aggregate(expected,reports):
    missing=[n for n in expected if n not in reports]
    rows={}
    for name,report in reports.items():
        row=next((r for r in report['comparisons'] if r['mode']==1),{})
        rows[name]={key:row.get(key) for key in METRICS}
    valid=not missing and all(rows[n][k] is not None and math.isfinite(rows[n][k]) for n in expected for k in METRICS)
    return dict(expected_sequences=len(expected),completed_sequences=len(reports),missing=missing,
                per_sequence=rows,average={k:sum(rows[n][k] for n in expected)/len(expected) for k in METRICS} if valid else None,
                average_basis='equal-weight arithmetic mean of every expected sequence BD-rate; no selective exclusions',
                sibrc_acceptance='not evaluated: requires matched SIBRC results')


def prefix_hash(path,count):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while count:
            chunk=source.read(min(1048576,count))
            if not chunk:raise ValueError('truncated prefix')
            digest.update(chunk);count-=len(chunk)
    return digest.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sequences',type=Path,default=Path('I:/Sequences360'))
    for name in ('encoder','decoder','sphere','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--frames',type=int,default=17)
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    items=[sequence_info(f,a.frames) for f in sorted(a.sequences.glob('*.yuv'))]
    if len(items)!=14:p.error('expected exactly 14 sequence inputs')
    a.output.mkdir(parents=True,exist_ok=True)
    encoder_hash=sha(a.encoder)
    manifest=dict(frames=a.frames,configuration='ldp16',modes=[0,1],qps=[22,27,32,37],
                  mu_m=1,mu_s=1,f=20,ctu=128,encoder_sha256=encoder_hash,sequences=items,
                  dependencies={str(f):sha(f) for f in [a.decoder,a.sphere,Path('cfg/visual_gaze_ldp16.cfg')]+[
                      Path(__file__).with_name(n) for n in ('prepare.py','evaluate.py','run_experiment.py','batch_strip.py')]})
    manifest_path=a.output/'manifest.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text())!=manifest:
        raise ValueError('batch manifest changed; use a fresh output directory')
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if a.dry_run:
        print('Validated 14 inputs; 168 main encodes + 14 repeat checks',flush=True);return
    reports={};failures={};expected=[i['name'] for i in items]
    def save():
        summary=aggregate(expected,reports);summary['failures']=failures
        (a.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    save()
    for info in items:
        name=info['name'];work=a.output/name;work.mkdir(exist_ok=True)
        result=work/'results/report.json'
        if result.exists():
            r=json.loads(result.read_text())
            if r['encoder_sha256']!=encoder_hash or r['frames']!=a.frames or r.get('modes')!=[0,1] or len(r['results'])!=8:
                raise ValueError('incompatible saved report: '+name)
            provenance=json.loads((work/'input.json').read_text())
            if provenance['source_prefix_sha256']!=prefix_hash(Path(info['input']),info['prefix_bytes']):
                raise ValueError('saved source prefix changed: '+name)
            if r['features_sha256']!=sha(work/'features.txt'):raise ValueError('saved feature file changed')
            for row in r['results']:
                prefix=work/'results'/f"mode{row['mode']}_qp{row['qp']}"
                if row['stream_sha256']!=sha(prefix.with_suffix('.vvc')) or row['trace_sha256']!=sha(prefix.with_suffix('.rc.csv')):
                    raise ValueError('saved stream/trace changed')
            reports[name]=r;save();print('Resume complete:',name,flush=True);continue
        try:
            print('Preparing:',name,flush=True)
            source=work/'source.yuv';features=work/'features.txt'
            digest=hashlib.sha256()
            with Path(info['input']).open('rb') as src,source.open('wb') as dst:
                remaining=info['prefix_bytes']
                while remaining:
                    chunk=src.read(min(1048576,remaining))
                    if not chunk:raise ValueError('source truncated during prefix copy')
                    dst.write(chunk);digest.update(chunk);remaining-=len(chunk)
            provenance=dict(info,source_prefix_sha256=digest.hexdigest())
            (work/'input.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
            metadata=json.loads(features.with_suffix('.txt.json').read_text()) if features.with_suffix('.txt.json').exists() else {}
            cached=(features.exists() and metadata.get('input_sha256')==digest.hexdigest()
                    and metadata.get('output_sha256')==sha(features)
                    and metadata.get('geometry')==[info['width'],info['height'],128,10,a.frames]
                    and metadata.get('mu_m')==1 and metadata.get('mu_s')==1 and metadata.get('motion_search')==4)
            if not cached:
                command=[sys.executable,str(Path(__file__).with_name('prepare.py')),'features','--input',source,
                         '--width',info['width'],'--height',info['height'],'--ctu',128,'--bitdepth',10,
                         '--input-bitdepth',info['input_bitdepth'],'--frames',a.frames,'--mu-m',1,'--mu-s',1,'--output',features]
                run(command,work/'prepare.log')
            jobs=2 if info['width']<=3840 else 1
            command=[sys.executable,str(Path(__file__).with_name('run_experiment.py')),
                     '--encoder',a.encoder,'--decoder',a.decoder,'--sphere',a.sphere,'--input',source,
                     '--features',features,'--width',info['width'],'--height',info['height'],
                     '--ctu',128,'--frames',a.frames,'--fps',info['fps'],'--input-bitdepth',info['input_bitdepth'],
                     '--strength',20,'--configuration','ldp','--modes',0,1,'--jobs',jobs,
                     '--discard-reconstruction','--output',work/'results']
            print('Encoding:',name,'QP workers:',jobs,flush=True)
            (work/'command.json').write_text(json.dumps(list(map(str,command)),indent=2))
            run(command,work/'batch.log')
            reports[name]=json.loads(result.read_text());save()
            source.unlink() # Generated prefix only; input originals are never removed.
            print('Complete:',name,reports[name]['comparisons'],flush=True)
        except Exception as error:
            failures[name]=str(error);save();print('Failed:',name,str(error)[-1000:],flush=True)
    save()
    if failures:raise RuntimeError('Some sequences failed; see summary.json; no complete average claimed')


if __name__=='__main__':main()
