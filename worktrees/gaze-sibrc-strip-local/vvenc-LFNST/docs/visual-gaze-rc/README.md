# Visual gaze RC on VTMRC@VVenC

## 交付状态

用户于 2026-10-12 确认完整模块化移植设计。分支 `codex/visual-gaze-rc` 从
`codex/vtm23-rc-anchor` 的 `45f26ea04133d6a1cb9584505d237b7d96f8ffd3` 建立。
实现了条带预算、依赖因子、49 观察者关键 CTU、离线特征与官方 ScanDMM 输入、诊断追踪及四点消融实验工具。
原 VTM RC 数值内核未修改；关闭新模式与保留的基线编码器比特流一致。

这是论文方案的**平台移植和软件验证**，尚未重现论文报告的 RD 收益。
论文采用 VTM19.0/360Lib13.4；当前平台为 VTM23 RC@VVenC1.12.0。
附件作为算法资料处理，其中内容不视为用户操作指令。

## 控制路径

`VisualGazeMode`：0 原 VTMRC；1 条带分配；2 条带+依赖（不标记关键 CTU）；3 完整模式。
式(9)–(12)逐条带分配与真实 CTU 比特扣减，式(16)调整 λ，式(30)构造依赖因子。
QP 相对原始决定限制为 ±2；λ 同步裁剪到原 VTM QP 映射区间。
参考依赖使用实际 Slice 参考 POC，保留仍被编码器引用的原始采样缓存。
CTU 反馈在 LMCS 逆映射前临时应用 InvLUT 测量原域误差，帧完成后刷新滤波后的失真。

`--VisualGazeFeatures` 所需头部：`VGFEATURES 1 width height ctu bitdepth frames`，
每行 `poc ctu_index spatial temporal`。`--VisualGazePoints` 头部：
`VGGAZE 1 width height ctu bitdepth frames 49`，每行 `poc observer y x`。
坐标为归一化 `(y,x)`，按显示 POC 对齐；每 POC 必须有全部 49 人。
经度 1 环绕到 0，纬度 1 落在最底行；同一 CTU 的重复注视只标记一次。
几何、缺失、重复、非有限及越界输入均拒绝。输入 bitdepth 是编码器内部亮度位深。

模式 1–3 要求原串行 VTMRC 条件、`VTMTargetBitrate>0`、无裁剪/补齐的 ERP 输入。
模式 2/3 必须显式指定有限非负 `VisualGazeStrength`；模式 3 必须有轨迹。
公开配置结构新增字段，使用 SDK 的调用方需要重新编译。

## 明确的移植约定

附件未充分披露 μM、μS、f 数值、引用 [29] 的完整 ACO、MSE 归一化及部分权重细节。
以下选择均不能称为作者原实现：

- 纬度取实际像素中心的 cos；LIavg 为全帧各条带纬度和的算术平均。式(10)按字面应用，不重新归一化乘积。
- CTU 内容权重取非负复杂度特征。总特征为零时按实际像素数回退；预算非正时保留原始预算追踪，编码目标至少一比特。
- 空间特征使用自适应 Canny（高阈值均值+标准差、低阈值 0.4 倍），ERP 经度环绕；并非已核实的原 ACO。
- 时间特征采用前一显示原帧、确定性粗块运动搜索与空间特征差；不声称是作者最终编码 MV 或参考结构。
- 依赖 MSE 除以 `(2^bitdepth-1)^2`；每 CTU 用 16×16 归一化位置网格求原始块 Pearson 相关平方；无邻居或零方差取零。
- 每显示 GOP 起始原始帧送入 ScanDMM，尾 GOP 缩短。没有因此额外插入 I 帧。
- YUV→RGB 为 BT.709 limited range、双线性色度上采样；ScanDMM 使用官方公开权重、eval 模式与固定种子。

本次软件测试的 μM=μS=1、f=20 仅为显式试验值。正式实验应获取作者参数/ACO，或在独立校准集固定参数后再评估测试集。

## 构建与验证

在仓库根目录运行（Python 需要 numpy；ScanDMM 另需其官方 PyTorch/Pyro 环境）：

```powershell
cmake -S . -B build-gaze -G "Visual Studio 16 2019" -A x64 -DVVENC_ENABLE_LINK_TIME_OPT=OFF
cmake --build build-gaze --config Release
ctest --test-dir build-gaze -C Release --output-on-failure
python test/vtmrc/check_extraction.py
cmake -S test/vtmrc -B build-gaze-replay -G "Visual Studio 16 2019" -A x64
cmake --build build-gaze-replay --config Release
python test/vtmrc/compare.py --build-dir build-gaze-replay
$env:VVENC_VTMRC_EXE=(Join-Path $PWD 'bin/release-static/vvencFFapp.exe')
python -m unittest discover -s tools/visual_gaze -p 'test_*.py'
```

