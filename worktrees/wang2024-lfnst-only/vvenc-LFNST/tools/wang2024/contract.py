"""Frozen Wang2024 matched matrix contract (user chose old frames, repeat1)."""
from pathlib import Path
from tools.lard_lfnst import run_skip21_stage12_ra_360lib as baseline
PRESETS=('medium','fast','slow')
CONFIGS=('AI','RA','LDP')
QPS=(22,27,32,37)
ADDITIONAL='LFNST=1 LardLfnstSkip=0'
def frames(config):
 if config not in CONFIGS:raise ValueError(config)
 return 1 if config=='AI' else 16
def jobs(sequences):
 return [(p,c,s) for s in sequences for p in PRESETS for c in CONFIGS]
def command(encoder,seq,qp,preset,config,bit,rec,ldp):
 c=baseline.build_encoder_command(encoder=Path(encoder),seq=seq,qp=qp,frames=frames(config),encode_config='LD' if config=='LDP' else config,ra_gop=16,ld_gop=8,threads=1,preset=preset,additional=ADDITIONAL,bitstream=Path(bit),reconstruction=Path(rec))
 if config=='LDP':c += ['-c',str(ldp)]
 return c
def runtime_env(kind,base):
 if kind not in ('anchor','proposed'):raise ValueError(kind)
 env=dict(base)
 for k in list(env):
  if k.startswith('WANG_LFNST_') or k in ('LFNST_TRANSFORM_AUDIT','LFNST_STAGE_WRONG_AUDIT','SALDANHA_MODE','SALDANHA_MODEL'):env.pop(k,None)
 env['WANG_LFNST_MODE']='off' if kind=='anchor' else 'on'
 return env
def timing_matches(cached,expected):
 return isinstance(cached,dict) and all(cached.get(k)==v for k,v in expected.items()) and isinstance(cached.get('transform_ns'),int) and cached['transform_ns']>0
def completion_matches(marker,identity):
 return isinstance(marker,dict) and marker.get('status')=='COMPLETE' and marker.get('run_identity')==identity
