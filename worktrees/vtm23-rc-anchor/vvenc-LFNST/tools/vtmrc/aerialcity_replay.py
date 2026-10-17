"""Replay actual first-IRAP feedback against independent original VTM and compat kernels."""
import argparse,csv,json,math,subprocess
from pathlib import Path
import numpy as np

def equal(a,b):
    assert len(a)==len(b),'record count mismatch'
    count=0
    for n,(x,y) in enumerate(zip(a,b)):
        xx=x.split();yy=y.split();assert len(xx)==len(yy) and xx[0]==yy[0],n
        for u,v in zip(xx[1:],yy[1:]):
            if xx[0]=='I':assert int(u)==int(v),(n,u,v)
            else:
                u=float(u);v=float(v);assert math.isfinite(u) and math.isfinite(v)
                assert abs(u-v)<=1e-12+1e-10*max(abs(u),abs(v)),(n,u,v)
            count+=1
    return count

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,default=Path('build-vtmrc/aerialcity16_ldp'))
    parser.add_argument('--input',type=Path,default=Path('I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv'))
    parser.add_argument('--ctu',type=int,default=128)
    parser.add_argument('--build',type=Path,default=Path('test/vtmrc/build/Release'));args=parser.parse_args()
    w,h,ctu=3840,1920,args.ctu
    # Independent unnormalized Walsh transform; only AC absolute sum matters, so coefficient order is irrelevant.
    matrix=np.ones((1,1),dtype=np.int64)
    for _ in range(3):matrix=np.block([[matrix,matrix],[matrix,-matrix]])
    y=np.fromfile(args.input,dtype=np.uint8,count=w*h).reshape(h,w).astype(np.int64)*4
    blocks=y.reshape(h//8,8,w//8,8).transpose(0,2,1,3)
    transform=matrix@blocks@matrix.T
    satd=(np.abs(transform).sum(axis=(-2,-1))-np.abs(transform[:,:,0,0])+2)>>2
    costs=(satd.reshape(h//ctu,ctu//8,w//ctu,ctu//8).sum(axis=(1,3))+2)>>2
    costs=costs.ravel();report=[]
    for i,rate in enumerate([1600000,3200000,6400000,12800000],1):
        with (args.folder/('R%d.csv'%i)).open() as f:rows=list(csv.DictReader(f))
        first=[r for r in rows if r['poc']=='0'];begin=first[0];feedback=[r for r in first if r['event']=='feedback']
        assert len(feedback)==len(costs)
        fixture=args.folder/('R%d_first_irap.fixture'%i)
        with fixture.open('w') as f:
            f.write('%d %d %d 16 %d 30\n'%(rate,w,h,ctu));f.write(' '.join(map(str,costs))+'\n')
            for r in feedback:f.write(' '.join(r[k] for k in ['bits','qp','lambda','skip_ratio','mse'])+'\n')
        expected=['I '+ ' '.join(begin[k] for k in ['bits','pic_target','qp','pic_left','seq_left']),'D '+begin['lambda']]
        for r in first:
            if r['event']=='decision':expected+=['I '+' '.join(r[k] for k in ['ctu','bits','qp','pic_left']),'D '+r['lambda']]
            elif r['event']=='feedback':expected+=['I '+r['ctu']+' '+r['pic_left'],'D '+r['alpha']+' '+r['beta']]
        outputs=[]
        for name in ['vtmrc_real_reference','vtmrc_real_compat']:
            dst=args.folder/('R%d_%s.txt'%(i,name));subprocess.run([str((args.build/(name+'.exe')).resolve()),str(fixture),str(dst)],check=True)
            outputs.append(dst.read_text().splitlines())
        fields=equal(outputs[0],outputs[1]);equal(expected,outputs[1])
        bad=outputs[1].copy();tokens=bad[0].split();tokens[2]=str(int(tokens[2])+1);bad[0]=' '.join(tokens)
        try:equal(outputs[0],bad)
        except AssertionError:pass
        else:raise AssertionError('deliberate divergence accepted')
        r={'rate':rate,'ctus':len(costs),'records':len(expected),'fields':fields,'original_vs_compat':True,'compat_vs_live_trace':True}
        report.append(r);print('PASS',json.dumps(r),flush=True)
    (args.folder/'real_replay_report.json').write_text(json.dumps({'scope':'First IRAP only; actual feedback captured from VVenC, both kernels replay it; not a full16-frame real trace replay','intra_cost_total':int(sum(costs)),'results':report},indent=2),encoding='utf8')
if __name__=='__main__':main()
