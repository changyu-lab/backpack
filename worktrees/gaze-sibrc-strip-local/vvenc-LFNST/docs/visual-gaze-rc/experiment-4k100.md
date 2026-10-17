# AerialCity 4K / 100 帧后续实验

2026-10-12 用户授权继续实验。沿用分支实现与固定试验系数，执行原始
3840×1920、30fps、8bit YUV420 ERP 的前 100 帧。

第一阶段为 LDP16：QP22/27/32/37 固定 QP 产生目标，再做模式0–3，合计20次主编码。
每个 RC 码流计算亮度 PSNR/WS-PSNR/S-PSNR-NN、文件码率偏差、虚拟缓冲；
独立 VTM23 解码核对重建哈希，完整模式最低目标额外重复编码。
μM=μS=1、f=20、faster preset、CTU128；没有按测试集 BD-rate 调参。
这些仍为平台移植试验，作者 ACO/参数尚未核实。

输入：`I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv`。
官方 ScanDMM commit/model/seed 同初次实验，按每16个显示 POC 推理，尾段4帧。
轨迹每帧覆盖37–46个关键 CTU（平均41.52/450）；初次256×128测试全部8个CTU都被标记，
因此原分辨率实验对于评价关键/非关键分配机制尤其必要。

工作盘启动时仅约16.5GB可用。使用 `--discard-reconstruction`：完成指标与独立解码哈希核对后
删除该点生成的原始重建文件。码流、逐帧指标、命令、日志、哈希及CSV保留。
该选项已在16个小尺寸RC编码点验证：全部解码一致，最后没有残留YUV。
编码日志改为实时写入文件，便于长实验观察；编码参数与数值内核未变。

## 当前检查点

100帧特征/轨迹与输入哈希已完成，来源和统计保存为 `aerialcity-4k100-inputs.json`。
QP22固定编码已完成：输出5,311,916字节，码率12,748,598.4bps，取整目标12,748,598bps，
编码耗时941.738秒。后续RC矩阵在运行，尚未得到完整RD结果。
实时状态以输出目录日志与 `results.partial.json` 为准；全部完成后生成 `report.json`。

输入及原始输出分别在 `build-gaze/aerialcity-4k100-inputs/` 和
`build-gaze/aerialcity-4k100-ldp/`。完成前不报告 BD-rate。

```powershell
python tools/visual_gaze/infer.py --repo external/ScanDMM --input I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv --width 3840 --height 1920 --frames 100 --gop 16 --output build-gaze/aerialcity-4k100-inputs
python tools/visual_gaze/prepare.py features --input I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv --width 3840 --height 1920 --ctu 128 --bitdepth 10 --frames 100 --mu-m 1 --mu-s 1 --output build-gaze/aerialcity-4k100-inputs/features.txt
python tools/visual_gaze/prepare.py gaze --manifest build-gaze/aerialcity-4k100-inputs/manifest.json --width 3840 --height 1920 --ctu 128 --bitdepth 10 --frames 100 --output build-gaze/aerialcity-4k100-inputs/gaze.txt
python tools/visual_gaze/run_experiment.py --encoder bin/release-static/vvencFFapp.exe --decoder I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe --input I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv --features build-gaze/aerialcity-4k100-inputs/features.txt --gaze build-gaze/aerialcity-4k100-inputs/gaze.txt --sphere I:/001-IBRC-exps/VTM-23.0/cfg-360Lib/360Lib/sphere_655362.txt --width 3840 --height 1920 --ctu 128 --frames 100 --fps 30 --strength 20 --configuration ldp --discard-reconstruction --output build-gaze/aerialcity-4k100-ldp
```
