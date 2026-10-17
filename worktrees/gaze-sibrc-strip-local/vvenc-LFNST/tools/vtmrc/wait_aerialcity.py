import ctypes,json,re,time
from pathlib import Path
folder=Path('build-vtmrc/aerialcity16_ldp');manifest=json.loads((folder/'vtm_runs.json').read_text(encoding='utf8'))
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p
k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];k.GetExitCodeProcess.restype=ctypes.c_int
k.CloseHandle.argtypes=[ctypes.c_void_p]
handles=[k.OpenProcess(0x1000,0,r['pid']) for r in manifest['runs']]
assert all(handles),'cannot open own VTM processes'
last=None
try:
 while True:
  progress=[];alive=False
  for run,handle in zip(manifest['runs'],handles):
   code=ctypes.c_ulong();assert k.GetExitCodeProcess(handle,ctypes.byref(code))
   live=code.value==259;alive|=live
   text=Path(run['log']).read_text(encoding='utf8',errors='replace')
   frames=len(re.findall(r'\[RC360RC\]\[FrameBits\] POC=',text))
   progress.append((run['rate'],frames,'running' if live else code.value))
   if not live:
    run['returncode']=code.value
    assert code.value==0 and frames==16,(run['rate'],code.value,frames,text[-3000:])
  if progress!=last:print(json.dumps(progress),flush=True);last=progress
  if not alive:break
  time.sleep(20)
 (folder/'vtm_runs.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
 print('PASS all four original VTM encodes exit0,16pictures',flush=True)
finally:
 for handle in handles:k.CloseHandle(handle)
