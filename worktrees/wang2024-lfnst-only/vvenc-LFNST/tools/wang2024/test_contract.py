import unittest,os
from tools.wang2024.contract import jobs, frames, command, runtime_env, timing_matches, completion_matches
class Contract(unittest.TestCase):
 def test_frozen_matrix(self):
  seqs=['s%d'%i for i in range(14)]
  j=jobs(seqs)
  self.assertEqual(len(j),126)
  self.assertEqual(len(j)*4*2,1008)
  self.assertEqual({p for p,c,s in j},{'fast','medium','slow'})
  self.assertEqual({c for p,c,s in j},{'AI','RA','LDP'})
  self.assertEqual([frames(c) for c in ['AI','RA','LDP']],[1,16,16])
 def test_matched_options(self):
  seq=dict(name='s',path='/x.yuv',width=3840,height=1920,fps=30,bitdepth=8)
  for config in ['AI','RA','LDP']:
   cmd=command('/enc',seq,22,'slow',config,'/b','/r','/ldp.cfg')
   def value(k):return cmd[cmd.index(k)+1]
   self.assertEqual(value('--threads'),'1')
   self.assertEqual(value('--additional'),'LFNST=1 LardLfnstSkip=0')
   self.assertEqual(value('-f'),str(frames(config)))
   self.assertEqual(value('--qpa'),'0')
   self.assertEqual(value('--GOPSize'),{'AI':'1','RA':'16','LDP':'8'}[config])
   if config=='LDP':self.assertEqual(value('-c'),'/ldp.cfg')
 def test_environment(self):
  a=runtime_env('anchor',{'WANG_LFNST_MODE':'on','LFNST_TRANSFORM_AUDIT':'bad','LFNST_STAGE_WRONG_AUDIT':'bad','WANG_LFNST_AUDIT':'bad'})
  b=runtime_env('proposed',{})
  self.assertEqual(a['WANG_LFNST_MODE'],'off')
  self.assertEqual(b['WANG_LFNST_MODE'],'on')
  self.assertNotIn('WANG_LFNST_AUDIT',a)
  self.assertNotIn('LFNST_TRANSFORM_AUDIT',a)
  self.assertNotIn('LFNST_STAGE_WRONG_AUDIT',a)
 def test_stale_timing_is_rejected(self):
  expected=dict(sha256='new_bits',encoder_sha256='new_encoder',command=['enc','-q','22'],wang_mode='on',run_identity='run1')
  self.assertTrue(timing_matches(dict(expected,transform_ns=10),expected))
  for key in expected:
   stale=dict(expected,transform_ns=10);stale[key]='old'
   self.assertFalse(timing_matches(stale,expected),key)
  self.assertFalse(timing_matches(dict(expected,transform_ns=0),expected))
 def test_completion_identity(self):
  self.assertTrue(completion_matches({'status':'COMPLETE','run_identity':'a'},'a'))
  self.assertFalse(completion_matches({'status':'COMPLETE'},'a'))
  self.assertFalse(completion_matches({'status':'COMPLETE','run_identity':'old'},'a'))
if __name__=='__main__':unittest.main()
