"""Run an explicitly selected LD sequence/rate set, preserving configs and identities.
No default sequence sweep. Native runs require explicit --method native.
"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
import psutil


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()


def parse_log(path):
    text=Path(path).read_text(encoding='utf8',errors='replace')
    lines=text.splitlines()
    header=None; values=None
    for line in lines:
        if 'Total Frames' in line and 'Bitrate' in line:
            header=['frames']+line.split('|',1)[1].split()
        elif header and re.match(r'^\s*\d+\s+a\s+',line):
            parts=line.split(); values=[parts[0]]+parts[2:]; break
    if values is None: raise ValueError('missing completed aggregate summary')
    d=dict(zip(header,map(float,values)))
    times=re.findall(r'Total Time:\s*([\d.]+) sec\. \[user\]\s*([\d.]+) sec\. \[elapsed\]',text)
    if not times: raise ValueError('missing completion timing')
    result={'frames':int(d['frames']),'actual_bps':d['Bitrate']*1000,'Y_PSNR':d['Y-PSNR'],
            'encoder_cpu_seconds':float(times[-1][0]),'encoder_wall_seconds':float(times[-1][1])}
    for key,col in [('Y_WS','Y-WSPSNR'),('Y_E2E_S','Y-E2ESPSNR_NN'),('Y_CF_CPP','Y-CFCPPPSNR')]:
        result[key]=d.get(col)
    pocs=[int(x) for x in re.findall(r'^POC\s+(\d+)\s+LId:',text,re.M)]
    if sorted(pocs)!=list(range(result['frames'])): raise ValueError('POC count/order invalid')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--encoder',type=Path,required=True); p.add_argument('--input',type=Path,required=True)
    p.add_argument('--sequence',required=True); p.add_argument('--config',type=Path,action='append',required=True)
    p.add_argument('--features',type=Path); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rates',type=int,nargs='+',required=True); p.add_argument('--frames',type=int,default=16)
    p.add_argument('--method',choices=['zhao','native'],default='zhao'); p.add_argument('--sphere',type=Path)
    p.add_argument('--diagnostics',action='store_true'); p.add_argument('--recon',action='store_true')
    p.add_argument('--reserve-gib',type=float,default=3); p.add_argument('--expected-rss-gib',type=float,default=12)
    p.add_argument('--shared-slot-confirmed',action='store_true'); p.add_argument('--prepare-only',action='store_true')
    a=p.parse_args()
    if a.method=='zhao' and not a.features: p.error('Zhao features required')
    if a.frames<1 or any(r<=0 for r in a.rates): p.error('positive frames/rates required')
    a.output.mkdir(parents=True,exist_ok=True)
    common=[str(a.encoder.resolve())]
    for config in a.config: common+=['-c',str(config.resolve())]
    common += ['--InputFile='+str(a.input.resolve()),'--FramesToBeEncoded='+str(a.frames),'--FrameSkip=0',
        '--RateControl=1','--LCULevelRateControl=1','--RC360FbTc=0','--RC360CtuExp=0',
        '--ZhaoRC='+str(int(a.method=='zhao'))]
    if a.features: common+=['--ZhaoRCFeatureDir='+str(a.features.resolve())]
    if a.sphere: common+=['--SphFile='+str(a.sphere.resolve())]
    jobs=[]
    for rate in a.rates:
        folder=a.output/str(rate)
        cmd=common+['--TargetBitrate='+str(rate),'--BitstreamFile='+str((folder/'stream.bin').resolve()),
                   '--ReconFile='+str((folder/'recon.yuv').resolve()) if a.recon else '--ReconFile=']
        if a.diagnostics: cmd+=['--ZhaoRCDiagnostics='+str((folder/'ctu.csv').resolve())]
        jobs.append({'target_bps':rate,'command':cmd,'folder':str(folder.resolve())})
    manifest={'sequence':a.sequence,'method':a.method,'frames':a.frames,'jobs':jobs,
              'encoder_sha256':sha(a.encoder),'configs':{str(x.resolve()):sha(x) for x in a.config},
              'input_path':str(a.input.resolve()),'input_size':a.input.stat().st_size,
              'features_manifest':json.loads((a.features/'manifest.json').read_text()) if a.features else None}
    manifest_path=a.output/'run_manifest.json'
    if any(Path(job['folder']).exists() for job in jobs):
        raise RuntimeError('refusing existing result folders; use a new output directory')
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise RuntimeError('refusing to overwrite different run provenance')
    else:
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf8')
    if a.prepare_only: return
    if not a.shared_slot_confirmed: p.error('measured shared resource admission required: --shared-slot-confirmed')
    for job in jobs:
        folder=Path(job['folder'])
        if folder.exists(): raise RuntimeError('refusing overwrite: '+str(folder))
        if psutil.virtual_memory().available < (a.reserve_gib+a.expected_rss_gib)*1024**3:
            raise RuntimeError('insufficient available RAM for this admission')
        folder.mkdir(); (folder/'command.json').write_text(json.dumps(job['command'],indent=2))
        start=time.perf_counter(); peak=0; cpu=0
        with (folder/'encoder.log').open('w',encoding='utf8') as log:
            child=subprocess.Popen(job['command'],stdout=log,stderr=subprocess.STDOUT)
            (folder/'pid.json').write_text(json.dumps({'pid':child.pid,'started_unix':time.time()}))
            proc=psutil.Process(child.pid)
            while child.poll() is None:
                try:
                    peak=max(peak,proc.memory_info().rss); ct=proc.cpu_times(); cpu=ct.user+ct.system
                except psutil.NoSuchProcess: pass
                time.sleep(1)
            code=child.returncode
        receipt={'returncode':code,'wall_seconds':time.perf_counter()-start,'sampled_cpu_seconds':cpu,'peak_rss_bytes':peak}
        if code==0:
            receipt.update(parse_log(folder/'encoder.log'))
            if receipt['frames']!=a.frames: raise RuntimeError('frame count mismatch')
            receipt['target_bps']=job['target_bps']; receipt['rate_error_pct']=100*(receipt['actual_bps']/job['target_bps']-1)
            receipt['abs_rate_error_pct']=abs(receipt['rate_error_pct']); receipt['bitstream_sha256']=sha(folder/'stream.bin')
        (folder/'receipt.json').write_text(json.dumps(receipt,indent=2))
        if code: raise RuntimeError('encoder failed; see '+str(folder/'encoder.log'))
        print(json.dumps(receipt),flush=True)

if __name__=='__main__': main()


