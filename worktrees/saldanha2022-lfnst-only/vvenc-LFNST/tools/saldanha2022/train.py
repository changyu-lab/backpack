"""Reproducible WEKA REPTree training; standard library only."""
import argparse, collections, csv, hashlib, json, math, pathlib, random, subprocess

FEATURES = 'width height area blockRatio MTTD mipFlag ispMode currCost currDistortion currFracBits currIntraMode numNonZeroCoeffs absSumCoeffs'.split()
EXCLUDED_NAMES = 'AerialCity Balboa BranCastle2 Broadway ChairliftRide DrivingInCity DrivingInCountry Gaslamp Harbor KiteFlite Landing2 PoleVault_le SkateboardInLot Trolley'.lower().split()

def check_source(value):
    if any(name in str(value).lower() for name in ['erp14','sequences360']+EXCLUDED_NAMES):
        raise ValueError('Excluded evaluation corpus: ' + str(value))

def split_rows(rows, train_sequences, validation_sequences):
    a,b = set(train_sequences),set(validation_sequences)
    if not a or not b or a & b: raise ValueError('Train/validation sequence sets must be nonempty and disjoint')
    for s in a|b: check_source(s)
    available = {r['sequence'] for r in rows}
    if (a|b)-available: raise ValueError('Requested sequences absent: '+str((a|b)-available))
    return [r for r in rows if r['sequence'] in a], [r for r in rows if r['sequence'] in b]

def balanced_sample(rows, maximum, seed):
    if maximum < 2: raise ValueError('maximum must be >= 2')
    groups = collections.defaultdict(list)
    for r in rows:
        key = tuple(r[k] for k in ['sequence','poc','width','height','qp','label'])
        groups[key].append(r)
    rng = random.Random(seed)
    for key in sorted(groups):
        groups[key].sort(key=lambda r: json.dumps(r,sort_keys=True))
        rng.shuffle(groups[key])
    # Round-robin paired classes per sequence/frame/shape/QP, avoiding class skew.
    bases = sorted({k[:-1] for k in groups})
    out=[]
    while len(out)+2 <= maximum:
        progress=False
        for base in bases:
            if len(out)+2 > maximum: break
            if groups[base+('0',)] and groups[base+('1',)]:
                out.extend([groups[base+('0',)].pop(),groups[base+('1',)].pop()]); progress=True
        if not progress: break
    if not out: raise ValueError('No stratum contains both classes')
    return out

def predict(nodes, values, index=0):
    _,f,t,l,r,w,p0,p1=nodes[index]
    if f<0: return [p0,p1]
    if math.isnan(values[f]):
        a,b=predict(nodes,values,l),predict(nodes,values,r)
        return [w*a[i]+(1-w)*b[i] for i in range(2)]
    return predict(nodes,values,l if values[f]<t else r)

def sha(path): return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def write_arff(path, rows):
    with open(path,'w',newline='\n') as f:
        f.write('@relation lfnst\n' + ''.join('@attribute '+n+' numeric\n' for n in FEATURES) + '@attribute label {0,1}\n@data\n')
        for r in rows: f.write(','.join(str(float(r[n])) for n in FEATURES)+','+r['label']+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',nargs='+',required=True); p.add_argument('--train-sequences',nargs='+',required=True)
    p.add_argument('--validation-sequences',nargs='+',required=True); p.add_argument('--output',required=True)
    p.add_argument('--java',required=True); p.add_argument('--javac',required=True); p.add_argument('--weka',required=True)
    p.add_argument('--extra-classpath',default=''); p.add_argument('--max-rows',type=int,default=20000); p.add_argument('--seed',type=int,default=2022)
    args=p.parse_args(); rows=[]; provenance=[]
    for path in sorted(args.input):
        check_source(path); check_source(pathlib.Path(path).resolve())
        with open(path,newline='',encoding='utf-8-sig') as f:
            reader=csv.DictReader(f)
            if not set(FEATURES+['sequence','poc','qp','label']) <= set(reader.fieldnames or []): raise ValueError('Missing CSV columns')
            for r in reader:
                for v in r.values(): check_source(v)
                if r['label'] not in ('0','1'): raise ValueError('label must be 0 or 1')
                if not all(math.isfinite(float(r[n])) for n in FEATURES): raise ValueError('Nonfinite feature')
                rows.append(r)
        provenance.append(dict(path=str(pathlib.Path(path).resolve()),sha256=sha(path)))
    training,validation=split_rows(rows,args.train_sequences,args.validation_sequences)
    sampled=balanced_sample(training,args.max_rows,args.seed)
    out=pathlib.Path(args.output); out.mkdir(parents=True,exist_ok=True)
    write_arff(out/'train.arff',sampled); write_arff(out/'validation.arff',validation)
    source=pathlib.Path(__file__).with_name('TrainExport.java')
    cp=str(pathlib.Path(args.weka).resolve()) + (';'+args.extra_classpath if args.extra_classpath else '')
    subprocess.run([args.javac,'-cp',cp,'-d',str(out),str(source)],check=True)
    subprocess.run([args.java,'-cp',str(out.resolve())+';'+cp,'TrainExport',str(out/'train.arff'),str(out/'validation.arff'),str(out),str(args.seed)],check=True)
    lines=(out/'model.txt').read_text().splitlines(); nodes=[]
    for line in lines[1:]:
        v=line.split(); nodes.append(tuple(int(x) if i in (0,1,3,4) else float(x) for i,x in enumerate(v)))
    reference=list(csv.DictReader(open(out/'weka_predictions.csv',newline='')))
    max_error=0
    with open(out/'validation_predictions.csv','w',newline='') as f:
        w=csv.writer(f); w.writerow(['sequence','poc','qp','label','prediction','p0','p1'])
        for r,ref in zip(validation,reference):
            probs=predict(nodes,[float(r[n]) for n in FEATURES]); error=max(abs(probs[i]-float(ref['p'+str(i)])) for i in range(2)); max_error=max(max_error,error)
            if error>1e-12: raise AssertionError('WEKA/export mismatch')
            w.writerow([r['sequence'],r['poc'],r['qp'],r['label'],int(probs[1]>probs[0]),*probs])
    if len(reference)!=len(validation): raise AssertionError('Prediction row count differs')
    manifest=dict(model='WEKA REPTree',weka_version='3.8.6',weka_sha256=sha(args.weka),seed=args.seed,max_depth=8,pruning='WEKA default reduced-error pruning, 3 folds',features=FEATURES,class_meaning={'0':'nonzero LFNST does not improve RD cost','1':'nonzero LFNST improves RD cost'},training_sequences=sorted(args.train_sequences),validation_sequences=sorted(args.validation_sequences),excluded_corpus='I:/Sequences360 ERP14 (all Sequences360/ERP14 paths and metadata rejected)',inputs=provenance,training_rows_available=len(training),training_rows_sampled=len(sampled),validation_rows=len(validation),sampling='equal class pairs within sequence/POC/width/height/QP; deterministic round robin',node_count=len(nodes),max_prediction_error=max_error,model_sha256=sha(out/'model.txt'),train_arff_sha256=sha(out/'train.arff'),validation_arff_sha256=sha(out/'validation.arff'),tool_sha256=sha(__file__),exporter_sha256=sha(source))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__': main()
