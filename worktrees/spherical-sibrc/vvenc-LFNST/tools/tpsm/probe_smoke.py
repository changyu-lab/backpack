"""Integration regression for isolated CTU probes; synthetic data is not performance evidence."""
import argparse,json,subprocess,csv,math
from pathlib import Path
from smoke import sha,ROOT

def main():
 p=argparse.ArgumentParser();p.add_argument('--encoder',required=True,type=Path);p.add_argument('--decoder',required=True,type=Path);p.add_argument('--fixture-runs',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();a.output.mkdir(exist_ok=False,parents=True)
 original=json.loads(a.fixture_runs.read_text());base=next(x for x in original if x['name']=='repaired')['command'];cmd=base.copy();cmd[0]=str(a.encoder)
 decisions=a.output/'baseline.decisions';records=[]
 def encode(name,extra):
  c=cmd.copy();stem=a.output/name;c[c.index('-b')+1]=str(stem)+'.vvc';c[c.index('-o')+1]=str(stem)+'.yuv'
  c=[('--SIBRCTrace='+str(stem)+'.sibrc.csv') if x.startswith('--SIBRCTrace=') else ('--VTMRCTrace='+str(stem)+'.vtm.csv') if x.startswith('--VTMRCTrace=') else x for x in c]
  c+=['--TPSMMode=2','--TPSMStrength=0','--TPSMTrace='+str(stem)+'.tpsm.csv']+extra
  with open(str(stem)+'.log','w') as f:subprocess.run(c,stdout=f,stderr=subprocess.STDOUT,check=True)
  dc=[str(a.decoder),'-b',str(stem)+'.vvc','-o',str(stem)+'.decoded.yuv','--OutputBitDepth=10']
  with open(str(stem)+'.decode.log','w') as f:subprocess.run(dc,stdout=f,stderr=subprocess.STDOUT,check=True)
  assert sha(str(stem)+'.yuv')==sha(str(stem)+'.decoded.yuv')
  records.append({'name':name,'command':c,'decoder_command':dc,'bitstream_sha256':sha(str(stem)+'.vvc'),'reconstruction_sha256':sha(str(stem)+'.yuv')});return stem
 b=encode('record',['--VTMDecisionRecord='+str(decisions)])
 assert records[-1]['bitstream_sha256']==next(x for x in original if x['name']=='repaired')['bitstream_sha256'],'record/observe changes baseline'
 z=encode('replay',['--VTMDecisionReplay='+str(decisions)])
 assert sha(str(z)+'.vvc')==sha(str(b)+'.vvc'),'zero probe bitstream identity'
 def rows(stem):
  with open(str(stem)+'.sibrc.csv') as f:return list(csv.DictReader(f))
 def pictures(stem):
  with open(str(stem)+'.vtm.csv') as f:return [(x['poc'],x['qp'],x['lambda']) for x in csv.DictReader(f) if x['event']=='begin']
 original_rows=rows(b)
 assert len(original_rows)==64
 assert pictures(b)==pictures(z),'replay picture init differs'

 for offset in [-1,1]:
  x=encode('probe_'+str(offset),['--VTMDecisionReplay='+str(decisions),'--VTMProbePOC=3','--VTMProbeCTU=0','--VTMProbeOffset='+str(offset)])
  changed=[]
  modified=rows(x);assert len(modified)==len(original_rows),'missing CTU rows'
  assert pictures(b)==pictures(x),'probe changed picture initialization'
  for before,after in zip(original_rows,modified):
   assert (before['poc'],before['ctu'])==(after['poc'],after['ctu']),'CTU key mismatch'
   is_probe=(int(after['poc']),int(after['ctu']))==(3,0)
   assert int(after['qp'])==int(before['qp'])+(offset if is_probe else 0)
   expected=float(before['lambda'])*(2**(offset/3) if is_probe else 1)
   assert math.isclose(float(after['lambda']),expected,rel_tol=1e-14),'incorrect lambda perturbation'

   if before['qp']!=after['qp'] or before['lambda']!=after['lambda']:changed.append((int(after['poc']),int(after['ctu'])))
  assert changed==[(3,0)],changed
  size=512*256*3
  with open(str(b)+'.yuv','rb') as f:prefix=f.read(size*3)
  with open(str(x)+'.yuv','rb') as f:assert f.read(size*3)==prefix,'frames before probe changed'
  assert sha(str(x)+'.vvc')!=sha(str(b)+'.vvc'),'probe had no effect'
 (a.output/'summary.json').write_text(json.dumps({'encoder_sha256':sha(a.encoder),'decision_sha256':sha(decisions),'checks':['all4 independent decodes','record and zero replay identity','exactly1 scheduled CTU action changes','all frames before probe identical'],'runs':records},indent=2));print('probe smoke passed4 encodes',flush=True)
if __name__=='__main__':main()
