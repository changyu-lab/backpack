import csv,json,sys,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
import calibrate
class RefitTests(unittest.TestCase):
 def test_holdout_diagnostics_precede_all_data_refit(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); data=root/'samples.csv'; meta=root/'meta.json'; meta.write_text(json.dumps({'sequences':['DrivingInCity','DrivingInCountry']})); rows=[]
   for seq in ['DrivingInCity','DrivingInCountry']:
    for poc in range(4):
     for qp in [17,22,37,52]:
      for info in [1,3,7]:
       f=calibrate.features(np.array([qp]),np.array([info]))[0]; offset=1.2 if seq=='DrivingInCountry' and poc>=2 else 0
       rows.append(dict(source_sequence=seq,poc=poc,kind='P',qp=qp,ieff=info,bits=np.exp(f@np.array([6,-.5,.2,.01,.01,.02])+offset),weighted_mse=np.exp(f@np.array([0,.4,.1,.01,.01,.01])+offset),latitude=0))
   with data.open('w',newline='') as out:
    writer=csv.DictWriter(out,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
   def execute(name,extra):
    path=root/name; result=subprocess.run([sys.executable,str(Path(calibrate.__file__)),'model','--input',str(data),'--metadata',str(meta),'--output',str(path),'--kind','P','--equator-degrees','15']+extra,capture_output=True,text=True)
    self.assertEqual(result.returncode,0,result.stderr)
    lines=path.read_text().splitlines(); coeff={key:np.array(list(map(float,next(x for x in lines if x.startswith(key+' ')).split()[1:]))) for key in ['rate','distortion']}
    return coeff,json.loads(Path(str(path)+'.json').read_text())
   baseline,bmeta=execute('baseline',[]); refit,rmeta=execute('refit',['--refit-all'])
   self.assertEqual(rmeta['final_fit_samples'],len(rows)); self.assertEqual(rmeta['holdout_metrics_before_refit'],bmeta['holdout_log_rmse'])
   for key,field in [('rate','bits'),('distortion','weighted_mse')]:
    expected=calibrate.fit(np.array([r['qp'] for r in rows]),np.array([r['ieff'] for r in rows]),np.array([r[field] for r in rows]))
    np.testing.assert_array_equal(refit[key],expected)
    np.testing.assert_array_equal(rmeta['holdout_coefficients_before_refit'][key],baseline[key])
   self.assertEqual(rmeta['holdout_groups'],bmeta['holdout_groups'])
if __name__=='__main__': unittest.main()
