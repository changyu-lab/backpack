from pathlib import Path
import unittest, subprocess, os

class VtmRcCLI(unittest.TestCase):
    def test_controller_is_exposed(self):
        exe = os.environ['VVENC_VTMRC_EXE']
        result = subprocess.run([exe, '--help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertTrue('VTMTargetBitrate' in result.stdout,
                      'Independent VTM23 RC controller option is missing')
        self.assertIn('VTMRCTrace', result.stdout)

if __name__ == '__main__':
    unittest.main()
