import unittest,numpy as np
from calibrate import fit
class ActiveSetTest(unittest.TestCase):
 def test_opposite_linear_trend_has_boundary_optimum(self):
  x=np.linspace(-2,2,101);q=4+x*6/np.log(2);info=np.ones_like(x)
  for kind,sign in [('rate',-1),('distortion',1)]:
   c=fit(q,info,np.exp(-sign*x),monotonic=kind,domain=(float(q.min()),float(q.max()),1,1))
   self.assertAlmostEqual(c[1],sign*1e-6,places=8)
   self.assertAlmostEqual(c[5],0,places=8)
   self.assertAlmostEqual(c[0],0,places=8)
if __name__=='__main__':unittest.main()
