import unittest
from pathlib import Path
from matched_ra32 import method_command,summary,native_cpp


class MatchedRA(unittest.TestCase):
    def test_method_only_replaces_outputs_and_adds_controller(self):
        anchor=['old-exe','--preset','faster','-c','frozen-ra.cfg','-i','source.yuv',
                '-f','32','--InternalBitDepth=10','--NumRefPics=1','-b','anchor.vvc',
                '--VTMTargetBitrate=123','--VTMRCTrace=anchor.csv']
        actual=method_command(anchor,Path('new-exe'),Path('features'),Path('out/R1'),Path('rec.yuv'))
        self.assertEqual(anchor[0],'old-exe')
        self.assertEqual(actual[1:actual.index('-b')],anchor[1:anchor.index('-b')])
        self.assertIn('--VTMTargetBitrate=123',actual)
        self.assertIn('--VisualGazeMode=1',actual)
        self.assertEqual(actual[actual.index('-f')+1],'32')
        self.assertNotIn('-q',actual)

    def test_incomplete_average_not_reported(self):
        self.assertIsNone(summary(['a','b'],{'a':{'comparisons':{'s_psnr_nn_bd_rate_percent':-1}}},{})['average'])

    def test_native_metrics_require_all_frames_and_finite_values(self):
        original=[{'s_psnr_nn':30.}]*32
        valid=dict(picture_y_spsnr=[30.]*32,picture_y_cpppsnr=[31.]*32)
        self.assertEqual(native_cpp(valid,original),31.)
        for values in ([31.]*31,[float('nan')]*32):
            bad=dict(valid,picture_y_cpppsnr=values)
            with self.assertRaises(ValueError):native_cpp(bad,original)


if __name__=='__main__':unittest.main()
