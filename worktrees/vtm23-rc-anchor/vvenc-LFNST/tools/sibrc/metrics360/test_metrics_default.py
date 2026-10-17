"""Run with the configured official metrics360 tool; no full sequence needed."""
import json,math,sys,tempfile,subprocess,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/sibrc'))
from evaluate import quality
from spherical_metrics import spherical_quality
temporary=ROOT/'build-vtmrc/metric-tests';temporary.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=str(temporary)) as d:
 p=Path(d);src=np.full(64*32*3//2,100,dtype=np.uint8);src.tofile(p/'src.yuv')
 for error in (0,4):
  np.full(len(src),400+error,dtype='<u2').tofile(p/'rec.yuv')
  q=quality(p/'src.yuv',p/'rec.yuv',64,32,1)
  assert q['default_metrics']==['WS-PSNR','S-PSNR-NN','CPP-PSNR']
  expected=999.99 if error==0 else 10*math.log10(1020**2/error**2)
  for key in ('spsnr','cpppsnr'):assert abs(q['picture_y_'+key][0]-expected)<1e-9
  if error:assert abs(q['mean_y_wspsnr']-expected)<1e-9
 np.tile(src,3).tofile(p/'src.yuv')
 np.concatenate([np.full(len(src),400+error,dtype='<u2') for error in (4,8,16)]).tofile(p/'rec.yuv')
 previous=os.environ.get('SIBRC_METRIC_WORKERS');os.environ['SIBRC_METRIC_WORKERS']='3'
 q=quality(p/'src.yuv',p/'rec.yuv',64,32,3)
 if previous is None:os.environ.pop('SIBRC_METRIC_WORKERS')
 else:os.environ['SIBRC_METRIC_WORKERS']=previous
 expected=[10*math.log10(1020**2/error**2) for error in (4,8,16)]
 for key in ('spsnr','cpppsnr'):assert np.allclose(q['picture_y_'+key],expected,rtol=0,atol=1e-9)
 try:spherical_quality(p/'src.yuv',p/'rec.yuv',64,32,1,exe=p/'missing.exe')
 except FileNotFoundError:pass
 else:raise AssertionError('missing metrics must not silently fall back to WS only')
 metric_exe=os.environ.get('SIBRC_METRICS360_EXE',str(ROOT/'build-vtmrc/metrics360-parallel/Release/metrics360.exe'))
 metric_sphere=os.environ.get('SIBRC_SPHERE_FILE','I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/cfg-360Lib/360Lib/sphere_655362.txt')
 result=subprocess.run([metric_exe,str(p/'src.yuv'),str(p/'rec.yuv'),'64','32','1',metric_sphere,str(p/'absent'/'output.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 assert result.returncode!=0,'unwritable output must fail rather than silently lose metrics'
 (p/'rec.yuv').write_bytes(b'')
 try:quality(p/'src.yuv',p/'rec.yuv',64,32,1)
 except ValueError:pass
 else:raise AssertionError('truncated reconstruction accepted')
print('PASS: default three metrics, bit-depth offset, identity, parallel frame order, missing-tool, unwritable-output and truncation checks')
