"""Read immutable AerialCity experiments, check decode and compute paired rate errors."""
import argparse,csv,hashlib,json,math,re,subprocess
from pathlib import Path
import numpy as np

WIDTH,HEIGHT,FRAMES,FPS=3840,1920,16,30
RATES=[1600000,3200000,6400000,12800000]

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def pictures(log):
    text=log.read_text(encoding='utf8',errors='replace')
    pattern=r'POC\s+(\d+).*?([IPB])-SLICE, QP\s+(-?\d+)\s*\)\s+(\d+) bits.*?\[Y\s+([\d.]+) dB'
    rows=[{'poc':int(p),'slice_type':t,'qp':int(q),'bits_log':int(b),'psnr_y_log':float(y)} for p,t,q,b,y in re.findall(pattern,text)]
    return text,rows

def complete_pocs(rows):
    assert len(rows)==FRAMES and sorted(int(r['poc']) for r in rows)==list(range(FRAMES)), 'missing/duplicate POC'

def vtm_rc_pictures(text):
    pattern=r'\[RC360RC\]\[FrameBits\] POC=(\d+) targetBits=(-?\d+) actualBits=(\d+)'
    return [{'poc':int(p),'target_bits':int(t),'actual_bits':int(a)} for p,t,a in re.findall(pattern,text)]

def quality(clip,recon):
    frame_size=WIDTH*HEIGHT*3//2;weights=np.cos(((np.arange(HEIGHT)+0.5)/HEIGHT-0.5)*np.pi)[:,None]
    mse=[];weighted=[]
    with clip.open('rb') as a,recon.open('rb') as b:
        for _ in range(FRAMES):
            original=np.frombuffer(a.read(frame_size),dtype=np.uint8)[:WIDTH*HEIGHT].reshape(HEIGHT,WIDTH).astype(np.float64)
            reconstructed=np.frombuffer(b.read(frame_size*2),dtype=np.uint16)[:WIDTH*HEIGHT].reshape(HEIGHT,WIDTH).astype(np.float64)/4
            diff=(original-reconstructed)**2;mse.append(float(diff.mean()));weighted.append(float((diff*weights).sum()/(WIDTH*weights.sum())))
        assert b.read(1)==b'', 'unexpected reconstruction length'
    return {'psnr_y_mean_picture':float(np.mean([10*math.log10(255**2/m) for m in mse])),
            'psnr_y_global':10*math.log10(255**2/np.mean(mse)),
            'wspsnr_y_mean_picture':float(np.mean([10*math.log10(255**2/m) for m in weighted]))}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,default=Path('build-vtmrc/aerialcity16_ldp'))
    parser.add_argument('--input',type=Path,default=Path('I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv'))
    parser.add_argument('--decoder',type=Path,required=True);args=parser.parse_args()
    report=[]
    for name in ['vvenc','VTM']:
        for i,rate in enumerate(RATES,1):
            label=('' if name=='vvenc' else 'VTM_')+'R'+str(i);log=args.folder/(label+'.log');text,pics=pictures(log)
            if 'Total Time:' in text:complete_pocs(pics)
            if len(pics)!=FRAMES or 'Total Time:' not in text:
                print('PENDING',name,rate,len(pics),flush=True);continue
            complete_pocs(pics);assert pics[0]['slice_type']=='I'
            assert all(p['slice_type']=='P' for p in pics[1:]),'not LDP'
            stream=args.folder/(label+'.vvc');recon=args.folder/(label+'.yuv');decoded=args.folder/(label+'.decoded.yuv')
            command=[str(args.decoder),'-b',str(stream),'-o',str(decoded)]
            r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            (args.folder/(label+'.decode.log')).write_text(r.stdout,encoding='utf8');assert r.returncode==0,r.stdout[-2000:]
            assert sha(decoded)==sha(recon),'decoder/encoder reconstruction mismatch'
            log_bps=sum(p['bits_log'] for p in pics)*FPS/FRAMES
            if name=='vvenc':
                with (args.folder/(label+'.csv')).open() as f:rc=[r for r in csv.DictReader(f) if r['event']=='picture']
                complete_pocs(rc);bits=sum(int(r['bits']) for r in rc)
            else:
                rc=vtm_rc_pictures(text);complete_pocs(rc);bits=sum(r['actual_bits'] for r in rc)
            normalized=[{'poc':int(x['poc']),'target_bits':int(x['pic_target'] if name=='vvenc' else x['target_bits']),'actual_bits':int(x['bits'] if name=='vvenc' else x['actual_bits'])} for x in rc]
            actual=bits*FPS/FRAMES
            r={'engine':name,'rate_id':'R'+str(i),'target_bps':rate,'actual_rc_bps':actual,'error_pct':100*(actual/rate-1),
               'annex_b_bps':stream.stat().st_size*8*FPS/FRAMES,'poc_log_bps':log_bps,'first_picture_bits_log':pics[0]['bits_log'],
               'picture_log':pics,'rc_pictures':normalized,'stream_sha256':sha(stream),'decode_matches_reconstruction':True,**quality(args.input,recon)}
            report.append(r);print('VALIDATED',name,rate,actual,r['error_pct'],r['psnr_y_mean_picture'],flush=True)
    (args.folder/'paired_analysis.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    columns=['engine','rate_id','target_bps','actual_rc_bps','error_pct','annex_b_bps','psnr_y_mean_picture','wspsnr_y_mean_picture','decode_matches_reconstruction']
    with (args.folder/'paired_summary.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(report)
if __name__=='__main__':main()
