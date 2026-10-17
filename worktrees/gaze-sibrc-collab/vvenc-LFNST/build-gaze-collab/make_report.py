from pathlib import Path
import json,sys
sys.path.insert(0,str(Path.cwd()/'tools/visual_gaze'))
from evaluate import bd_rate
root=Path('docs/visual-gaze-rc/collab-ra32-dev-20261016')
j=json.loads((root/'summary.json').read_text())
frozen=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/docs/sibrc/m4-ra32-20261014/runs')
metrics=('psnr','ws_psnr','s_psnr_nn','cpp_psnr')
labels=('PSNR','WS-PSNR','S-PSNR-NN','CPP-PSNR')
lines=['# RA32 / 32帧：条带预算与冻结 SIBRC C4 协同开发试验','',
'独立分支：`codex/gaze-sibrc-collab`，实现提交 `52a8a52b`。试验使用 DrivingInCity、DrivingInCountry 两条既有开发序列，不是独立泛化验证。',
'', '## 设置与隔离','',
'GOPSize=32，实际编码32帧，NumRefPics=1，四档目标码率逐点复用原32帧 CQP 结果。原 Anchor/C4/条带结果只在四项代表性码流回归通过后复用。C4 模型、统计文件、beta=5、偏移范围[-2,+2]冻结。',
'', '`mixed = max(1, round((1-alpha)*original + alpha*strip))`：先混合目标预算，只执行一次 VTM 参数估计，再由原 SIBRC 决定最终 QP/lambda。两者接收同一实际 CTU 比特反馈，全局预算只扣减一次。',
'', '远端独立目录 `/root/gaze_sibrc_collab_20261016`；原两个方法的源码、二进制、模型、统计文件和归档结果均未覆盖。四路独立串行编码并发，RAM 预留上限24GB，另核查实际可用RAM和内存盘。',
'', '## 相对单独 SIBRC 的 BD-rate（%，负值更好）','',
'| 序列 | alpha | PSNR | WS-PSNR | S-PSNR-NN | CPP-PSNR |','|---|---:|---:|---:|---:|---:|']
for n in ('DrivingInCity','DrivingInCountry'):
 for a in (.1,.25):
  v=j['comparisons'][n+':'+str(a)]
  lines.append('| '+n+' | '+str(a)+' | '+' | '.join(f"{v['C4_'+m+'_bd_rate_percent']:+.6f}" for m in metrics)+' |')
for a in (.1,.25):
 v=j['average'][str(a)]
 lines.append('| 两序列等权平均 | '+str(a)+' | '+' | '.join(f"{v['C4_'+m+'_bd_rate_percent']:+.6f}" for m in metrics)+' |')
lines += ['', '平均采用两个序列等权，包含每序列全部四档；没有按序列挑选alpha，没有排除损失点。与SIBRC直接计算BD-rate，不能用两个相对Anchor的百分比相减替代。','', '## 四点 bitrate / S-PSNR-NN','', 'bitrate 单位 kbps，质量单位 dB；按 R4 到 R1 展示。']
for n in ('DrivingInCity','DrivingInCountry'):
 lines += ['', '### '+n,'','| 档位 | 目标 | Anchor码率 | Anchor S | SIBRC码率 | SIBRC S | H0.10码率 | H0.10 S | H0.25码率 | H0.25 S |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
 for i in (4,3,2,1):
  ar=json.loads((frozen/n/'anchor'/f'R{i}.quality.json').read_text())
  sr=json.loads((frozen/n/'C4'/f'R{i}.quality.json').read_text())
  vals=[ar['target_bps']/1000,ar['actual_bps']/1000,ar['mean_y_spsnr'],sr['actual_bps']/1000,sr['mean_y_spsnr']]
  for a in (.1,.25):
   p=next(p for p in j['points'] if (p['sequence'],p['point'],p['alpha'])==(n,i,a))
   vals += [p['actual_bps']/1000,p['quality']['s_psnr_nn']]
  lines.append('| R'+str(i)+' | '+' | '.join(f'{v:.6f}' for v in vals)+' |')
lines += ['', '## 生效、反馈与码率误差','', '| 序列 | alpha | 混合目标改变CTU | SIBRC非零动作CTU | fallback CTU | 总CTU | 平均绝对码率误差% |','|---|---:|---:|---:|---:|---:|---:|']
for n in ('DrivingInCity','DrivingInCountry'):
 for a in (.1,.25):
  ps=[p for p in j['points'] if p['sequence']==n and p['alpha']==a]
  counts=[sum(p['activity'][k] for p in ps) for k in ('mixed_active_ctus','sibrc_active_ctus','sibrc_fallback_ctus','ctus')]
  mae=sum(abs(p['bitrate_error_percent']) for p in ps)/4
  lines.append('| '+n+' | '+str(a)+' | '+' | '.join(map(str,counts))+f' | {mae:.6f} |')
lines += ['', 'fallback 是冻结 SIBRC 已有的合法路径，单列计数并与 `frozen-c4-activity.json` 对照，不因发生fallback而删除该点。所有点均核验四份CTU日志：VTM决策/反馈、SIBRC、条带和协同，核对QP/offset、lambda比例、帧预算连续性、真实比特和条带扣减。',
'', '## 验证与证据','',
'40项CTest通过；初版26项Python测试通过；加强后的11项runner测试在本地和远端通过；6项真实CLI非法配置拒绝测试通过。16点均完成32帧RA、独立解码与编码重建SHA一致、四指标有限值、S-PSNR逐帧与原生指标工具一致性及四trace反馈交叉核验。',
'', '四项代表性兼容门禁：双关=原Anchor，G-only=原条带，S-only=原C4，G+S且alpha0=原C4，均码流SHA逐字节一致。门禁只覆盖DrivingInCity R1，不能宣称已证明所有配置完全等价。',
'', '结果：`summary.json`；不可变输入与工具身份：`manifest.json`；门禁：`compatibility-approved.json`；CLI：`cli-validation.json`；旧文件保护：`original-assets-before.json`、`original-assets-after.json`。完整码流、压缩trace、逐点命令/指标/日志保留在远端results，并在本地build-gaze-collab证据归档留存。']
(root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('Report generated',root/'report.md')
