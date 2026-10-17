import os,sys,json,csv,gzip,re,shutil,subprocess,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import beta_runtime as rt

B=rt.BASE
BETAS=[2,3,5,8,12,18,20]
NAMES=['AerialCity','DrivingInCity','DrivingInCountry','PoleVault','Balboa','Gaslamp']

def run(cmd,log,**kw):
    with Path(log).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True,**kw)

def prepare():
    src=B/'vvenc'
    if not src.exists():shutil.copytree(rt.FROZEN/'vvenc',src,ignore=shutil.ignore_patterns('.git','build','bin','lib','__pycache__'))
    path=src/'source/Lib/EncoderLib/Sibrc/Statistics.cpp'
    if not (B/'beta-source-patch.json').exists():
        text=path.read_text();original=rt.sha(path)
        text=text.replace('#include <stdexcept>','#include <stdexcept>\n#include <cstdlib>')
        anchor='static constexpr double pi=3.14159265358979323846;'
        text=text.replace(anchor,anchor+'\nstatic double experimentBeta(){static const double beta=[](){const char* p=std::getenv("SIBRC_IB_BETA");if(!p)return 5.;char* end=nullptr;double v=std::strtod(p,&end);if(*end||!std::isfinite(v)||v<=1)throw std::invalid_argument("Invalid SIBRC_IB_BETA");return v;}();return beta;}')
        assert text.count('ibWeight(r,5)')==1 and text.count('ibWeight(s.rho2,5)')==1
        text=text.replace('ibWeight(r,5)','ibWeight(r,experimentBeta())').replace('ibWeight(s.rho2,5)','ibWeight(s.rho2,experimentBeta())').replace('5*r-1','experimentBeta()*r-1')
        path.write_text(text);rt.save(B/'beta-source-patch.json',dict(before=original,after=rt.sha(path),scope='runtime IB beta only; default5'))
    if not rt.EXE.exists():
        run(['cmake','-S',str(src),'-B',str(B/'build'),'-DCMAKE_BUILD_TYPE=Release','-DVVENC_ENABLE_LINK_TIME_OPT=OFF','-DCMAKE_CXX_FLAGS=-Wno-error=misleading-indentation'],B/'configure.log')
        run(['cmake','--build',str(B/'build'),'-j','24'],B/'build.log')
    sys.path.insert(0,str(src/'tools/sibrc'))

def gate(spec):
    dest=B/'compatibility-approved.json'
    if dest.exists():assert json.loads(dest.read_text())['new_exe_sha256']==rt.sha(rt.EXE);return
    d=B/'smoke';d.mkdir(exist_ok=True);prefix=d/'beta5-C4-R1'
    old=rt.PREVIOUS/'runs'/spec['name']/'C4'/'R1'
    record=json.loads(old.with_suffix('.run.json').read_text());cmd=record['command'].copy();cmd[0]=str(rt.EXE)
    cmd=[x.replace(str(old),str(prefix)) for x in cmd]
    assert not prefix.with_suffix('.vvc').exists(),'Inspect incomplete smoke before retry'
    run(cmd,prefix.with_suffix('.log'),env=dict(os.environ,SIBRC_IB_BETA='5'))
    assert rt.sha(prefix.with_suffix('.vvc'))==rt.sha(old.with_suffix('.vvc')),'beta5 compatibility failed'
    rt.save(dest,dict(pass_test=True,bitstream_identical=True,scope='AerialCity RA32 C4 R1',new_exe_sha256=rt.sha(rt.EXE),old_exe_sha256=rt.sha(rt.FROZEN/'vvenc/bin/release-static/vvencFFapp')))

collect_lock=threading.Condition();collect_reserved=0
def collect(job):
    global collect_reserved
    beta,s,window,qp=job
    d=B/'collect'/('B'+str(beta))/s['name'];d.mkdir(parents=True,exist_ok=True)
    prefix=d/('w%d_QP%d'%(window,qp));record=prefix.with_suffix('.run.json');trace=prefix.with_suffix('.sibrc.csv');packed=Path(str(trace)+'.gz')
    if record.exists():
        r=json.loads(record.read_text());assert r['verified'] and rt.sha(packed)==r['packed_sha256'];return r
    assert not any(p.exists() for p in [prefix.with_suffix('.vvc'),trace,packed]),'Partial collect '+str(prefix)
    with collect_lock:
        while collect_reserved>=20 or rt.psutil.virtual_memory().available<2_000_000_000:collect_lock.wait(5)
        collect_reserved+=1
    try:
        cmd=rt.command(s,prefix,5000000,None);cmd[cmd.index('-c')+1]=str(B/'collection.cfg');cmd[cmd.index('-f')+1]='16'
        cmd+=['--FrameSkip='+str(window),'--SIBRCMode=2','--SIBRCStats='+str(rt.STATS),'--SIBRCTrace='+str(trace),'--SIBRCFeature=4','--SIBRCCalibrationQP='+str(qp)]
        print('COLLECT START',beta,s['name'],window,qp,flush=True)
        run(cmd,prefix.with_suffix('.log'),env=dict(os.environ,SIBRC_IB_BETA=str(beta)))
        text=prefix.with_suffix('.log').read_text();pocs=sorted(set(map(int,re.findall(r'POC\s+(\d+)\s',text))));assert pocs==list(range(16))
        bitsha=rt.sha(prefix.with_suffix('.vvc'));rawsha=rt.sha(trace)
        with trace.open('rb') as a,gzip.open(packed,'wb') as b:shutil.copyfileobj(a,b)
        assert gzip.open(packed,'rb').read()==trace.read_bytes()
        r=dict(beta=beta,sequence=s['name'],window=window,qp=qp,prefix=str(prefix),command=cmd,verified=True,bitstream_sha256=bitsha,raw_trace_sha256=rawsha,packed_sha256=rt.sha(packed))
        rt.save(record,r)
        # Disposable training bitstream and duplicate trace; hashes and lossless compressed trace retained.
        prefix.with_suffix('.vvc').unlink();trace.unlink()
        print('COLLECT PASS',beta,s['name'],window,qp,flush=True);return r
    finally:
        with collect_lock:collect_reserved-=1;collect_lock.notify_all()

