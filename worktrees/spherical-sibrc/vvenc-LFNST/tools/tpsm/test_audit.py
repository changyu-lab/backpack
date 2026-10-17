import unittest, tempfile, struct, csv
from pathlib import Path
from audit import verify
class AuditTests(unittest.TestCase):
 def test_triples_match_trace(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'audit.bin').write_bytes(struct.pack('<6i',1,0,0,0,2,1)+struct.pack('<6h',10,7,9,20,15,18))
   (p/'trace.csv').write_text('poc,ctu,d,mcp,pixels\n1,0,5,34,2\n')
   self.assertEqual(verify(p/'audit.bin',p/'trace.csv')['pixels'],2)
   (p/'trace.csv').write_text('poc,ctu,d,mcp,pixels\n1,0,6,34,2\n')
   with self.assertRaises(ValueError):verify(p/'audit.bin',p/'trace.csv')
 def test_reject_overlap_and_truncation(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);block=struct.pack('<6i',1,0,0,0,1,1)+struct.pack('<3h',10,7,9)
   (p/'audit.bin').write_bytes(block*2);(p/'trace.csv').write_text('poc,ctu,d,mcp,pixels\\n1,0,2,18,2\\n'.replace('\\n','\n'))
   with self.assertRaises(ValueError):verify(p/'audit.bin',p/'trace.csv')
   (p/'audit.bin').write_bytes(block[:-1])
   with self.assertRaises(ValueError):verify(p/'audit.bin',p/'trace.csv')
if __name__=='__main__':unittest.main()
