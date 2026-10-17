from pathlib import Path
import json,hashlib
VTM=Path('I:/001-IBRC-exps/VTM-23.0-paper-scc-rc')
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360')
ROOT=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
paths=list((VTM/'source/Lib/Lib360').glob('*.cpp'))+list((VTM/'source/Lib/Lib360').glob('*.h'))+[VTM/'lib/vs16/msvc-19.29/x86_64/release/CommonLib.lib',VTM/'cfg-360Lib/360Lib/sphere_655362.txt',ROOT/'tools/sibrc/metrics360/main.cpp',ROOT/'tools/sibrc/spherical_metrics.py',ROOT/'tools/sibrc/evaluate.py',D/'adapter_scalar.cpp',Path('I:/vvenc-LFNST/.worktrees/metrics360-fast/Release/metrics360.exe'),ROOT/'build-vtmrc/metrics360-parallel/Release/metrics360.exe']
assert sha(paths[-1])==sha(Path('I:/vvenc-LFNST/.worktrees/metrics360-corrected/Release/metrics360.exe'))
q={'default_metrics':['WS-PSNR','S-PSNR-NN','CPP-PSNR'],'input_bitdepth':8,'reconstruction_bitdepth':10,'reference_peak_at_10bit':1020,'geometry':'ERP, 3840x1920','cpp_dimensions':[3840,1920],'cpp_interpolation':['Lanczos3','Lanczos2'],'chroma_location':2,'sphere_samples':655362,'aggregation':'arithmetic mean of per-frame luma dB','bd_rate':'PCHIP log actual Annex-B bitrate integrated over overlapping quality range, no extrapolation','source_assets_sha256':{str(p):sha(p) for p in paths},'io_protocol':'two full temporary reconstructions and hash-verified original source cache on C, deletion after complete frame count/source and reconstruction SHA256 checks; failed four-worker I-disk pilot excluded'}
q['spsnr_geometry_metadata']='explicit original initCFSPSNR before createTable'
q['lowest_rate_revalidation']='all 300 S-PSNR values recomputed with corrected initializer; independent legacy CPP retained after exact corrected frame 0/150/299 comparison; separate executable hashes in point JSON'
(D/'protocol.json').write_text(json.dumps(q,indent=2),encoding='utf8');print('MANIFEST',len(paths),'hashed assets')
