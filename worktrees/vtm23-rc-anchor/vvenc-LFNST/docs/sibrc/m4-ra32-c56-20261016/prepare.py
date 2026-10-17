import json,shutil,subprocess,hashlib
from pathlib import Path
B=Path('/root/sibrc-ra32-m4-c56-20261016');S=Path('/dev/shm/sibrc-m4-c56-build-20261016/vvenc');F=Path('/data/vtmrc-vvenc-tune-20261014/vvenc')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
B.mkdir(exist_ok=True)
if not S.exists():shutil.copytree(F,S,ignore=shutil.ignore_patterns('.git','build','bin','lib','__pycache__'))
p=S/'source/Lib/EncoderLib/Sibrc/Statistics.cpp';text=p.read_text();original=text
text=text.replace('#include <stdexcept>','#include <stdexcept>\n#include <cstdlib>')
a='static constexpr double pi=3.14159265358979323846;'
text=text.replace(a,a+'\nstatic int ablationMode(){static int m=[](){const char* p=std::getenv("SIBRC_M4_ABLATION");if(!p)return 0;int v=std::atoi(p);if(v!=0&&v!=5&&v!=6)throw std::invalid_argument("Invalid ablation");return v;}();return m;}')
i=text.index('double informationFromResidual(');head=text[:i];body=text[i:]
a='var/=1024;if(var<=1e-12)return 0;';assert body.count(a)==1
b='var/=1024;\n if(ablationMode()==5){double total=0;int support=std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));for(int v=0;v<32;++v)for(int u=0;u<support;++u)total+=ibWeight(stats.at(latitude,u,v).rho2,5);return total;}\n if(var<=1e-12)return 0;'
body=body.replace(a,b);i=body.index('const auto& diag=covarianceDiagonals();');a='int support=std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));';body=body[:i]+body[i:].replace(a,'int support=ablationMode()==6?32:std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));',1)
p.write_text(head+body)
(B/'Statistics.before.cpp').write_text(original);(B/'Statistics.after.cpp').write_text(p.read_text())
(B/'patch.json').write_text(json.dumps(dict(before_sha256=hashlib.sha256(original.encode()).hexdigest(),after_sha256=sha(p),C5='Full band variance var*diagH*diagV/1024*gain replaced by1; latitude support and IB beta5 retained including zero residual blocks',C6='Only horizontal support expanded to32; variance gain and IB unchanged',model='Frozen original C4 I/P; no refit'),indent=2))
for cmd,n in [(['cmake','-S',str(S),'-B',str(S.parent/'build'),'-DCMAKE_BUILD_TYPE=Release','-DVVENC_ENABLE_LINK_TIME_OPT=OFF','-DCMAKE_CXX_FLAGS=-Wno-error=misleading-indentation'],'configure.log'),(['cmake','--build',str(S.parent/'build'),'-j','24'],'build.log')]:
 with (B/n).open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
shutil.copy2(S/'bin/release-static/vvencFFapp',B/'vvencFFapp');(B/'build-approved.json').write_text(json.dumps(dict(status='BUILD_PASS_GATE_PENDING',exe_sha256=sha(B/'vvencFFapp')),indent=2))
subprocess.run(['python3','-u',str(B/'run_c56.py')],check=True)
