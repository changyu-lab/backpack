import hashlib,json
from pathlib import Path
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()
p=Path('docs/visual-gaze-rc');p.mkdir(exist_ok=True)
report=Path('build-gaze/aerialcity-port-decoded/report.json')
(p/'aerialcity-smoke-report.json').write_bytes(report.read_bytes())
manifest=json.loads(Path('build-gaze/official-gaze/manifest.json').read_text())
arrays=[]
for segment in manifest['segments']:
    a=Path('build-gaze/official-gaze')/segment['array']
    b=Path('build-gaze/official-gaze-repeat')/segment['array']
    arrays.append(dict(source_poc=segment['source_poc'],sha256=sha(a),repeat_sha256=sha(b),identical=sha(a)==sha(b)))
native=json.loads(Path('build-gaze/native-metric-check.json').read_text())['picture_y_spsnr']
metric=json.loads(Path('build-gaze/aerialcity-port-decoded/mode3_qp37.metrics.json').read_text())
ours=[f['s_psnr_nn'] for f in metric['frames']]
delta=max(abs(a-b) for a,b in zip(native,ours))
assert len(native)==len(ours)==19 and delta<1e-10,(delta,native[0],ours[0])
full=Path('build-gaze/official-gaze')
assert sha(full/'full4k.rec.yuv')==sha(full/'full4k.decoded.yuv')
evidence=dict(source='AerialCity_3840x1920_30fps_8bit_420_erp.yuv',manifest=manifest,
    inference_gop=16,inference_repeat_arrays=arrays,
    full4k=dict(width=3840,height=1920,frames=1,ctu=128,target_bps=6400000,
        command=json.loads((full/'full4k.command.json').read_text()),
        hashes={name:sha(full/name) for name in ['full4k.vvc','full4k.rec.yuv','full4k.decoded.yuv','full4k.features.txt','full4k.gaze.txt','full4k.rc.csv','full4k.gaze.csv']}),
    s_psnr_nn_crosscheck=dict(reference='local 360Lib13.6 native metrics360',frames=19,max_absolute_db_difference=delta,python=ours,native=native),
    verification=dict(ctest='40/40 passed',python='9 tests passed; six encoder cases',
        kernel='extraction unchanged, replay 4200 records/13192 fields across eight scenarios',
        decoded_smoke='16/16 decoder output equals encoder reconstruction',
        scope='software port and smoke evidence; published RD gains not reproduced'))
(p/'provenance.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print('native S-PSNR maximum delta',delta)
print(json.dumps(json.loads(report.read_text())['comparisons'],indent=2))
