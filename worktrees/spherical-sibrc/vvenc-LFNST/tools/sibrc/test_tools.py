import unittest
import numpy as np
import calibrate, evaluate

class CalibrationTests(unittest.TestCase):
 def test_equator_and_unsupported(self):
  rng=np.random.default_rng(23); blocks=rng.normal(size=(80,32,32))
  rho,g=calibrate.statistics(blocks,0)
  self.assertTrue(np.allclose(rho,.999999)); self.assertTrue(np.allclose(g,1))
  rho,g=calibrate.statistics(blocks,85)
  self.assertTrue(np.all(rho[:,3:]==0)); self.assertTrue(np.all(g[:,3:]==0))
 def test_constant_population_guard(self):
  rho,g=calibrate.statistics(np.ones((4,32,32)),0)
  self.assertTrue(np.all(rho==0)); self.assertTrue(np.all(g==0))
 def test_area_preserves_constant_and_mean(self):
  a=np.arange(1024).reshape(32,32)
  b=calibrate.area_resample(a,7)
  self.assertTrue(np.allclose(b.mean(axis=-1),a.mean(axis=-1)))
 def test_scaled_fit_physical_coefficients(self):
  rng=np.random.default_rng(9); qp=rng.uniform(20,40,300); info=np.exp(rng.uniform(-4,4,300))
  f=calibrate.features(qp,info); coeff=np.array([1,-.2,.3,.01,-.02,.005])
  fit=calibrate.fit(qp,info,np.exp(f@coeff),ridge=0)
  self.assertTrue(np.allclose(fit,coeff,atol=1e-8))

class EvaluationTests(unittest.TestCase):
 def test_bdrate(self):
  q=[30,33,36,39]; r=[1,2,4,8]
  self.assertAlmostEqual(evaluate.bd_rate(q,r,q,r),0)
  self.assertAlmostEqual(evaluate.bd_rate(q,r,q,np.array(r)*.9),-10)
 def test_disjoint(self):
  with self.assertRaises(ValueError): evaluate.bd_rate([1,2],[1,2],[3,4],[1,2])
 def test_weighted_latitude(self):
  src=np.zeros((4,8)); rec=src.copy(); rec[0]=10
  mse,wmse=evaluate.picture_mse(src,rec)
  self.assertEqual(mse,25); self.assertLess(wmse,mse)

if __name__=='__main__': unittest.main()
