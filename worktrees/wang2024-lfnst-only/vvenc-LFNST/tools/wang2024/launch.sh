set -eu
cd /data/wang2024_lfnst_only_20261007
python3 - <<'PY'
from pathlib import Path
import hashlib,json,os,subprocess,sys,shutil
root=Path.cwd()
report=json.loads((root/'smoke/verification.json').read_text())
assert report['status']=='PASS' and report['independent_decode']
assert report['encoder_sha256']==hashlib.sha256((root/'src/bin/release-static/vvencFFapp').read_bytes()).hexdigest()
assert shutil.disk_usage(root).free>8*2**30
pidfile=root/'worker.pid'
if pidfile.exists():
 pid=int(pidfile.read_text())
 try:os.kill(pid,0)
 except ProcessLookupError:pass
 else:raise RuntimeError('Wang runner already active: '+str(pid))
env=dict(os.environ,WANG_CPU_LIST='18,20',PYTHONUNBUFFERED='1')
with (root/'worker.log').open('ab') as log:
 p=subprocess.Popen([sys.executable,'-u','-m','tools.wang2024.run_matrix'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
pidfile.write_text(str(p.pid)+'\n')
print('WANG_WORKER_PID='+str(p.pid))
PY
