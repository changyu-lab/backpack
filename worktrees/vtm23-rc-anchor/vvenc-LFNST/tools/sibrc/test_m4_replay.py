import unittest, subprocess, tempfile, csv
from pathlib import Path
class ReplayContract(unittest.TestCase):
 def test_real_fitted_model_replay_detects_difference(self):
  root=Path(__file__).parents[2]; exe=root/'build-vtmrc/sibrc-tests/Release/sibrc_m4_replay.exe'; self.assertTrue(exe.exists(),'fitted model replay missing')
  with tempfile.TemporaryDirectory() as temporary:
   out=Path(temporary); paths=[]
   for selector in [2,3]:
    for kind in ['I','P']:
     path=out/(str(selector)+kind); paths.append(str(path)); path.write_text('SIBRC_MODEL_V2\npicture_type '+kind+'\nqp_mapping exp2_qp_minus4_over6\nfeature_selector '+str(selector)+'\ninformation_scale '+str(4 if selector==2 else 1)+'\ninformation_floor 1e-12\nrate_unit ctu_bits\ndistortion_unit spherical_weighted_mse\nrate 4 -1 .1 0 0 0\ndistortion 0 1 .1 0 0 0\n')
   table=out/'samples.csv'; fields=['source_sequence','window_start','poc','ctu','kind','actual_qp','area','bits','weighted_mse']+['feature_'+f for f in ['C0','C1','C2','C3','C4','plane','geo','satd']]
   with table.open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for kind in ['I','P']:
     for ctu in range(3):
      writer.writerow(dict(source_sequence='DrivingInCity',window_start=0,poc=0,ctu=ctu,kind=kind,actual_qp=28,area=1,bits=4,weighted_mse=2,**{'feature_'+x:(ctu+1)*(4 if x=='C2' else 1) for x in ['C0','C1','C2','C3','C4','plane','geo','satd']}))
   good=subprocess.run([str(exe)]+paths+[str(table)],capture_output=True,text=True); self.assertEqual(good.returncode,0,good.stdout+good.stderr);self.assertIn('"controller_replay_pass":true',good.stdout)
   bad=Path(paths[2]);bad.write_text(bad.read_text().replace('rate 4 -1','rate 5 -1'))
   failed=subprocess.run([str(exe)]+paths+[str(table)],capture_output=True,text=True); self.assertEqual(failed.returncode,1); self.assertIn('"controller_replay_pass":false',failed.stdout)
if __name__=='__main__': unittest.main()
