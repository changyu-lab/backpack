from pathlib import Path
import json,csv,gzip,hashlib,collections
root=Path.cwd();e=root/'build-gaze-strip-local/evidence';dest=root/'docs/visual-gaze-rc/strip-local-aerialcity-20261016';dest.mkdir(parents=True,exist_ok=True)
j=json.loads((e/'results-final/summary.json').read_text());assert j['completed_points']==4 and not j['failures']
frozen=Path('C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/docs/sibrc/m4-ra32-20261014/runs/AerialCity')
def rows(p):
 with (gzip.open(p,'rt') if str(p).endswith('.gz') else p.open()) as f:return list(csv.DictReader(f))
metrics=('psnr','ws_psnr','s_psnr_nn','cpp_psnr');labels=('PSNR','WS-PSNR','S-PSNR-NN','CPP-PSNR')
lines=['# AerialCity：附件strip预算 + strip内SIBRC','',
'独立分支 codex/gaze-sibrc-strip-local，实现提交88c242f7。原模型、统计、beta5、QP偏移[-2,+2]冻结。用户确认的首个序列为AerialCity，本次仅四点，未运行其余序列。',
'', '## 实验定义','',
'RA GOP32，实际编码32帧，refs1，3840x1920，CTU128。每帧15条strip，每条30个CTU。附件公式在每条strip起点按真实帧余额分配预算，SIBRC只优化当前strip剩余CTU，并使用strip真实剩余预算；取消alpha混合。真实反馈各更新一次，跨strip不重置SIBRC校正。',
'', '## 完整四点BD-rate（%，负值更好）','', '| 对照 | PSNR | WS-PSNR | S-PSNR-NN | CPP-PSNR |','|---|---:|---:|---:|---:|']
for base in ('anchor','C4'):
 lines.append('| '+base+' | '+' | '.join(f"{j['comparisons'][base+'_'+m+'_bd_rate_percent']:+.6f}" for m in metrics)+' |')
