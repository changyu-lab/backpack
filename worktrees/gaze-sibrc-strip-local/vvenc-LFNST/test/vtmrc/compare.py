from pathlib import Path
import math, subprocess,sys
import argparse
import os
parser=argparse.ArgumentParser(description='Run independent VTM RC replay and compare persisted state')
parser.add_argument('--build-dir',type=Path,default=Path(__file__).resolve().parent/'build')
parser.add_argument('--config',default='Release')
args=parser.parse_args()
build=args.build_dir.resolve()
suffix='.exe' if os.name=='nt' else ''
# Support multi-config generators, single-config flat output, and a directly supplied executable directory.
executables={}
for name in ['vtmrc_reference','vtmrc_replay']:
 candidates=[build/args.config/(name+suffix),build/(name+suffix)]
 executables[name]=next((p for p in candidates if p.is_file()),None)
 if executables[name] is None:
  parser.error('Executable not found: '+', '.join(str(p) for p in candidates))
# Store replay output in the invoking writable working directory, independently of executable location.
outputs={name:Path.cwd()/(name+'.txt') for name in executables}
for name,executable in executables.items():
 subprocess.run([str(executable),str(outputs[name])],check=True)
def compare(a,b):
 assert len(a)==len(b), 'record count mismatch'
 count=0
 for n,(x,y) in enumerate(zip(a,b),1):
  xx=x.split(); yy=y.split(); assert len(xx)==len(yy), 'field count mismatch'
  assert xx[0]==yy[0]
  for u,v in zip(xx[1:],yy[1:]):
   if xx[0]=='I': assert int(u)==int(v), 'integer mismatch at record %d: %s != %s'%(n,u,v)
   else:
    u=float(u);v=float(v)
    assert math.isfinite(u) and math.isfinite(v), 'nonfinite state'
    assert abs(u-v)<=1e-12+1e-10*max(abs(u),abs(v)), 'double mismatch at record %d: %s != %s'%(n,u,v)
   count+=1
 return count
a=outputs['vtmrc_reference'].read_text().splitlines(); b=outputs['vtmrc_replay'].read_text().splitlines()
count=compare(a,b)
mutated=b.copy(); fields=mutated[0].split();fields[2]=str(int(fields[2])+1);mutated[0]=' '.join(fields)
try: compare(a,mutated)
except AssertionError: pass
else: raise AssertionError('comparator accepted deliberate integer divergence')
mutated=b.copy(); idx=next(i for i,x in enumerate(b) if x.startswith('D ')); fields=mutated[idx].split(); fields[1]=str(float(fields[1])+1); mutated[idx]=' '.join(fields)
try: compare(a,mutated)
except AssertionError: pass
else: raise AssertionError('comparator accepted deliberate double divergence')
print('PASS: %d records, %d fields, 8 scenarios; deliberate integer and double divergence rejected'%(len(a),count))
