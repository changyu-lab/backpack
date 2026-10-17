import importlib.util
import io
import hashlib
import tempfile
import unittest
from pathlib import Path
import numpy as np


class Inputs(unittest.TestCase):
    def test_source_hash_can_cover_only_evaluated_prefix(self):
        scratch=Path('build-gaze');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            p=Path(folder)/'source.yuv';p.write_bytes(b'frames_tail')
            self.assertEqual(self.module.sha(p,6),hashlib.sha256(b'frames').hexdigest())
            with self.assertRaises(ValueError):self.module.sha(p,100)

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).with_name('prepare.py')
        if path.exists():
            spec = importlib.util.spec_from_file_location('prepare', path)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        else:
            cls.module = None

    def test_scanpaths_are_display_poc_indexed(self):
        self.assertIsNotNone(self.module, 'offline input converter is missing')
        paths = np.zeros((49, 3, 2))
        paths[:, 1, :] = (.5, 1.)
        out = io.StringIO()
        self.module.write_gaze(out, [(0, [0, 2, 1], paths)], (128, 96, 64, 10, 3))
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 148)
        self.assertEqual(lines[50].split(), ['1', '0', '0', '0'])
        self.assertEqual(lines[99].split(), ['2', '0', '0.5', '1'])

    def test_invalid_scanpaths_fail(self):
        self.assertIsNotNone(self.module, 'offline input converter is missing')
        for a in (np.zeros((48, 2, 2)), np.full((49, 2, 2), np.nan), np.full((49, 2, 2), 1.1)):
            with self.subTest(shape=a.shape), self.assertRaises(ValueError):
                self.module.write_gaze(io.StringIO(), [(0, [0, 1], a)], (128, 96, 64, 10, 2))
        with self.assertRaises(ValueError):
            self.module.write_gaze(io.StringIO(), [(0, [0, 0], np.zeros((49, 2, 2)))], (128, 96, 64, 10, 2))

    def test_stationary_temporal_feature_is_zero(self):
        self.assertIsNotNone(self.module, 'offline input converter is missing')
        y, x = np.mgrid[:32, :64]
        image = ((x * 17 + y * 13) % 256).astype(float)
        edges = self.module.adaptive_edges(image)
        sf, tf = self.module.frame_features(image, image, edges, edges, 32, 1., 1., 4)
        self.assertTrue(np.all(np.asarray(sf) > 0))
        self.assertTrue(np.all(np.asarray(tf) == 0))


if __name__ == '__main__':
    unittest.main()
