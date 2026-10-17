import unittest
from pathlib import Path
from run_zhao2022_ldp import parse_log
class Logs(unittest.TestCase):
    def test_native_summary(self):
        r=parse_log(Path('I:/07_IBRC/anchor/encLD16_AerialCity_r1369185.txt'))
        self.assertEqual(r['frames'],16)
        self.assertEqual(r['actual_bps'],2470380)
        self.assertEqual(r['Y_WS'],35.9514)
        self.assertEqual(r['Y_CF_CPP'],35.9421)
        self.assertEqual(r['Y_E2E_S'],35.6221)
if __name__=='__main__': unittest.main()