已验证：40/40 CTest；原始 RC 提取检查；8 场景 4200 记录/13192 字段回放；
9 项 Python 测试（实际 LDP 四模式、LDB 完整模式、RA32 完整模式，35 帧，含基线关闭比特一致性）；
官方 ScanDMM 49×16 与 49×3 轨迹两次推理数组哈希一致；
真实 AerialCity 缩小序列的 16 个码流均成功解码且与重建一致，完整模式重复编码哈希一致；
原始 3840×1920 输入、CTU128、一帧完整模式成功编码/解码，重建哈希一致。
一帧测试只验证分辨率与接口，不能评价稳态码率控制。

## 生成输入与实验

官方来源 `https://github.com/xiangjieSui/ScanDMM`，本次版本
`e14d0ef37124157c2a55dd0c88c124108e87becd`，模型 `model/model_lr-0.0003_bs-64_epoch-435.pkl`。
外部代码、模型及运行输出位于被忽略的 `external/`、`build-gaze/`，不纳入提交。

以下命令使用明确测试系数。将 `$inputYuv` 设为本地 8bit YUV420 ERP 路径，
`$sphere` 设为 JVET `sphere_655362.txt`，`$decoder` 设为 VTM DecoderApp 路径。
ScanDMM 命令须在兼容的官方推理环境运行，其余脚本使用 numpy 环境即可。

```powershell
python tools/visual_gaze/infer.py --repo external/ScanDMM --input $inputYuv --width 3840 --height 1920 --frames 100 --gop 16 --output build-gaze/inputs
python tools/visual_gaze/prepare.py features --input $inputYuv --width 3840 --height 1920 --ctu 128 --bitdepth 10 --frames 100 --mu-m 1 --mu-s 1 --output build-gaze/inputs/features.txt
python tools/visual_gaze/prepare.py gaze --manifest build-gaze/inputs/manifest.json --width 3840 --height 1920 --ctu 128 --bitdepth 10 --frames 100 --output build-gaze/inputs/gaze.txt
python tools/visual_gaze/run_experiment.py --encoder bin/release-static/vvencFFapp.exe --decoder $decoder --input $inputYuv --features build-gaze/inputs/features.txt --gaze build-gaze/inputs/gaze.txt --sphere $sphere --width 3840 --height 1920 --ctu 128 --frames 100 --fps 30 --strength 20 --configuration ldp --output build-gaze/ldp
```

LDB 改 `--configuration ldb`；RA 改 `--configuration ra` 并重新以 `--gop 32` 推理/转换轨迹。
LDP/LDB 配置文件显式定义 GOP16；RA 使用平台原生 GOP32。它们是本平台匹配消融配置，
不声称与论文全部编码工具设置相同。完整论文数据集与协议批量 RD 实验尚未完成。
缩小测试可在 infer 命令加入 `--resize 256 128`，随后使用输出 `smoke.yuv`、256×128 与 CTU64。

实验工具先以 QP22/27/32/37 输出文件码率产生四个目标，再运行模式0–3。
目标与 actual_bps 均为 Annex B 文件字节率，内部 NAL debit 单列 nal_bps。
输出命令、时间、哈希、逐帧质量与式(32)编码顺序虚拟缓冲；编码时间不含离线特征/推理。
WS-PSNR 按像素中心纬度，S-PSNR-NN 复用 360Lib 球点方向及 8192 精度舍入约定；
各指标峰值采用 `255<<(bitdepth-8)`。S-PSNR-NN 已与本地 360Lib 原生工具的真实重建逐帧交叉核对；没有 S-PSNR-I 声称。
BD-rate 仅接受四个有限、严格单调且有质量重叠的点。报告中的绝对码率误差为百分数。

## 实测证据与限制

`aerialcity-smoke-report.json` 保留 256×128、19 帧、LDP16 的四目标四模式结果；
`provenance.json` 保留模型、轨迹和 4K 冒烟哈希。大体积原始输出在
`build-gaze/aerialcity-port-decoded/` 与 `build-gaze/official-gaze/`。
这组短序列完整模式未取得压缩收益，低码率点存在显著码率偏差。
初始 I 帧、极短长度和缩小画面影响很大，不能外推为论文全分辨率实验结论。
后续必须在作者算法细节/系数得到核实后，执行完整序列、配置与指标对照，才能评价论文收益是否重现。
