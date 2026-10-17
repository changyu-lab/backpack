import json
from pathlib import Path
import tempfile
import unittest
import batch_strip as batch


class Batch(unittest.TestCase):
    def test_metadata_and_short_source(self):
        scratch=Path('build-gaze');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            p=Path(folder)/'Test_4x2_60fps_10bit_420_erp.yuv'
            p.write_bytes(bytes(24*17))
            info=batch.sequence_info(p,17)
            self.assertEqual((info['fps'],info['input_bitdepth'],info['prefix_bytes']),(60,10,408))
            p.write_bytes(bytes(24*16))
            with self.assertRaises(ValueError):batch.sequence_info(p,17)

    def test_average_requires_every_sequence_and_metric(self):
        reports={'a':dict(comparisons=[dict(mode=1,ws_psnr_bd_rate_percent=-2,psnr_bd_rate_percent=1,s_psnr_nn_bd_rate_percent=-4)])}
        incomplete=batch.aggregate(['a','b'],reports)
        self.assertIsNone(incomplete['average'])
        reports['b']=dict(comparisons=[dict(mode=1,ws_psnr_bd_rate_percent=-4,psnr_bd_rate_percent=3,s_psnr_nn_bd_rate_percent=-2)])
        complete=batch.aggregate(['a','b'],reports)
        self.assertEqual(complete['average']['ws_psnr_bd_rate_percent'],-3)
        reports['b']['comparisons'][0].pop('psnr_bd_rate_percent')
        self.assertIsNone(batch.aggregate(['a','b'],reports)['average'])
        reports['b']['comparisons'][0]['psnr_bd_rate_percent']=float('nan')
        self.assertIsNone(batch.aggregate(['a','b'],reports)['average'])


if __name__=='__main__':unittest.main()
