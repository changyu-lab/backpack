import unittest
import numpy as np
import calibrate
class MonotonicTests(unittest.TestCase):
 def samples(self):
  q,z=np.meshgrid(np.linspace(20,40,9),np.linspace(-5,3,9)); q=q.ravel(); i=np.exp(z.ravel()); return q,i
 def test_default_coefficients_unchanged(self):
  q,i=self.samples(); f=calibrate.features(q,i); y=np.exp(f@np.array([2,.3,-.1,.02,.01,-.005])); scale=np.maximum(np.sqrt(np.mean(f*f,axis=0)),1e-12); penalty=np.eye(6)*.001; penalty[0,0]=0
  expected=np.linalg.lstsq(np.vstack((f/scale,penalty)),np.r_[np.log(y),np.zeros(6)],rcond=None)[0]/scale
  np.testing.assert_array_equal(calibrate.fit(q,i,y),expected)
 def test_constraints_across_domain(self):
  q,i=self.samples(); f=calibrate.features(q,i)
  for kind,sign in [('rate',-1),('distortion',1)]:
   # Deliberately fit data with the wrong QP trend; constraints must override it.
   y=np.exp(f@np.array([2,-sign*.4,.1,.08,.01,-sign*.02]))
   c=calibrate.fit(q,i,y,monotonic=kind)
   x,z=np.meshgrid(np.linspace(f[:,1].min(),f[:,1].max(),31),np.linspace(f[:,2].min(),f[:,2].max(),31))
   derivative=c[1]+c[3]*z+2*c[5]*x
   self.assertGreaterEqual(float((sign*derivative).min()),.999e-6)
 def test_constraint_domain_wider_than_fit_domain(self):
  q,i=self.samples(); mask=(i>1)&(i<5); q=q[mask]; i=i[mask]
  f=calibrate.features(q,i); y=np.exp(f@np.array([2,.2,.1,.4,0,.01]))
  c=calibrate.fit(q,i,y,monotonic='rate',domain=(10,50,np.exp(-10),np.exp(8)))
  corner=calibrate.features(np.array([10,10,50,50]),np.exp(np.array([-10,8,-10,8])))
  self.assertLessEqual(float(np.max(c[1]+c[3]*corner[:,2]+2*c[5]*corner[:,1])),-.999e-6)
 def test_invalid_constraint_rejected(self):
  q,i=self.samples()
  with self.assertRaises(ValueError): calibrate.fit(q,i,np.ones(len(q)),monotonic='typo')
if __name__=='__main__': unittest.main()
