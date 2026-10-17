"""Real encoder integration tests; synthetic trajectories are fixtures only."""
import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SERIAL = ['--Threads=0', '--MaxParallelFrames=0', '--IFP=0', '--TileParallelCtuEnc=0',
          '--Tiles=1x1', '--WaveFrontSynchro=0', '--WppBitEqual=0', '--HrdParametersPresent=0',
          '--SEIBufferingPeriod=0', '--PerceptQPA=0', '--BIM=0', '--MCTF=0', '--LookAhead=0', '--STA=0']


class Encoder(unittest.TestCase):
    def test_options_exist(self):
        r = subprocess.run([os.environ['VVENC_VTMRC_EXE'], '--help'], capture_output=True, text=True)
        self.assertIn('VisualGazeMode', r.stdout)

    def test_closed_loop_all_modes_and_ra_poc(self):
        exe = os.environ['VVENC_VTMRC_EXE']
        scratch=Path('build-gaze');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            p = Path(folder)
            frame = bytes((x * 17 + y * 13) % 256 for y in range(192) for x in range(256)) + bytes([128]) * (256 * 192 // 2)
            (p / 'in.yuv').write_bytes(frame * 35)
            features = ['VGFEATURES 1 256 192 64 10 35']
            gaze = ['VGGAZE 1 256 192 64 10 35 49']
            for poc in range(35):
                features += [f'{poc} {c} {10 + c} {10 + c}' for c in range(12)]
                gaze += [f'{poc} {o} 0.5 0.5' for o in range(49)]
            (p / 'features.txt').write_text('\n'.join(features) + '\n')
            (p / 'gaze.txt').write_text('\n'.join(gaze) + '\n')
            for mode, reorder, layout in ((0,0,'ldp'), (1,0,'ldp'), (2,0,'ldp'), (3,0,'ldp'), (3,1,'ra'), (3,0,'ldb')):
                with self.subTest(mode=mode, reorder=reorder,layout=layout):
                    trace = p / f'm{mode}r{reorder}.csv'
                    command = [exe, '--preset', 'faster', '-s', '256x192', '-fr', '30', '-f', '35',
                               '-i', str(p / 'in.yuv'), '-b', str(p / 'out.vvc'), '--CTUSize=64',
                               '--GOPSize=' + str(32 if reorder else 16), '--PicReordering=' + str(reorder), '--POC0IDR=1',
                               '--DecodingRefreshType=' + str(reorder), '--IntraPeriod=32', '--VTMTargetBitrate=120000',
                               '--VisualGazeMode=' + str(mode), '--VisualGazeStrength=20',
                               '--VisualGazeFeatures=' + str(p / 'features.txt'),
                               '--VisualGazePoints=' + str(p / 'gaze.txt'), '--VisualGazeTrace=' + str(trace)] + SERIAL
                    if not reorder:
                        command[3:3]=['-c',f'cfg/visual_gaze_{layout}16.cfg']
                    r = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    self.assertEqual(r.returncode, 0, r.stdout[-4000:])
                    if mode==0:
                        baseline=Path('build-gaze/baseline-vvencFFapp.exe').absolute()
                        if baseline.exists():
                            current=(p/'out.vvc').read_bytes()
                            old=[str(baseline)]+[v for v in command[1:] if not v.startswith('--VisualGaze')]
                            previous=subprocess.run(old,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                            self.assertEqual(previous.returncode,0,previous.stdout[-2000:])
                            self.assertEqual(current,(p/'out.vvc').read_bytes(),'disabled mode changed baseline bitstream')
                    if mode:
                        with trace.open() as f:
                            rows = list(csv.DictReader(f))
                        self.assertEqual(len(rows), 35 * 12)
                        self.assertEqual({int(r['poc']) for r in rows}, set(range(35)))
                        for row in rows:
                            self.assertLessEqual(abs(int(row['qp']) - int(row['base_qp'])), 2)
                            self.assertGreater(float(row['lambda']), 0)
                            self.assertLessEqual(float(row['phi']), 1)
                            self.assertAlmostEqual(float(row['strip_after']), float(row['strip_before']) - int(row['bits']), places=7)
                        if mode == 3:
                            self.assertEqual(sum(int(r['key']) for r in rows), 35)


if __name__ == '__main__':
    unittest.main()
