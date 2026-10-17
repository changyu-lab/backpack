# SIBRC 无增益调查：I 帧反馈接口修复与消融结果（2026-10-10）

## 已确认的错误与修复

原控制器在 VTM 基准 QP 后追加 ±2 偏移，却没有保留 VTM I 帧 pictureQP±2 的反馈约束。后续 CTU 同时受 pictureQP±2 与前一实际 QP±1 约束，偏移后的实际 QP 可使两区间交集为空；Clip3 假设下界不大于上界，因此错误逐 CTU 传播，基准 QP 也随之下降。旧 R3（128 帧）有 109 个无效交集、144 个越界 I CTU；pictureQP=28 时基准 QP 最低降到 7、应用 QP 降到 6。零偏移等价测试不能覆盖这一启用后的集成问题。

修复仅限制 I 帧候选动作至 pictureQP±2 与合法 QP 范围的交集，并拒绝已越界的输入基准 QP。P 帧策略和 native VTM RateCtrl 算术不变，真实 QP 仍反馈给原控制器。该限制是移植接口必须满足的约束；不能把它描述成论文原方案已有的约束。

此前完整 I/P 的负结果受该错误影响，不能据此断言 SIBRC 无效。模型外推、短序列预算与 EMA 偏差仍是次要问题，不能替代本次已确认的接口原因。

## 实验协议

AerialCity 原始 ERP，3840×1920，30 fps，8-bit 输入、10-bit 编码；VVenC 1.12.0 vvencFFapp，preset faster，LDP，CTU128。串行，QPA、native VVenC RC、WPP、IFP、tiles 并行关闭。独立分支 codex/sibrc-vtmrc-vvenc。比较对象为相同 VVenC 编码内核下的 VTM-RC anchor，不是原生 VTM 编码器。

以实际 Annex-B 码率计算 BD-rate，PCHIP 对数码率积分，仅使用共同质量区间；负值为节省码率。质量为逐帧 PSNR 的均值，主指标 Y-WS-PSNR（球面余弦权重），同时保留普通 Y-PSNR。各候选码流独立解码，解码重建与编码器重建 SHA256 一致。

## 完整 I/P 修复版：16 帧四点

保持初始 v1 I/P 模型、统计量及其他设置不变，仅修复 I 帧动作范围。目标码率 1.6/3.2/6.4/12.8 Mbps。

WS-PSNR BD-rate **−1.6480%**；普通 Y-PSNR BD-rate **+0.4198%**。旧完整 v1 对应结果为 +4.3368% / +5.7061%，必须标为受反馈错误影响。

|目标 Mbps|anchor 实际 Mbps|修复版实际 Mbps|anchor WS dB|修复版 WS dB|
|---:|---:|---:|---:|---:|
|1.6|2.418495|2.414565|34.701429|34.815446|
|3.2|3.284355|3.274560|35.280671|35.246089|
|6.4|6.405465|6.406650|38.314404|38.419707|
|12.8|12.807060|12.823020|39.315712|39.438322|

第一点约 +51% 超出目标，16 帧启动 I 帧消耗造成低码率点预算不足，因此不宜将此短序列作为稳态码率控制或最终性能结论。四个候选的 450 个 I CTU 均无 QP 越界、无无效交集。四点关闭 SIBRC 后码流及原 RC trace 与旧 anchor 完全一致。

## P-only 消融：128 帧四点

此消融使用修复前的已归档编码器，保留原 P 模型，仅用 QP 不变的诊断 I 模型让 I 帧选择零偏移。不是完整 I/P 方案，也不是修复版完整方案的 128 帧结果。I 帧完整 native RC trace 和重建均与 anchor 完全一致。

四点目标码率为同平台 CQP 派生的 0.413768/0.879622/2.358218/12.222900 Mbps；与 16 帧目标不同，不能直接比较两组 BD-rate 大小。

WS-PSNR BD-rate **−5.4177%**；普通 Y-PSNR BD-rate **+2.1181%**。四点 WS 提升 +0.18869/+0.09183/+0.08569/+0.06558 dB，实际码率误差 +0.3248/+0.1682/+0.0790/+0.0306%。后 64 帧中后三点 WS 略降，收益不是均匀分布。该干预同时改变 I 帧质量和后续预算，不能解释成纯参考质量传播实验。

这说明 P 帧重分配在 AerialCity 的球面加权指标上有可测收益，但普通 Y 指标仍有退化。该变体是在观察 AerialCity 后选择的开发消融；尚不能宣称跨序列普遍有效。

## 验证与后续边界

先添加回归测试，修复前复现失败，修复后通过。独立 SIBRC 测试 3/3，主程序测试 39/39，机械抽取检查通过；独立代码审查无阻断发现。修复版四点全部独立解码且重建一致。完整 I/P 修复版 128 帧和未见内容尚未测量。

后续应先跑冻结模型的完整 I/P 128 帧，再在未用于选择策略的 ERP 内容上验证。若仍退化，按 I/P、纬度区域和时间段检查真实码率/失真与预测误差；避免直接继续调参并只保留有利结果。

## 可复核数据

- 修复版 16 帧：I:/vvenc-LFNST/.worktrees/sibrc-intra-safe-smoke-20261010/assessment.json、identity_gates.json、各点 contract.json、run.json、quality.json。
- P-only 128 帧：I:/vvenc-LFNST/.worktrees/sibrc-intra-hold-20261010/assessment.json、causal_comparison.json、identity_gates.json、encoder-before-fix.exe。
- 旧接口失败证据：同目录 old_contract_check.json、v1_intra_regional_diagnosis.json。
- 所有旧完整负结果与开发诊断仍保留；初始无增益调查文档已追加更正。
