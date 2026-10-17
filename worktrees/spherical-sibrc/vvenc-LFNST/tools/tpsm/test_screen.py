import unittest,tempfile,json
from pathlib import Path
from screen import load_targets,validate_profiles
class ScreenTests(unittest.TestCase):
 def test_frozen_target_lineage(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'targets.json').write_text('[100,200,300,400]');meta=dict(source_prefix_sha256='abc',width=128,height=64,frames=16,fps=30,stage='cqp');(p/'manifest.json').write_text(json.dumps(meta))
   values,provenance=load_targets(p/'targets.json',meta)
   self.assertEqual(values,[100,200,300,400]);self.assertIn('sha256',provenance)
   other=dict(meta,frames=8)
   with self.assertRaises(ValueError):load_targets(p/'targets.json',other)
 def test_duplicate_profiles_rejected(self):
  with self.assertRaises(ValueError):validate_profiles(['joint','joint'])
  with self.assertRaises(ValueError):validate_profiles(['unknown'])
  validate_profiles(['anchor','sibrc','joint'])
if __name__=='__main__':unittest.main()
