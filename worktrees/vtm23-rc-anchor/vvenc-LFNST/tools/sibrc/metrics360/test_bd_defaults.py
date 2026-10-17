import sys,json,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory(dir=str(ROOT/'build-vtmrc/metric-tests')) as d:
 p=Path(d);a=[];b=[]
 for index,rate in enumerate((100,200,400,800)):
  q={'actual_bps':rate,'mean_y_wspsnr':30+index*5,'mean_y_spsnr':31+index*5,'mean_y_cpppsnr':32+index*5};a.append(q);b.append(dict(q,actual_bps=rate*.9))
 (p/'a.json').write_text(json.dumps(a));(p/'b.json').write_text(json.dumps(b))
 cmd=[sys.executable,str(ROOT/'tools/sibrc/evaluate.py'),'bd-rate','--anchor',str(p/'a.json'),'--candidate',str(p/'b.json')]
 result=json.loads(subprocess.run(cmd,check=True,capture_output=True,text=True).stdout)
 assert isinstance(result['bd_rate_percent'],dict),'default BD-rate must include all three metrics'
 assert set(result['bd_rate_percent'])=={'mean_y_wspsnr','mean_y_spsnr','mean_y_cpppsnr'}
 assert all(abs(value+10)<1e-9 for value in result['bd_rate_percent'].values())
 single=json.loads(subprocess.run(cmd+['--quality-key','mean_y_wspsnr'],check=True,capture_output=True,text=True).stdout)
 assert abs(single['bd_rate_percent']+10)<1e-9
print('PASS default three BD-rates and explicit single-metric override')
