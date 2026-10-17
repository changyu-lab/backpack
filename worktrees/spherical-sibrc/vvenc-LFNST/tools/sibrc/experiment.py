"""Run an explicit JSON command manifest; capture provenance and fail closed."""
import argparse,csv,hashlib,json,subprocess,time
from pathlib import Path

def sha256(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''): h.update(chunk)
 return h.hexdigest()

def poc_values(path):
 with open(path,newline='') as f: return sorted({int(row['poc']) for row in csv.DictReader(f)})

def poc_count(path): return len(poc_values(path))

def run(command,inputs,outputs):
 if any(Path(p).exists() for p in outputs): raise ValueError('declared output already exists; choose fresh output paths')
 record={'command':command,'inputs':{str(p):sha256(p) for p in inputs},'started_unix':time.time()}
 start=time.perf_counter(); result=subprocess.run(command,capture_output=True,text=True)
 record.update(returncode=result.returncode,elapsed_seconds=time.perf_counter()-start,stdout=result.stdout,stderr=result.stderr,outputs={str(p):sha256(p) for p in outputs if Path(p).is_file()})
 record['missing_outputs']=[str(p) for p in outputs if not Path(p).is_file()]
 return record

def main():
 p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); p.add_argument('--output',required=True); a=p.parse_args()
 manifest=json.loads(Path(a.manifest).read_text(encoding='utf-8-sig')); records=[]
 for job in manifest['jobs']:
  record=run(job['command'],job.get('inputs',[]),job.get('outputs',[])); record['name']=job['name']; records.append(record)
  if record['returncode']==0 and job.get('trace'):
   record['pocs']=poc_values(job['trace']); record['unique_pocs']=len(record['pocs']); record['expected_pocs']=job['expected_pocs']; record['poc_coverage_ok']=record['pocs']==list(range(job['expected_pocs']))
  if record['returncode']==0 and job.get('hash_equal'):
   record['hash_equal']=[{'paths':pair,'equal':sha256(pair[0])==sha256(pair[1])} for pair in job['hash_equal']]
  Path(a.output).write_text(json.dumps({'manifest':manifest,'manifest_sha256':sha256(a.manifest),'records':records},indent=2))
  if not record.get('poc_coverage_ok',True) or record['returncode'] or record['missing_outputs'] or record.get('unique_pocs')!=record.get('expected_pocs') or any(not pair['equal'] for pair in record.get('hash_equal',[])): raise SystemExit('job failed verification: '+job['name'])
if __name__=='__main__': main()
