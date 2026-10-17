import json,hashlib,shutil,subprocess,time
from pathlib import Path
B=Path('/root/sibrc-ra300-stable-20261016');SRC=Path('/dev/shm/sibrc-ra300-stable-build-20261016/vvenc');OLD=Path('/data/vtmrc-vvenc-tune-20261014/vvenc')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
B.mkdir(exist_ok=True)
assert not (B/'build-approved.json').exists(),'Already built; inspect rather than repeat'
if not SRC.exists():shutil.copytree(OLD,SRC,ignore=shutil.ignore_patterns('.git','build','bin','lib','__pycache__'))
f=SRC/'source/Lib/EncoderLib/VtmRcCompat/Adapter.cpp';t=f.read_text();before=sha(f)
a='    if(m_cfg.m_IntraPeriod!=1 && seq->getLeftAverageBits()<=0)\n      throw std::runtime_error("VTM23 RC unsupported nonpositive remaining intra budget (upstream numerical domain)");\n    if(m_cfg.m_IntraPeriod!=1)\n      rcPic.setTargetBits(std::max(200,rcPic.getRefineBitsForIntra(seq->getLeftAverageBits())));'
b='    if(m_cfg.m_IntraPeriod!=1)\n    {\n      const int remainingAverageBits=seq->getLeftAverageBits();\n      // Deterministic numeric-domain extension: positive-budget VTM path unchanged.\n      const int refinedBits=remainingAverageBits>0 ? rcPic.getRefineBitsForIntra(remainingAverageBits) : 200;\n      rcPic.setTargetBits(std::max(200,refinedBits));\n    }'
assert t.count(a)==1,'Patch context mismatch';f.write_text(t.replace(a,b))
(B/'source-patch.json').write_text(json.dumps(dict(before=before,after=sha(f),old_exe_sha256=sha(OLD/'bin/release-static/vvencFFapp'),scope='Only nonpositive remaining intra budget maps deterministically to200; positive path unchanged; not unmodified VTM23 behavior'),indent=2))
(B/'Adapter.before.cpp').write_text(t);(B/'Adapter.after.cpp').write_text(f.read_text())
def run(cmd,name):
 with (B/name).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run(['cmake','-S',str(SRC),'-B',str(SRC.parent/'build'),'-DCMAKE_BUILD_TYPE=Release','-DVVENC_ENABLE_LINK_TIME_OPT=OFF','-DCMAKE_CXX_FLAGS=-Wno-error=misleading-indentation'],'configure.log')
run(['cmake','--build',str(SRC.parent/'build'),'-j','24'],'build.log')
exe=SRC/'bin/release-static/vvencFFapp';assert exe.exists();shutil.copy2(exe,B/'vvencFFapp')
(B/'build-approved.json').write_text(json.dumps(dict(status='BUILD_PASS_NOT_REGRESSION_APPROVED',exe_sha256=sha(B/'vvencFFapp'),scope='Only numeric guard change; do not run failed formal streams until positive-path gates pass'),indent=2))
print('BUILD PASS; regression gates pending',flush=True)
