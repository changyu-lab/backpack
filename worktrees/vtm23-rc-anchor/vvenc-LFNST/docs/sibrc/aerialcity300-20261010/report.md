# AerialCity ERP：300 帧 LDP 四点实验

先 native 定 QP 37/32/27/22 获取完整 300 帧实际码率，再冻结这些目标运行 VTM-RC@VVenC anchor 和修复后的完整 I/P SIBRC。VVenC 1.12.0 vvencFFapp，preset faster，CTU128，QPA/native RC/WPP/IFP 等关闭；独立进程并行，每进程串行反馈。模型未重新训练。全部候选独立解码，核验300帧重建大小并记录重建哈希。关闭编码器重建输出以减少并行写盘，独立解码使用快速盘临时重建，逐点质量及完整重建哈希计算完成后删除临时像素文件；16帧完整SIBRC码流和两条trace已验证与启用重建输出时完全一致。

WS-PSNR BD-rate：-4.3970%；普通 Y-PSNR BD-rate：+4.6872%。使用实际码率及共同质量区间；负值为码率节省。

|QP 基准|目标 Mbps|anchor 实际 Mbps|SIBRC 实际 Mbps|anchor WS dB|SIBRC WS dB|ΔWS dB|
|---:|---:|---:|---:|---:|---:|---:|
|37|0.359510|0.362810|0.360702|34.018219|34.254527|+0.236308|
|32|0.792057|0.793548|0.793332|36.182472|36.258105|+0.075633|
|27|2.196112|2.202149|2.197608|38.015734|38.068447|+0.052713|
|22|11.820750|11.822724|11.823594|39.702385|39.747796|+0.045411|

分段结果及动作/回退统计见 temporal_diagnosis.json；命令、资产哈希和输入前缀哈希见 protocol.json 与各 run.json。并发墙钟时间不能作为隔离速度比较。该结果来自 AerialCity 单序列，不能直接推广为多序列有效性。

## Temporal behavior

|Point|All 300 frames WS delta (dB)|Last 150 frames WS delta (dB)|Frames with WS gain|
|---:|---:|---:|---:|
|1|+0.236308|+0.167482|280/300|
|2|+0.075633|+0.002547|232/300|
|3|+0.052713|-0.004384|214/300|
|4|+0.045411|+0.003674|229/300|

The low-rate improvement persists in the last 150 frames. Late gains at R2-R4 are close to zero; R3 is slightly negative. The aggregate BD-rate gain does not imply a uniform gain over every frame.

## Encoding elapsed time under concurrent scheduling

|Point|Anchor seconds|SIBRC seconds|Ratio|
|---:|---:|---:|---:|
|1|511.45|669.29|1.309|
|2|642.22|858.80|1.337|
|3|973.76|1228.23|1.261|
|4|2214.28|2397.68|1.083|

Encoding batch span: 46.30 min, up to four independent serial encoders. Sum of per-job elapsed times: 158.26 min. These are observed concurrent elapsed times, not an isolated speed benchmark or pure controller overhead. CQP and quality evaluation are excluded.
