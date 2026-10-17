import run_three_sibrc300 as batch
from pathlib import Path
for seq,file,w,h,enc,metric in batch.SEQUENCES:
 d=batch.BASE/seq;source=batch.CACHE/file
 for qp in batch.QPS:
  j=batch.make_job(d,seq,source,w,h,'test_cqp',300,cqp=qp);c=j['command']
  assert c[c.index('-s')+1]==str(w)+'x'+str(h)
  assert c[c.index('-i')+1]==str(source)
  assert '--QP='+str(qp) in c
  assert not any(x.startswith('--VTMTargetBitrate') for x in c)
 for mode in (0,3):
  j=batch.make_job(d,seq,source,w,h,'test_rc',300,1234567,mode);c=j['command']
  assert '--VTMTargetBitrate=1234567' in c
  assert '--Threads=0' in c and '--PerceptQPA=0' in c and '--WaveFrontSynchro=0' in c
  assert '-o' not in c
  if mode:
   assert '--SIBRCMode=3' in c
   assert '--SIBRCModel='+str(batch.BASE/'model') in c
   assert '--SIBRCStats='+str(batch.BASE/'stats.txt') in c
   assert str(batch.BASE/'model.I') in j['assets']
print('PASS 4K/6K/8K CQP and RC commands, native dimensions, frozen model paths, serial feedback and no encoder reconstruction')
