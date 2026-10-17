"""Three-metric TPSM evaluation; original 360Lib adapter is mandatory."""
import sys,json,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sibrc'))
from evaluate import quality,bd_rate
from spherical_metrics import spherical_quality
KEYS=('mean_y_wspsnr','mean_y_spsnr','mean_y_cpppsnr')
def measure(source,recon,w,h,frames,bitstream,fps,exe,sphere):
 q=quality(source,recon,w,h,frames);q.update(spherical_quality(source,recon,w,h,frames,exe,sphere));q['actual_bps']=Path(bitstream).stat().st_size*8*fps/frames;return q
