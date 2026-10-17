import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_encoder import SERIAL

@unittest.skipUnless(os.environ.get('VVENC_VTMRC_EXE'),'requires compiled encoder')
class StripConfiguration(unittest.TestCase):
 def command(self,source):
  return [os.environ['VVENC_VTMRC_EXE'],'--preset','faster','-s','128x128','-fr','30','-f','32','-i',str(source),'-b',os.devnull,'--CTUSize=128','--GOPSize=32','--PicReordering=1','--POC0IDR=1','--DecodingRefreshType=1','--IntraPeriod=32','--VTMTargetBitrate=120000','--VisualGazeMode=1','--VisualGazeFeatures=not-opened-features','--SIBRCMode=3','--SIBRCStats=not-opened-stats','--SIBRCModel=not-opened-model','--SIBRCTrace='+os.devnull,'--GazeSibrcStripLocal=1','--GazeSibrcStripTrace='+os.devnull]+SERIAL
 def test_help_exposes_new_mode(self):
  p=subprocess.run([os.environ['VVENC_VTMRC_EXE'],'--help'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  self.assertIn('GazeSibrcStripLocal',p.stdout);self.assertIn('GazeSibrcStripTrace',p.stdout)
 def test_invalid_mode_combinations_fail_before_input_assets(self):
  with tempfile.TemporaryDirectory() as temp:
   source=Path(temp)/'in.yuv';source.write_bytes(bytes([128])*(128*128*3//2)*32)
   for extra in (['--GazeSibrcAlpha=.1'],['--SIBRCMode=0'],['--VisualGazeMode=0']):
    with self.subTest(extra=extra):
     p=subprocess.run(self.command(source)+extra,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
     self.assertNotEqual(p.returncode,0);self.assertIn('GazeSibrcStripLocal requires VisualGazeMode=1 SIBRCMode=3 GazeSibrcAlpha=1',p.stdout)
