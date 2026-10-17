import unittest
import numpy as np
from extract_zhao2022_features import extract, local_saliency

class Features(unittest.TestCase):
    def test_constant_first_frame(self):
        f=extract(np.full((16,16),80.),None,8)
        np.testing.assert_array_equal(f[:,:3],0)
        np.testing.assert_array_equal(f[:,3],0)
    def test_center_is_in_neighborhood_denominator(self):
        y=np.zeros((12,12)); y[4:8,4:8]=1
        # Orthonormal 4x4 DC is 4; eight differences, denominator nine.
        l=local_saliency(y,1,0)
        self.assertAlmostEqual(l[1,1],32/9)
        self.assertAlmostEqual(l[0,0],1.)
    def test_temporal_and_partial_ctus(self):
        y=np.zeros((20,28)); y[8:16,8:16]=100
        f=extract(y,np.zeros_like(y),8)
        self.assertEqual(f.shape,(12,4))
        self.assertAlmostEqual(f[5,1],255)
        self.assertTrue(np.isfinite(f).all())
        np.testing.assert_allclose(f[:,2],.5*(f[:,0]+f[:,1]))

if __name__=='__main__': unittest.main()

