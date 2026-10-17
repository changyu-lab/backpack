import pathlib,subprocess,os,json,random,hashlib
r=pathlib.Path('/data/wang2024_lfnst_only_20261007');o=r/'regression';o.mkdir(exist_ok=True)
random.seed(20241007)
data=bytes(max(0,min(255,100+(x*3+y*7)%80+random.randrange(-20,21))) for y in range(128) for x in range(128))
(o/'input.yuv').write_bytes(data+bytes([128])*(128*128//2))
cmd=[str(r/'src/bin/release-static/vvencFFapp'),'--preset','slow','-i',str(o/'input.yuv'),'-s','128x128','-r','30','--InputBitDepth','8','-q','22','--qpa','0','-f','1','--mtprofile','0','--threads','1','--IntraPeriod','1','--GOPSize','1','--DecodingRefreshType','1','--additional','LFNST=1 LardLfnstSkip=0','-b',str(o/'shadow.vvc'),'-o',str(o/'shadow.yuv')]
env=dict(os.environ,WANG_LFNST_MODE='shadow',WANG_LFNST_AUDIT=str(o/'shadow.json'),WANG_LFNST_VERIFY_PRIMARY='1')
with (o/'shadow.log').open('w') as f:subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
a=json.loads((o/'shadow.json').read_text())
assert sum(x.get('large_border_nonzero',0) for x in a['kernels'])>0, 'LFNST gradients must include nonzero full DCT-II borders on 16/32 TUs'
print('PASS full-primary border regression',a)
