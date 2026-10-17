"""Official 360Lib S-PSNR-NN and CPP-PSNR file adapter (ERP, YUV420)."""
import json,os,subprocess,tempfile,hashlib
from pathlib import Path
import numpy as np

DEFAULT_METRICS=('WS-PSNR','S-PSNR-NN','CPP-PSNR')
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def spherical_quality(source,recon,width,height,frames,exe=None,sphere=None):
 root=Path(__file__).resolve().parents[2]
 exe=Path(exe or os.environ.get('SIBRC_METRICS360_EXE',str(root/'build-vtmrc/metrics360-parallel/Release/metrics360.exe')))
 sphere=Path(sphere or os.environ.get('SIBRC_SPHERE_FILE','I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/cfg-360Lib/360Lib/sphere_655362.txt'))
 if not exe.is_file() or not sphere.is_file():raise FileNotFoundError('Three-metric evaluation requires the official metrics360 executable and sphere file; see tools/sibrc/metrics360/README.md, SIBRC_METRICS360_EXE and SIBRC_SPHERE_FILE')
 with tempfile.TemporaryDirectory(prefix='sibrc-metrics-',dir=str(Path(recon).resolve().parent)) as d:
  output=Path(d)/'metrics.json'
  workers=int(os.environ.get('SIBRC_METRIC_WORKERS','2'))
  cmd=[str(exe),str(source),str(recon),str(width),str(height),str(frames),str(sphere),str(output),str(workers)]
  subprocess.run(cmd,check=True)
  q=json.loads(output.read_text())
 for key in ('spsnr','cpppsnr'):
  values=q['picture_y_'+key]
  if len(values)!=frames or not np.all(np.isfinite(values)):raise ValueError('invalid official metric output')
  q['mean_y_'+key]=float(np.mean(values))
 q.update(default_metrics=list(DEFAULT_METRICS),metric_workers=min(workers,frames),spsnr_variant='S-PSNR-NN',sphere_sha256=sha(sphere),metrics360_exe_sha256=sha(exe),cpp_dimensions=[width,height],cpp_interpolation={'luma':'Lanczos3','chroma':'Lanczos2'},metric_aggregation='arithmetic mean of per-picture dB',metric_peak_10bit=1020,metric_implementation='unmodified VTM project 360Lib TSPSNRMetric/TCPPPSNRMetric; source8/reconstruction10; luma reported')
 return q
