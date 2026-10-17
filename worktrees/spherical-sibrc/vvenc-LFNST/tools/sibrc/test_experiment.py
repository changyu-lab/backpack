import unittest, tempfile, json, sys
from pathlib import Path
import experiment
class ExperimentTests(unittest.TestCase):
 def test_record_success_and_hash_output(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'artifact'; record=experiment.run([sys.executable,'-c','from pathlib import Path; Path(r"'+str(out)+'").write_text("ok")'],[],[str(out)])
   self.assertEqual(record['returncode'],0); self.assertEqual(len(record['outputs'][str(out)]),64)
 def test_unique_pocs(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'trace.csv'; p.write_text('poc,ctu\n0,0\n0,1\n1,0\n')
   self.assertEqual(experiment.poc_count(p),2)
if __name__=='__main__': unittest.main()
