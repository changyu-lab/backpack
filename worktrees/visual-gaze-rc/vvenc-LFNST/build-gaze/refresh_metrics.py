import json, subprocess, sys
from pathlib import Path
sys.path.insert(0,'tools/visual_gaze')
from evaluate import bd_rate
p=Path('build-gaze/aerialcity-port-decoded')
report=json.loads((p/'report.json').read_text())
for r in report['results']:
    prefix=p/f"mode{r['mode']}_qp{r['qp']}"
    command=[sys.executable,'tools/visual_gaze/evaluate.py','--input','build-gaze/official-gaze/smoke.yuv',
             '--reconstruction',str(prefix.with_suffix('.yuv')),'--trace',str(prefix.with_suffix('.rc.csv')),
             '--bitstream',str(prefix.with_suffix('.vvc')),'--width','256','--height','128','--frames','19',
             '--target-bps',str(r['target_bps']),'--fps','30','--delay','16',
             '--sphere','I:/001-IBRC-exps/VTM-23.0/cfg-360Lib/360Lib/sphere_655362.txt',
             '--output',str(prefix.with_suffix('.metrics.json'))]
    subprocess.run(command,check=True)
    m=json.loads(prefix.with_suffix('.metrics.json').read_text())
    r.update(actual_bps=m['actual_bps'],nal_bps=m['nal_bps'],bitrate_error_percent=m['bitrate_error_percent'],quality=m['quality_mean_db'])
anchor=[r for r in report['results'] if r['mode']==0]
for comparison in report['comparisons']:
    rows=[r for r in report['results'] if r['mode']==comparison['mode']]
    for metric in anchor[0]['quality']:
        try:
            comparison[metric+'_bd_rate_percent']=bd_rate([r['actual_bps'] for r in anchor],[r['quality'][metric] for r in anchor],
                [r['actual_bps'] for r in rows],[r['quality'][metric] for r in rows])
        except ValueError as e:
            comparison[metric+'_bd_rate_unavailable']=str(e)
report['rate_basis']='Annex B file bytes for both targets and actual_bps; nal_bps separately retained'
(p/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report['comparisons'],indent=2))
