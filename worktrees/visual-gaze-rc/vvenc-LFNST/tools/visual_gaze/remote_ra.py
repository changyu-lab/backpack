"""Pinned 14-sequence RA32/17-frame experiment using verified local features."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import shutil
import sys
from batch_strip import sequence_info,prefix_hash,aggregate
from prepare import sha
from run_experiment import run


def validate_input(info,inputs):
    folder=inputs/info['name'];features=folder/'features.txt'
    meta=json.loads((folder/'features.txt.json').read_text())
    provenance=json.loads((folder/'input.json').read_text())
    expected=[info['width'],info['height'],128,10,info['frames']]
    if meta.get('geometry')!=expected or meta.get('mu_m')!=1 or meta.get('mu_s')!=1 or meta.get('motion_search')!=4:
        raise ValueError('feature convention mismatch: '+info['name'])
    if meta['output_sha256']!=sha(features):raise ValueError('feature hash mismatch: '+info['name'])
    digest=prefix_hash(Path(info['input']),info['prefix_bytes'])
    if digest!=meta['input_sha256'] or digest!=provenance['source_prefix_sha256']:
        raise ValueError('remote input differs from locally analyzed prefix: '+info['name'])
    return dict(info,features_sha256=sha(features),source_prefix_sha256=digest)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('sequences','inputs','encoder','decoder','sphere','output','scratch-root'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--sequence-workers',type=int,choices=range(1,5),default=3)
    p.add_argument('--qp-jobs',type=int,choices=range(1,5),default=2)
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);a.scratch_root.mkdir(parents=True,exist_ok=True)
    infos=[sequence_info(f,17) for f in sorted(a.sequences.glob('*.yuv'))]
    if len(infos)!=14:p.error('exactly fourteen sources required')
    checked=[]
    with ThreadPoolExecutor(max_workers=a.sequence_workers) as pool:
        futures=[pool.submit(validate_input,info,a.inputs) for info in infos]
        for future in as_completed(futures):
            info=future.result();checked.append(info);print('Input SHA verified:',info['name'],flush=True)
    checked.sort(key=lambda i:i['name'])
    slots=a.sequence_workers*a.qp_jobs
    largest=max(i['width']*i['height']*3*17 for i in infos)
    required=largest*2*slots+1024**3
    if shutil.disk_usage(a.scratch_root).free<required:
        raise ValueError('insufficient scratch capacity for concurrent reconstruction/decoder outputs')
    deps=[a.encoder,a.decoder,a.sphere,Path('cfg/visual_gaze_ldp16.cfg')]+[
        Path(__file__).with_name(n) for n in ('prepare.py','evaluate.py','run_experiment.py','batch_strip.py','remote_ra.py')]
    manifest=dict(configuration='ra32',frames=17,modes=[0,1],qps=[22,27,32,37],f=20,
                  mu_m=1,mu_s=1,inputs=checked,sequence_workers=a.sequence_workers,qp_jobs=a.qp_jobs,
                  dependencies={str(f.absolute()):sha(f) for f in deps},scratch_required_bytes=required,
                  cpu_count=os.cpu_count(),timing_comparable=False)
    path=a.output/'manifest.json'
    if path.exists() and json.loads(path.read_text())!=manifest:raise ValueError('experiment identity changed; use fresh output')
    path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if a.dry_run:print('Preflight passed: fourteen input prefixes and features verified',flush=True);return
    reports={};failures={};expected=[i['name'] for i in checked]
    def save():
        data=aggregate(expected,reports);data.update(failures=failures,configuration='ra32',frames=17,
            modes=[0,1],timing_comparable=False)
        (a.output/'summary.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    def worker(info):
        name=info['name'];out=a.output/name;out.mkdir(exist_ok=True)
        result=out/'report.json'
        if result.exists():
            r=json.loads(result.read_text())
            if r['configuration']!='ra' or r['frames']!=17 or r['modes']!=[0,1] or len(r['results'])!=8:
                raise ValueError('incompatible completed sequence report')
            if r['features_sha256']!=info['features_sha256'] or r['encoder_sha256']!=sha(a.encoder):
                raise ValueError('completed sequence inputs changed')
            for row in r['results']:
                prefix=out/f"mode{row['mode']}_qp{row['qp']}"
                if sha(prefix.with_suffix('.vvc'))!=row['stream_sha256'] or sha(prefix.with_suffix('.rc.csv'))!=row['trace_sha256']:
                    raise ValueError('completed stream/trace changed')
            return r
        command=[sys.executable,str(Path(__file__).with_name('run_experiment.py')),'--encoder',a.encoder,
            '--decoder',a.decoder,'--sphere',a.sphere,'--input',info['input'],'--features',a.inputs/name/'features.txt',
            '--width',info['width'],'--height',info['height'],'--frames',17,'--ctu',128,'--fps',info['fps'],
            '--input-bitdepth',info['input_bitdepth'],'--configuration','ra','--modes',0,1,'--strength',20,
            '--jobs',a.qp_jobs,'--discard-reconstruction','--scratch-root',a.scratch_root,'--output',out]
        (out/'command.json').write_text(json.dumps(list(map(str,command)),indent=2))
        print('Encoding:',name,flush=True);run(command,out/'batch.log')
        return json.loads(result.read_text())
    save()
    with ThreadPoolExecutor(max_workers=a.sequence_workers) as pool:
        futures={pool.submit(worker,info):info['name'] for info in checked}
        for future in as_completed(futures):
            name=futures[future]
            try:
                reports[name]=future.result();print('Complete:',name,reports[name]['comparisons'],flush=True)
            except Exception as error:
                failures[name]=str(error);print('Failed:',name,str(error)[-2000:],flush=True)
            save()
    if failures:raise RuntimeError('Some sequences failed; full average is unavailable')


if __name__=='__main__':main()
