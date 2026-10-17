import subprocess,json,time
from pathlib import Path
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360')
base=['C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-vtmrc/metric-source-cache/AerialCity_3840x1920_30fps_8bit_420_erp.yuv','C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-vtmrc/sibrc300-decoder-temp/rc300_anchor_R2.yuv','3840','1920','3','I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/cfg-360Lib/360Lib/sphere_655362.txt']
times={}
for exe,name,extra in [('I:/vvenc-LFNST/.worktrees/metrics360-corrected/Release/metrics360.exe','corrected_actual3_parallel',['3']),('I:/vvenc-LFNST/.worktrees/metrics360-corrected/Release/metrics360.exe','corrected_actual3_scalar',[])]:
 start=time.perf_counter();subprocess.run([exe,*base,str(D/(name+'.json')),*extra],check=True);times[name]=time.perf_counter()-start
assert json.loads((D/'corrected_actual3_scalar.json').read_text())==json.loads((D/'corrected_actual3_parallel.json').read_text())
(D/'corrected_parallel_equivalence_actual3.json').write_text(json.dumps({'exact_equal':True,'frames':3,'width':3840,'height':1920,'times':times},indent=2));print('PASS actual ERP first three frames: scalar and three-worker outputs exactly equal',times)
