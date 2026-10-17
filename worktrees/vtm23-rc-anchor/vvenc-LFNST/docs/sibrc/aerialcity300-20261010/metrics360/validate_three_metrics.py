import csv,json,hashlib,math
from pathlib import Path
import numpy as np
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360')
a=json.loads((D/'assessment.json').read_text())
assert len(a['points'])==8
for method in ('_anchor_','_full_'):
    points=sorted([q for q in a['points'] if method in q['name']],key=lambda q:q['target_bps'])
    assert len(points)==4
    assert all(x['actual_bps']<y['actual_bps'] for x,y in zip(points,points[1:]))
    for m in ('wspsnr','spsnr','cpppsnr'):
        assert all(x['mean_y_'+m]<y['mean_y_'+m] for x,y in zip(points,points[1:]))
for q in a['points']:
    assert q['frames']==300 and q['reconstruction_hash_matches_previous']
    assert q['spsnr_geometry_explicitly_initialized']
    assert q['annexb_minus_picture_bits']==0
    assert abs(q['actual_bps']/q['target_bps']-1)<0.02
    for m in ('psnr','wspsnr','spsnr','cpppsnr'):
        values=q['picture_y_'+m]
        assert len(values)==300 and all(math.isfinite(v) for v in values)
        assert abs(np.mean(values)-q['mean_y_'+m])<1e-12
    if q['name'].endswith('_R1'):
        assert q['cpp_revalidation_samples']==[0,150,299]
        assert q['cpp_revalidation_max_abs_difference']==0
rows=list(csv.DictReader((D/'frames.csv').open()))
assert len(rows)==2400
assert len({(r['method'],r['target_bps'],r['poc']) for r in rows})==2400
assert all(math.isfinite(v) for v in a['bd_rate_percent'].values())
print('PASS: eight streams, all 2400 frames, finite three metrics, means, reconstruction hashes, CPP spot validation and Annex-B bits')
print(json.dumps(a['bd_rate_percent']))
