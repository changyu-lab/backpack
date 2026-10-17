import unittest, importlib.util
import numpy as np
from pathlib import Path
class M4Tests(unittest.TestCase):
 def module(self):
  p=Path(__file__).with_name('calibrate_m4.py'); self.assertTrue(p.exists(),'independent M4 calibration missing')
  spec=importlib.util.spec_from_file_location('m4',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
 def rows(self):
  return [dict(source_sequence=s,window_start=w,poc=0,ctu=c,actual_qp=q,kind='I',bits=100,weighted_mse=2,**{'feature_'+f:float(c+1)*(4 if f=='C2' else 1) for f in ['C0','C1','C2','C3','C4','plane','geo','satd']}) for s in ['DrivingInCity','DrivingInCountry'] for w in [0,64,128,192] for c in range(3) for q in [22,27]]
 def test_common_invalid_intersection_and_duplicate_rejection(self):
  m=self.module(); rows=self.rows(); rows[0]['feature_satd']=float('nan'); valid,reasons=m.matched_rows(rows); self.assertEqual(len(valid),len(rows)-1); self.assertEqual(reasons['invalid_feature'],1)
  with self.assertRaises(ValueError): m.matched_rows(rows+[rows[1]])
 def test_holdout_reports_information_extrapolation_without_refitting_scale(self):
  m=self.module(); train,test=m.split_rows(self.rows());
  for r in test: r["feature_C0"]=1e9
  model=m.fit_model(train,test,"C0"); self.assertEqual(model["diagnostics"]["holdout"]["information_extrapolation_count"],len(test))
 def test_monotonic_diagnostics_report_corner_violations(self):
  m=self.module(); train,test=m.split_rows(self.rows()); model=m.fit_model(train,test,"C0"); self.assertEqual(model["monotonic_violation_count"],{"rate":0,"distortion":0})
 def test_all_zero_descriptor_keeps_rows_and_scale_one(self):
  m=self.module(); rows=self.rows();
  for r in rows: r["feature_C4"]=0
  valid,_=m.matched_rows(rows); train,test=m.split_rows(valid); model=m.fit_model(train,test,"C4"); self.assertEqual(model["scale"],1); self.assertEqual(model["diagnostics"]["train"]["zero_count"],len(train))
 def test_requested_qp_clamp_keeps_distinct_samples(self):
  m=self.module(); a=self.rows()[0]; b=dict(a); a["requested_qp"]=22; b["requested_qp"]=27; valid,_=m.matched_rows([a,b]); self.assertEqual(len(valid),2)
 def test_grouped_split_holds_all_qps_and_each_source(self):
  m=self.module(); train,test=m.split_rows(self.rows()); self.assertTrue(train and test); self.assertTrue(all(int(r['window_start'])==192 for r in test)); self.assertFalse({m.group_key(r) for r in train}&{m.group_key(r) for r in test})
 def test_c2_c3_normalized_predictions_equivalent_including_zero(self):
  m=self.module(); rows=self.rows(); rows[0]['feature_C2']=rows[0]['feature_C3']=0; train,test=m.split_rows(rows)
  a=m.fit_model(train,test,'C2'); b=m.fit_model(train,test,'C3'); self.assertAlmostEqual(a['scale'],4*b['scale']); np.testing.assert_allclose(a['rate'],b['rate'],rtol=1e-8,atol=1e-8)
  np.testing.assert_allclose(m.model_features([22]*len(rows),[r['feature_C2'] for r in rows],a['scale']),m.model_features([22]*len(rows),[r['feature_C3'] for r in rows],b['scale']),atol=1e-12)
if __name__=='__main__': unittest.main()



