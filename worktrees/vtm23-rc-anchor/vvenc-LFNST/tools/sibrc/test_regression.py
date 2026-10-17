import unittest, tempfile, subprocess, sys, csv, json
from pathlib import Path
import experiment
class RegressionTests(unittest.TestCase):
 def test_preexisting_output_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old'; p.write_text('stale')
   with self.assertRaises(ValueError): experiment.run([sys.executable,'-c','pass'],[],[str(p)])
 def test_shifted_pocs_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'trace.csv'; p.write_text('poc,ctu\n1,0\n2,0\n')
   manifest=Path(d)/'manifest.json'; manifest.write_text(json.dumps({'jobs':[{'name':'shift','command':[sys.executable,'-c','pass'],'trace':str(p),'expected_pocs':2}]}))
   r=subprocess.run([sys.executable,str(Path(experiment.__file__)), '--manifest',str(manifest),'--output',str(Path(d)/'result.json')],capture_output=True)
   self.assertNotEqual(r.returncode,0)
 def test_calibration_source_and_group(self):
  import calibrate
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); meta=root/'meta.json'; meta.write_text(json.dumps({'sequences':['DrivingInCity','DrivingInCountry']})); data=root/'data.csv'; output=root/'model'
   def execute(source):
    with data.open('w',newline='') as f:
     writer=csv.DictWriter(f,fieldnames=['source_sequence','sequence','run_id','poc','kind','qp','ieff','bits','weighted_mse']); writer.writeheader()
     for seq in [source,'DrivingInCountry']:
      for run in ['qp22','qp37']:
       for ctu in range(8): writer.writerow(dict(source_sequence=seq,sequence=seq+'_'+run,run_id=run,poc=0,kind='I',qp=22 if run=='qp22' else 37,ieff=1+ctu,bits=100+ctu,weighted_mse=2+ctu))
    return subprocess.run([sys.executable,str(Path(calibrate.__file__)),'model','--input',str(data),'--metadata',str(meta),'--output',str(output),'--kind','I'],capture_output=True)
   self.assertNotEqual(execute('AerialCity').returncode,0)
   self.assertEqual(execute('DrivingInCity').returncode,0)
   result=json.loads(Path(str(output)+'.json').read_text()); self.assertEqual(result['holdout_samples'],16); self.assertEqual(result['train_samples'],16)
   self.assertEqual(result['holdout_groups'],[['DrivingInCountry',0]])
if __name__=='__main__': unittest.main()
