# -*- coding: utf-8 -*-
import json
from pathlib import Path
D=Path('I:/vvenc-LFNST/.worktrees/sibrc300-20261010/metrics360')
a=json.loads((D/'assessment.json').read_text());p=a['points'];targets=sorted({q['target_bps'] for q in p})
lines=['# AerialCity ERP 300-frame three-metric evaluation','',
'Existing frozen VTM-RC@VVenC anchor versus SIBRC full I/P streams. ERP 3840x1920, 30 fps, LDP, VVenC 1.12.0 vvencFFapp faster, serial CTU feedback, QPA off. Four targets from native CQP 37/32/27/22. No re-encoding. All eight reconstructions match the previous full coded-prefix SHA256; ordinary Y/WS per-picture arrays are unchanged.','',
'WS-PSNR, S-PSNR-NN and CPP-PSNR are now project defaults. All reported PSNRs are luma. S/CPP call the original project 360Lib directly, with 655362 sphere points, source8/reconstruction10 and CPP 3840x1920, Lanczos3 luma/Lanczos2 chroma. Qualities are arithmetic means of 300 per-picture dB values. This CPP definition includes 360Lib integer rounding and clipping at each projection bit depth; do not mix it with old bilinear error-plane approximations.','',
'S-PSNR geometry metadata is explicitly initialized through the original initCFSPSNR interface. At the lowest target, all 300 S-PSNR values were recomputed after this initialization correction; the independent CPP results were retained and checked for exact equality against fresh corrected evaluations at frames 0, 150 and 299. The other six streams use the corrected evaluator for both metrics. Separate executable hashes preserve this provenance.','',
'| Metric | SIBRC BD-rate vs anchor |','|---|---:|']
for key,label in [('wspsnr','WS-PSNR'),('spsnr','S-PSNR-NN'),('cpppsnr','CPP-PSNR'),('psnr','ordinary Y-PSNR')]:lines.append('| %s | %+.4f%% |'%(label,a['bd_rate_percent'][key]))
lines+=['','Negative BD-rate means rate saving. Actual complete Annex-B rate, common-quality-range PCHIP log-rate integration, no extrapolation. One content sequence: these results describe this experiment.','',
'| Target Mbps | Metric | Anchor dB | SIBRC dB | Delta dB |','|---:|---|---:|---:|---:|']
for target in targets:
 aa=next(q for q in p if q['target_bps']==target and '_anchor_' in q['name']);bb=next(q for q in p if q['target_bps']==target and '_full_' in q['name'])
 for key,label in [('wspsnr','WS'),('spsnr','S-NN'),('cpppsnr','CPP')]:
  av=aa['mean_y_'+key];bv=bb['mean_y_'+key];lines.append('| %.6f | %s | %.6f | %.6f | %+.6f |'%(target/1e6,label,av,bv,bv-av))
lines+=['','## Per-frame plots','',
'All frames 0..299 are included, with no smoothing. Encoder POC bits sum exactly to full Annex-B size for all eight streams. Frame bitrate = POC bits times 30 fps. The logarithmic bitrate axis preserves the first I-frame peak and subsequent P-frame variations.','',
'![Frame bitrate](frame_bitrate.png)','', '![S-PSNR-NN](frame_spsnr.png)','',
'Vector PDF/SVG and 600-dpi PNG exports accompany both figures; grayscale previews and layout audits are retained. `frames.csv` contains 2400 rows (300 frames x 4 targets x 2 methods) and all four per-picture quality values. `protocol.json` hashes metric sources, library, executable and sphere data.','',
'Evaluation uses two C-disk temporary reconstructions and an SSD source cache whose 300-frame prefix SHA256 equals the original sequence, to avoid I-disk contention. The cancelled I-disk pilot and recovered metric attempts are excluded from coding time comparisons. Temporary reconstruction files are removed only after full size/hash checks.']
(D/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
print(json.dumps(a['bd_rate_percent']))
zh=['# AerialCity ERP：300帧三指标评价','',
'复用已编码的四个目标码率、共八条码流。配置为 VTM-RC@VVenC，VVenC 1.12.0 vvencFFapp faster，LDP，3840×1920，30 fps，关闭 QPA，保持串行 CTU 反馈。目标码率由定 QP 37/32/27/22 的实际码率获得。','',
'| 质量指标 | SIBRC 相对 anchor 的 BD-rate |','|---|---:|']
for key,label in [('wspsnr','WS-PSNR'),('spsnr','S-PSNR-NN'),('cpppsnr','CPP-PSNR'),('psnr','普通 Y-PSNR（补充）')]:
 zh.append('| %s | %+.4f%% |'%(label,a['bd_rate_percent'][key]))
zh+=['','| 目标码率 Mbps | Anchor 实际 Mbps | SIBRC 实际 Mbps |','|---:|---:|---:|']
for target in targets:
 aa=next(q for q in p if q['target_bps']==target and '_anchor_' in q['name']);bb=next(q for q in p if q['target_bps']==target and '_full_' in q['name'])
 zh.append('| %.6f | %.6f | %.6f |'%(target/1e6,aa['actual_bps']/1e6,bb['actual_bps']/1e6))
zh+=['','负值表示节省码率。三个球面指标分别计算；普通 Y-PSNR 的变化也如实保留。本结果只对应当前 AerialCity ERP 实验。','',
'三个指标今后作为本隔离项目的默认评价输出。S/CPP 直接调用原项目 360Lib，S 使用 655362 个标准球面点及最近邻采样；CPP 使用 3840×1920 投影和 Lanczos3/Lanczos2 插值。报告亮度指标，序列质量为300帧逐帧dB的算术平均值。BD-rate 使用实际完整码流码率、共同质量区间和 PCHIP 对数码率积分，不外推。','',
'S-PSNR 的投影元数据已通过原接口显式初始化。最低码率点全部300帧 S-PSNR 已在修正后重算；独立的 CPP 结果保留，并在第0、150、299帧使用修正评价器重算核验，逐值完全一致。其余六条码流的 S/CPP 均使用修正后的评价器。详见 protocol.json 和每点 JSON 的独立可执行文件哈希。','',
'八条重建序列的哈希均与原实验一致，Y/WS逐帧数组完全一致；逐帧比特数之和均等于完整码流比特数。','',
'![逐帧码率](frame_bitrate.png)','',
'![逐帧S-PSNR](frame_spsnr.png)','',
'四个子图分别对应四个目标码率，包含第0—299帧，未平滑。码率纵轴采用对数刻度以保留首帧峰值。逐帧码率=该帧编码比特数×30fps。图形同时提供600dpi PNG及PDF/SVG。frames.csv包含2400条记录及三个默认指标和普通Y-PSNR。逐点均值、差值和完整定义见英文 report.md。']
(D/'report_zh.md').write_text('\n'.join(zh)+'\n',encoding='utf8')
