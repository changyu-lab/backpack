# 9帧并行筛选

2026-10-12 用户要求后续改为9帧，并最大化计算资源使用。
已有100帧结果保留，后续快速筛选统一使用9帧。最终各项 average BD-rate
要求不高于同条件 SIBRC；没有同条件 SIBRC 数据时不判定达标。

本机16逻辑核、物理内存15.86GiB，启动时可用约2.21GiB。
VTMRC每个编码器仍保持串行；不同QP任务由 `--jobs` 并行调度，范围1–4，
当前4K任务采用2个worker，以免内存换页抵消并行收益。
编码时间受并发竞争影响，`timing_comparable=false`，不能用于宣称算法时间开销。
四worker小尺寸验证的16个码流、RC trace、质量值与串行版完全一致。

AerialCity输入截取前9帧为独立YUV，原100帧特征和官方GOP16轨迹取显示POC0–8，
不重新随机生成注视。头部帧数改为9并保持几何/CTU/位深一致。
来源记录：`build-gaze/aerialcity-4k9-inputs/provenance.json`。
运行输出：`build-gaze/aerialcity-4k9-ldp/`。
固定μM=μS=1、f=20，四QP目标、模式0–3、独立解码哈希及最低目标重复检查均保留。
每QP有独立partial文件，主报告按QP和模式排序，避免并发写入冲突。

9帧适合快速筛选和诊断；初始I帧占比高，且小于GOP16，不能代替完整GOP/稳态实验。
与SIBRC比较必须采用相同长度和配置，不能直接用9帧结果对比其100帧average。

```powershell
python tools/visual_gaze/run_experiment.py --encoder bin/release-static/vvencFFapp.exe --decoder I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe --input build-gaze/aerialcity-4k9-inputs/source.yuv --features build-gaze/aerialcity-4k9-inputs/features.txt --gaze build-gaze/aerialcity-4k9-inputs/gaze.txt --sphere I:/001-IBRC-exps/VTM-23.0/cfg-360Lib/360Lib/sphere_655362.txt --width 3840 --height 1920 --ctu 128 --frames 9 --fps 30 --strength 20 --configuration ldp --discard-reconstruction --jobs 2 --output build-gaze/aerialcity-4k9-ldp
```
