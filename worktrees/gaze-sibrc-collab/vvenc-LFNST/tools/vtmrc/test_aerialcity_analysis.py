import unittest
from analyze_aerialcity import vtm_rc_pictures, complete_pocs
class Statistics(unittest.TestCase):
    def test_actual_rc_bits_exclude_poc_log_framing(self):
        text='POC 0 (I-SLICE, QP 29) 168 bits [Y 40 dB] [RC360RC][FrameBits] POC=0 targetBits=160 actualBits=150 errorBits=-10'
        self.assertEqual(vtm_rc_pictures(text)[0]['actual_bits'],150)
    def test_missing_and_duplicate_pocs_rejected(self):
        for rows in [[{'poc':i} for i in range(15)],[{'poc':i} for i in range(15)]+[{'poc':14}]]:
            with self.assertRaises(AssertionError):complete_pocs(rows)
        complete_pocs([{'poc':i} for i in range(16)])
if __name__=='__main__':unittest.main()
