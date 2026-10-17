import unittest
from marginal import contrast,select_ctus,ranking
class MarginalTests(unittest.TestCase):
 def test_future_separation_and_cost(self):
  a={'wsse':[10,8,6,4],'picture_bits':[10,12,11,9]};b={'wsse':[10,10,9,5],'picture_bits':[10,10,10,9]}
  x=contrast(a,b,1);self.assertEqual(x['current_sse_reduction'],2);self.assertEqual(x['future_sse_reduction'],4);self.assertEqual(x['current_extra_bits'],2);self.assertEqual(x['total_extra_bits'],3);self.assertEqual(x['amplification'],2)
 def test_zero_and_negative_not_hidden(self):
  x=contrast({'wsse':[2,4],'picture_bits':[2,2]},{'wsse':[2,3],'picture_bits':[2,3]},1)
  self.assertEqual(x['current_sse_reduction'],-1);self.assertIsNone(x['amplification']);self.assertIsNone(x['future_benefit_per_current_bit']);self.assertEqual(x['current_extra_bits'],-1)
 def test_selection_is_deterministic_and_stratified(self):
  rows=[{'poc':'16','ctu':str(i),'wt':str(w),'history_valid':'1','bits':'100','chain':'1','beta':'1'} for i,w in enumerate([.1,.2,.3,.4,1,1,1,1,2,3,4,5])]
  rows += [dict(x,poc='15') for x in rows]
  a=select_ctus(rows,16,4);self.assertEqual(a,select_ctus(rows,16,4));self.assertEqual(len(a),12);self.assertEqual({x['stratum'] for x in a},{'low','neutral','high'})
 def test_missing_history_is_rejected(self):
  with self.assertRaises(ValueError):select_ctus([{'poc':'16','ctu':'0','wt':'.1','history_valid':'1','bits':'100','chain':'4'}],16,1)
 def test_changed_past_is_rejected(self):
  with self.assertRaises(ValueError):contrast({'wsse':[1,2],'picture_bits':[1,2]},{'wsse':[2,2],'picture_bits':[1,2]},1)
 def test_frame_metrics_and_bit_coverage(self):
  import tempfile
  import numpy as np
  from marginal_run import frame_metrics,picture_bits
  from pathlib import Path
  with tempfile.TemporaryDirectory() as temp:
   d=Path(temp);source=d/'s.yuv';rec=d/'r.yuv';log=d/'run.log'
   source.write_bytes(bytes([10])*6);rec.write_bytes(np.array([44]*4+[40]*2,dtype='<u2').tobytes())
   m=frame_metrics(source,rec,2,2,1);self.assertAlmostEqual(m['wsse'][0],4*np.cos(np.pi/4));self.assertAlmostEqual(m['wspsnr'][0],10*np.log10(255**2))
   log.write_text('POC    0 TId: 0 ( TRAIL, P-SLICE, QP 20)      128 bits [Y 40]\n');self.assertEqual(picture_bits(log,1),[128])
   with self.assertRaises(ValueError):picture_bits(log,2)
 def test_ranking(self):
  self.assertAlmostEqual(ranking([1,2,3,4],[4,3,2,1],99)['spearman'],-1);self.assertIsNone(ranking([1,1],[3,4],99)['spearman'])
if __name__=='__main__':unittest.main()
