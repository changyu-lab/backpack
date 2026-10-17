import importlib.util
from pathlib import Path
import unittest
import tempfile
import numpy as np


class Metrics(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('evaluate.py')
        self.assertTrue(path.exists(), 'evaluation implementation missing')
        spec = importlib.util.spec_from_file_location('evaluate', path)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_buffer_has_paper_inclusive_debit(self):
        self.assertEqual(self.m.buffer_status([10, 20, 30], 300, 30, 2), [10, 10, 0])

    def test_360lib_sphere_orientation_and_rounding(self):
        scratch=Path('build-gaze');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            p=Path(folder)/'sphere.txt'
            p.write_text('4\n0 0\n0 90\n0 -90\n90 0\n')
            y,x=self.m.sphere_indices(p,8,4)
            np.testing.assert_array_equal(x,[6,4,7,6])
            np.testing.assert_array_equal(y,[2,2,2,0])
        np.testing.assert_array_equal(self.m.round_360lib(np.array([.49995,.4999,-.49995,-.4999])),[1,0,-1,0])

    def test_wspsnr_weights_equator(self):
        a = np.zeros((4, 8))
        polar, equator = a.copy(), a.copy()
        polar[0] = 10
        equator[1] = 10
        self.assertGreater(self.m.quality(a, polar, 255)['ws_psnr'], self.m.quality(a, equator, 255)['ws_psnr'])

    def test_bd_rate_known_parallel_curves(self):
        self.assertAlmostEqual(self.m.bd_rate([1, 2, 4, 8], [30, 31, 32, 33],
                                              [2, 4, 8, 16], [30, 31, 32, 33]), 100., places=8)


if __name__ == '__main__':
    unittest.main()