def calibrate(records):
    import calibrate_m4 as cal
    tables={};labels={}
    for beta in BETAS:
        rows=[]
        for r in records:
            if r['beta']!=beta:continue
            key=(r['sequence'],r['window'],r['qp'])
            if key in labels:assert labels[key]==r['bitstream_sha256'],'Collection differs across beta'
            labels[key]=r['bitstream_sha256']
            with gzip.open(r['prefix']+'.sibrc.csv.gz','rt') as f:
                for row in csv.DictReader(f):
                    row.update(source_sequence=r['sequence'],window_start=r['window'],requested_qp=r['qp']);rows.append(row)
        matched,reasons=cal.matched_rows(rows);tables[beta]={cal.row_key(r):r for r in matched}
        rt.save(B/('B%d-row-filter.json'%beta),dict(input_rows=len(rows),matched_rows=len(matched),filter_reasons=reasons))
    keys=set.intersection(*(set(v) for v in tables.values()));assert keys
    common_hash=cal.canonical_hash(sorted(keys));split=None
    for beta in BETAS:
        rows=[tables[beta][k] for k in sorted(keys)];train,test=cal.split_rows(rows,split)
        current={'all_groups':sorted({cal.group_key(r) for r in rows}),'holdout_groups':sorted({cal.group_key(r) for r in test})}
        if split is None:split=current
        assert current==split
        d=B/'models'/('B'+str(beta));d.mkdir(parents=True,exist_ok=True)
        for kind in ['I','P']:
            tr=[r for r in train if r['kind']==kind];te=[r for r in test if r['kind']==kind]
            model=cal.fit_model(tr,te,'C4',1e-6);cal.write_model(d/('model.'+kind),kind,'C4',model)
            rt.save(d/('model.'+kind+'.json'),dict(beta=beta,matched_key_sha256=common_hash,train_rows=len(tr),holdout_rows=len(te),**model))
        print('FIT PASS',beta,len(rows),flush=True)
    rt.save(B/'calibration-protocol.json',dict(betas=BETAS,common_samples=len(keys),common_key_sha256=common_hash,split=split,ridge=1e-6,stats_sha256=rt.sha(rt.STATS),bitstream_equal_across_beta=True,development_sources=['DrivingInCity','DrivingInCountry'],training_window=0,holdout_window=16,frames_per_window=16,scope='common remote32 development protocol; not original four-window calibration; beta5 refit'))

def main():
    prepare()
    specs=json.loads((rt.PREVIOUS/'sources.json').read_text());selected=[s for s in specs if s['name'] in NAMES];assert len(selected)==6
    for s in specs:s['targets']=json.loads((rt.PREVIOUS/(s['name']+'-targets.json')).read_text())['targets']
    rt.save(B/'sources.json',selected);gate(next(s for s in specs if s['name']=='AerialCity'))
    jobs=[(beta,s,w,qp) for beta in BETAS for s in specs if s['name'] in ['DrivingInCity','DrivingInCountry'] for w in [0,16] for qp in range(17,53,5)]
    assert len(jobs)==224
    with ThreadPoolExecutor(max_workers=24) as pool:records=list(pool.map(collect,jobs))
    calibrate(records)
    rt.save(B/'frozen-assets.json',{str(p):rt.sha(p) for p in [rt.EXE,rt.METRIC,rt.DEC,rt.CFG,rt.STATS]+list((B/'models').glob('*/model.[IP]'))})
    runs=[(s,'B'+str(beta),i,rate,[-2,2,beta]) for s in selected for beta in BETAS for i,rate in enumerate(s['targets'],1)]
    with ThreadPoolExecutor(max_workers=28) as pool:encoded=list(pool.map(rt.encode,runs))
    summary={}
    for s in selected:
        anchor=[]
        for i in range(1,5):
            p=rt.PREVIOUS/'runs'/s['name']/'anchor'/('R'+str(i));r=json.loads(p.with_suffix('.run.json').read_text());assert all(rt.sha(p)==h for p,h in r['outputs_sha256'].items());anchor.append(json.loads(p.with_suffix('.quality.json').read_text()))
        summary[s['name']]={}
        for beta in BETAS:
            qs=[rt.quality(r) for r in encoded if r['sequence']==s['name'] and r['label']=='B'+str(beta)]
            assert len(qs)==4;summary[s['name']][str(beta)]=rt.compare(anchor,qs);rt.save(B/'summary-progress.json',summary)
    rt.save(B/'summary.json',dict(bd=summary,betas=BETAS,protocol='RA32 six native sequences, same-window target/Anchor reuse; all beta independently calibrated common samples including beta5; truncated GOP32; two calibration sequences are development'))
    print('COMPLETE BETA SWEEP',flush=True)

if __name__=='__main__':main()
