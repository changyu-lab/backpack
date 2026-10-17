# 14序列 / 17帧 / LDP16 通测

2026-10-13 用户要求14序列、LDP16、四目标、17帧，并延续最大化资源利用的要求。
原消息同时含“仅条带”和“四模式”，已发模式澄清。当前按“仅条带”准备原VTMRC(0)
及条带(1)；未将依赖/注视模式伪称为本次通测范围。四目标指固定QP22/27/32/37。
若确认全部四模式，需要扩展任务及真实ScanDMM轨迹，不能用虚构轨迹填补。

## 固定协议

- 原始分辨率、原始8/10bit YUV420，编码内部/输出10bit，CTU128，faster preset。
- 前17显示帧，LDP16串行VTMRC配置，每序列四固定QP产生Annex B文件目标码率。
- 每目标模式0/1，各点计算PSNR、WS-PSNR、S-PSNR-NN、码率误差和虚拟缓冲，独立解码核对哈希。
- 模式1最低目标重复验证；14×(4固定QP+8RC)=168次主编码，另14次重复检查。
- 特征μM=μS=1，算法规则与此前一致，不在测试集按BD-rate挑参数。模式1不需要ScanDMM。
- 4K任务两个QP worker，6K/8K一个；所有worker内部串行，避免突破内存承载能力。
- 每点验证后清理生成的重建YUV，序列完成后清理生成的源前缀；原始视频不修改。
- 保存码流、命令、CSV、指标、来源哈希、特征和日志。支持按完整序列续跑，部分序列从头跑。
- 同一路径源文件变化、模型工具/配置/sphere/编码器变化不得复用旧批次；完整序列续跑重新核对前17帧、特征、码流及trace哈希。

## 输入

`I:/Sequences360/` 共14个：AerialCity、Balboa、BranCastle2、Broadway、ChairliftRide、
DrivingInCity、DrivingInCountry、Gaslamp、Harbor、KiteFlite、Landing2、PoleVault_le、
SkateboardInLot、Trolley。全部长度已验证≥17帧。
ChairliftRide和SkateboardInLot为10bit；编码器InputBitDepth与指标input-bitdepth均显式传递。
真实10bit小尺寸八点已通过独立解码及重复验证。

## 汇总与验收

各序列BD-rate相对同平台模式0计算；最终average为全部14序列BD-rate等权算术平均。
任何序列缺失、失败、曲线无效或非有限指标时，完整average为null，不能静默排除困难序列。
用户筛选条件仍为各项average不高于同条件SIBRC。本队列尚未加入SIBRC编码，
因此它可给出条带对VTMRC的14序列average，不能独立宣称达到SIBRC约束。
17帧包含一个完整GOP16，但依然较短，码率误差须随BD-rate一并报告。
并发编码耗时不得直接解释为算法复杂度变化。

```powershell
python tools/visual_gaze/batch_strip.py --encoder bin/release-static/vvencFFapp.exe --decoder I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe --sphere I:/001-IBRC-exps/VTM-23.0/cfg-360Lib/360Lib/sphere_655362.txt --frames 17 --output build-gaze/batch14-17-strip-run
```

队列状态：`build-gaze/batch14-17-strip-run/summary.json`；完整清单及依赖身份：同目录`manifest.json`。
各序列特征预分析、固定QP、各模式日志均实时写入其子目录。完成前不报告完整average。