lines += ['', '## 四点数据（R4到R1）','', '| 档位 | 目标kbps | Anchor kbps | Anchor S | SIBRC kbps | SIBRC S | strip-local kbps | strip-local S | 耗时s |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for p in sorted(j['points'],key=lambda p:-p['point']):
 i=p['point'];a=json.loads((frozen/'anchor'/f'R{i}.quality.json').read_text());s=json.loads((frozen/'C4'/f'R{i}.quality.json').read_text())
 vals=[p['target_bps']/1000,a['actual_bps']/1000,a['mean_y_spsnr'],s['actual_bps']/1000,s['mean_y_spsnr'],p['actual_bps']/1000,p['quality']['s_psnr_nn'],p['seconds']]
 lines.append('| R'+str(i)+' | '+' | '.join(f'{v:.6f}' for v in vals)+' |')
lines += ['', '## 可达性诊断','', '| 档位 | CTU总数 | SIBRC非零动作 | 无回退 | 负预算 | 低于最低可达率 | 无效预测 | 价格搜索失败 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for p in sorted(j['points'],key=lambda p:p['point']):
 a=p['activity'];r=a['fallback_reason_counts'];lines.append('| R'+str(p['point'])+' | '+' | '.join(map(str,[a['ctus'],a['sibrc_active_ctus'],r['0'],r['2'],r['3'],r['1'],r['4']]))+' |')
lines += ['', 'fallback和零特征像素回退均保留原始指标，不删除任何码率点。零特征回退属于附件既有路径，runner的ineligible标签仅用于提示，不能将其自动解释为编码损坏；是否获得增益按全部四点评估。实际strip比特不保证精确等于预测预算。', '', '## 编码耗时与码率误差','', '| 方法 | 四点耗时总和s | 相对Anchor ΔT% | 平均绝对码率误差% |','|---|---:|---:|---:|']
times={};errs={}
for m in ('anchor','C4'):
 rr=[json.loads((frozen/m/f'R{i}.run.json').read_text()) for i in range(1,5)];qq=[json.loads((frozen/m/f'R{i}.quality.json').read_text()) for i in range(1,5)];times[m]=sum(x['elapsed_seconds'] for x in rr);errs[m]=sum(abs(x['actual_bps']/x['target_bps']-1)*100 for x in qq)/4
for m in ('anchor','C4'):
 lines.append(f"| {m} | {times[m]:.6f} | {(times[m]/times['anchor']-1)*100:+.6f} | {errs[m]:.6f} |")
total=sum(p['seconds'] for p in j['points']);mae=sum(abs(p['actual_bps']/p['target_bps']-1)*100 for p in j['points'])/4
lines.append(f"| strip-local | {total:.6f} | {(total/times['anchor']-1)*100:+.6f} | {mae:.6f} |")
lines += ['', '时间为四点编码墙钟时间之和；历史Anchor/SIBRC与新四路并发试验负载不同，DeltaT是归档观测值，不能作为受控加速比。解码/指标/离线特征生成不计入编码耗时。', '', '## I/B帧及纬度资源分布诊断','', '| 档位 | I帧S变化dB | B帧平均S变化dB | I帧CTU bits变化 | B帧CTU bits变化 |','|---|---:|---:|---:|---:|']
diagnostics=[]
for p in sorted(j['points'],key=lambda p:p['point']):
 i=p['point'];q=json.loads((frozen/'C4'/f'R{i}.quality.json').read_text());mq=json.loads((e/'results-final/AerialCity'/f'R{i}.metrics.json').read_text());d=[x['s_psnr_nn']-y for x,y in zip(mq['frames'],q['picture_y_spsnr'])]
 h=rows(e/'results-final/AerialCity'/f'R{i}.sibrc.csv.gz');s=rows(frozen/'C4'/f'R{i}.sibrc.csv');bands={}
 for label,lo,hi in [('equator',0,30),('middle',30,60),('poles',60,91)]:
  H=[x for x in h if lo<=float(x['latitude'])<hi];S=[x for x in s if lo<=float(x['latitude'])<hi];bands[label]=dict(method_bits=sum(int(x['bits']) for x in H),sibrc_bits=sum(int(x['bits']) for x in S),ctus=len(H))
 changes=[sum(int(x['bits']) for x in h if (x['kind']=='I')==intra)-sum(int(x['bits']) for x in s if (x['kind']=='I')==intra) for intra in (True,False)]
 lines.append(f'| R{i} | {d[0]:+.6f} | {sum(d[1:])/31:+.6f} | {changes[0]:+d} | {changes[1]:+d} |');diagnostics.append(dict(point=i,spsnr_delta_by_poc=d,bands=bands,ctu_bits_delta_I=changes[0],ctu_bits_delta_B=changes[1]))
lines += ['', 'CTU比特不含完整AnnexB封装。各纬度比特统计见diagnostic.json；这些是编码资源统计，不是最终纬度质量证据。冻结SIBRC的CTU失真反馈含其原内部域约定，不将其直接当成最终重建球面质量。', '', '## 验证与限制','',
'41项CTest通过，最终41项Python测试通过，五种旧模式在AerialCity R1上逐字节码流一致。4点分别完成32帧覆盖、480个strip及14400个CTU日志核验；包括行公式/冻结特征、CTU比例、帧和strip真实扣减、跨行校正连续及QP/lambda合同；独立解码SHA一致、S-PSNR逐帧与原生指标工具一致。PSNR/WS由Python计算，原生工具只返回S/CPP。',
'', '首次部署脚本滞后于最终版导致一项路径保护测试失败，已停止初始门禁、保留日志，重新部署后全部测试及正式试验在results-final独立目录运行。旧结果未覆盖。',
'', '当前仅一条已使用过的序列，不能宣称14序列平均、独立泛化或两个开发序列已完成。原strip目标可达性、负余额和fallback按实测报告，不能隐藏。']
(dest/'diagnostic.json').write_text(json.dumps(diagnostics,indent=2));(dest/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('REPORT',dest/'report.md')
