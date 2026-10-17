"""Check batch mode selection and 10-bit propagation across command boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import run_experiment as runner


class Runner(unittest.TestCase):
    def test_strip_only_10bit_needs_no_gaze(self):
        scratch=Path('build-gaze');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            p=Path(folder);source=p/'source.yuv';source.write_bytes(b'\0\0')
            features=p/'features.txt';features.write_text('fixture')
            encoder=p/'encoder.exe';encoder.write_bytes(b'fixture')
            calls=[]
            def fake_run(command,log):
                c=list(map(str,command));calls.append(c)
                if '-b' in c:
                    Path(c[c.index('-b')+1]).write_bytes(b'bitstream')
                    if '-o' in c:Path(c[c.index('-o')+1]).write_bytes(b'reconstruction')
                    if any(v.startswith('--VTMRCTrace=') for v in c):
                        Path(next(v.split('=',1)[1] for v in c if v.startswith('--VTMRCTrace='))).write_text('trace')
                else:
                    Path(c[c.index('--output')+1]).write_text(json.dumps(dict(actual_bps=100,nal_bps=90,
                        quality_mean_db=dict(psnr=30,ws_psnr=30,s_psnr_nn=30),bitrate_error_percent=0)))
                return 1.
            args=['runner','--encoder',str(encoder),'--input',str(source),'--features',str(features),
                  '--sphere','sphere.txt','--output',str(p/'out'),'--width','256','--height','128',
                  '--frames','17','--ctu','64','--strength','20','--modes','0','1','--input-bitdepth','10']
            args+=['--scratch-root',str(p/'scratch'),'--discard-reconstruction','--decoder',str(encoder)]
            with patch.object(sys,'argv',args),patch.object(runner,'run',side_effect=fake_run):
                runner.main()
            report=json.loads((p/'out/report.json').read_text())
            self.assertEqual(len(report['results']),8)
            self.assertEqual({r['mode'] for r in report['results']},{0,1})
            self.assertIsNone(report['gaze_sha256'])
            for c in calls:
                if any(v.startswith('--preset') for v in c):self.assertIn('--InputBitDepth=10',c)
                elif '-b' in c:continue
                else:self.assertEqual(c[c.index('--input-bitdepth')+1],'10')


if __name__=='__main__':unittest.main()
