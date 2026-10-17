# 当前 LARD-LFNST 实现与实验溯源报告

日期：2026-06-05

本文档用于记录当前 `I:\vvenc-LFNST` 项目中所有 LARD-LFNST 版本的实现方法、已知性能、效果和问题，供后续论文写作、代码回溯和实验复现使用。当前分支为：

```text
codex/lfnst-ablation-logging-platform
```

## 1. 总体结论

当前项目把多代快速 LFNST 实验都挂在同一个编码器参数 `LardLfnstSkip` 下。所有版本都是编码器端候选裁剪，不改变 VVC 码流语法，解码端不需要修改。

目前最稳定、最接近工程目标的是 `LardLfnstSkip=6`，配置为：

```text
LardLfnstSkip=6
LardLfnstThetaMinDeg=45
```

在 AerialCity 首帧、medium、20 线程、QP 22/27/32/37 的冻结测试上：

| 版本 | 条件 | 时间节省 | BDBR / 质量损失 | 状态 |
| --- | --- | ---: | ---: | --- |
| Skip6 | AerialCity，1 帧，medium，20 线程 | 12.790% | Y-BDBR 0.709%，YUV-BDBR 0.701% | 达到 10% TS 与 <1% BDBR 目标 |
| Skip6 球面指标 | 同一决策，`vvencFFapp` 输出重建 | 同一决策 | WS-YUV 0.730%，CPP-YUV 0.780% | 360 组合指标也在 1% 内 |
| Skip7 | 低误跳 guarded 版本 | 1.394% | YUV-BDBR 0.0035% | 很安全，但速度收益不足 |
| Skip8 | 候选增益查表 | 3.169% | YUV-BDBR 0.348%，WS-YUV 0.344%，CPP-YUV 0.376% | 质量尚可，速度不足 |
| Skip14 mode3 | 理论空间 `{0}` 跳过，4 帧测试 | 重复中位 TS -0.026% | max YUV BDBR 0.386% | 理论更接近论文，但在线开销重 |

一个必须明确的事实是：按照后来重新定义的错误率，即“我们判断跳过 LFNST，但原始编码器最终 RDO 选择了 `lfnstIdx != 0`”，Skip6 的错误率是 33.49%。因此 Skip6 可以作为工程速度-质量折中点，但不能宣称为严格低风险的最终 `lfnstIdx` 分类器。Skip7 把该错误率降到 12.85%，但时间收益也降到约 1.4%。

## 2. 代码结构

核心文件如下。

| 文件 | 作用 |
| --- | --- |
| `include/vvenc/vvencCfg.h` | 增加所有 LARD-LFNST 配置字段 |
| `source/Lib/vvenc/vvencCfg.cpp` | 默认值和参数合法性检查 |
| `source/Lib/apputils/VVEncAppCfg.h` | 命令行参数，包含小写和标准写法 |
| `source/Lib/EncoderLib/IntraSearch.h` | LARD-LFNST 数据结构和函数声明 |
| `source/Lib/EncoderLib/IntraSearch.cpp` | 主要实现，所有 LFNST 裁剪分支都在这里 |
| `source/Lib/EncoderLib/EncCu.cpp` | final CU trace，用于统计原编码器最终 `lfnstIdx` |
| `source/Lib/EncoderLib/LardLfnstFitTable.inc` | Skip6/7 使用的分组安全阈值表 |
| `source/Lib/EncoderLib/LardLfnstSpeedTable.inc` | Skip3/5/8/9 使用的速度型阈值表 |
| `source/Lib/EncoderLib/LardLfnstCandGainTable.inc` | Skip8/9 的候选增益查表 |
| `source/Lib/EncoderLib/LardLfnstModeSkipTable.inc` | Skip9 的 mode-level skip 表 |
| `source/Lib/EncoderLib/LardLfnst2ndCorrTable.inc` | 二阶 response 相关性表 |
| `source/Lib/EncoderLib/LardLfnst2ndScoreTable.inc` | 二阶 response final-score 表 |
| `source/Lib/EncoderLib/LardLfnst2ndCoffTable.inc` | 二阶 response 辅助分桶表 |
| `source/Lib/EncoderLib/LardLfnstTheoryStatsTable.inc` | Skip14 理论统计查表 |
| `tools/lard_360_metrics.py` | WS-PSNR / CPP-PSNR BDBR 计算 |
| `tools/lard_lfnst_*.py` | trace 分析、阈值拟合、表生成和机制实验 |

构建和依赖说明：

* IEPR/ONNX 已清理，本项目当前 LFNST 工作不涉及 ONNX/IEPR。
* 本地主要使用 `build-lahtp-nolto` no-LTO 构建。
* `build-lahtp-nolto/` 是本地构建目录，已加入 `.gitignore`。

## 3. 公共判决流程

所有版本都遵循一个基本约束：只裁剪编码器搜索候选，不修改语法。若条件不满足，回退到原始 VVenC LFNST RDO。

公共适用条件：

* 非 ISP；
* 非 MIP；
* 非 multi-reference intra；
* 非 BDPCM；
* luma block 面积至少 16，宽高至少 4；
* 宽高比不超过 4:1。

公共纬度信息：

* 计算 CU 中心纬度和块跨度修正后的 `thetaMax`；
* 使用 `cos(theta)` 表征 ERP 水平拉伸；
* 支持闭式阈值：

```text
theta_skip,l = atan(sqrt(log(A_l / C_l) / (gamma_l * psi)))
```

* 支持 `LardLfnstThetaMinDeg` 覆盖闭式阈值。

早期版本使用 `org - pred` 的在线近似 DCT ROI。后期版本等待 no-LFNST DCT2 真正完成后，复用 VVenC 已经得到的量化主变换 ROI。

## 4. 各版本实现方法

### Skip0：关闭 proposed 方法

`LardLfnstSkip=0` 表示关闭 proposed 裁剪，使用原始 VVenC LFNST RDO。

特殊情况：如果设置了 `LardLfnst2ndMeasureOnly=1` 和 final-stat 文件，Skip0 也可以仅做二阶 response 统计，不实际裁剪。

### Skip1：保守两级残差 DCT 模型

实现方法：

1. 第一级：纬度阈值；
2. 第二级：对 `org - pred` 做低成本 DCT-II 近似；
3. 使用 ROI 能量、低频集中度、预测非零数三个安全条件；
4. 条件同时满足时把 LFNST 搜索范围裁剪为 `{0}`。

作用：

* 第一版完整博士方法链路；
* 适合 smoke test 和 trace 收集。

已知效果：

* 低分辨率 medium pilot，保守阈值下码流 byte-identical；
* 单线程 pilot 约 3.66% 时间节省；
* 20 线程低分辨率 pilot 因跳过率太低，收益不足以抵消在线特征计算开销。

问题：

* 在线近似 DCT ROI 计算成本偏高；
* 与 VVenC 实际量化主变换 ROI 不完全一致。

### Skip2：分组保守阈值表

实现方法：

* 仍使用 Skip1 的残差 DCT 两级模型；
* 按 QP、尺寸组、intra mode group 查 `LardLfnstFitTable.inc`。

已知效果：

* pilot trace 中分组 zero-false 表提高了预测跳过率；
* 但 closed-loop 仍有 2/12 case 出现码流变化。

问题：

* candidate trace oracle 不能完全预测 closed-loop 编码交互；
* 不适合作为主结果。

### Skip3：速度型分组阈值表

实现方法：

* 使用 `LardLfnstSpeedTable.inc`；
* 仍是早期残差 DCT 特征路径；
* 比 Skip2 更激进。

状态：

* 作为速度型实验版本保留；
* 没有被选为主线。

### Skip4：仅纬度解析阈值

实现方法：

* 只做第一级纬度阈值；
* 不做 ROI 安全校验；
* 纬度满足阈值就跳过 LFNST。

pilot 结果：

| TS | Y-BDBR | YUV-BDBR |
| ---: | ---: | ---: |
| 2.10% | -0.036% | 0.047% |

问题：

* 这不是完整两级稀疏性模型；
* 只能作为 latitude-only 消融。

### Skip5：目标速度候选裁剪

实现方法：

* 使用速度型阈值表；
* 在 luma mode 循环较早阶段禁用 LFNST；
* 主要目标是达到 10% 以上时间下降。

pilot 结果：

| TS | Y-BDBR | YUV-BDBR |
| ---: | ---: | ---: |
| 17.35% | 0.423% | 0.470% |

问题：

* 这是 aggressive speed 版本；
* 不能和论文里“保守、可解释、低风险两级判据”混成同一个结论。

### Skip6：优化后的 lazy 两级量化 ROI 模型

实现方法：

* 当前工程主线；
* stage 1 使用纬度阈值；
* stage 2 复用 no-LFNST DCT2 后的真实量化 ROI；
* 根据 `LardLfnstFitTable.inc` 查分组阈值；
* 满足 ROI 能量、低频集中度、非零数条件后，跳过候选 1 和 2；
* 当前代码中 Skip5/6 还保留了 caller-side early-disable 路径，所以 Skip6 并不是所有路径都纯粹等到 DCT2 后才判断。

选定配置：

```text
LardLfnstSkip=6
LardLfnstThetaMinDeg=45
```

SJTU 4K 验证集 closed-loop：

| Stage-1 设置 | TS | Y-BDBR | YUV-BDBR |
| --- | ---: | ---: | ---: |
| 闭式 stage 1 | 7.77% | -0.037% | 0.014% |
| `ThetaMinDeg=45` | 8.50% | -0.055% | -0.007% |
| `ThetaMinDeg=30` | 6.59% | -0.055% | -0.007% |

AerialCity 冻结测试：

| 指标 | 数值 |
| --- | ---: |
| 三次均值 TS | 12.790% |
| Y-BDBR | 0.709% |
| YUV-BDBR | 0.701% |
| WS-YUV BDBR | 0.730% |
| CPP-YUV BDBR | 0.780% |
| byte delta | 0.261% |

final-CU 错误率：

| 判定跳过数 | anchor 最终用了 LFNST | 错误率 | matched final CU 跳过率 |
| ---: | ---: | ---: | ---: |
| 20,790 | 6,963 | 33.49% | 18.74% |

问题：

* 工程目标满足，但 final-index 错误率较高；
* 适合描述为速度-质量折中，不适合描述为严格安全分类。

### Skip7：低误跳 guarded lazy 版本

实现方法：

* 基于 Skip6 的 lazy quantized ROI；
* stage2 后增加 guard：
  * 大块允许；
  * 或 QP <= 20 且 intra mode 属于可靠模式；
* 不走 Skip5/6 的 caller-side pre-prune。

AerialCity 结果：

| TS | Y-BDBR | YUV-BDBR | byte delta |
| ---: | ---: | ---: | ---: |
| 1.394% | 0.012% | 0.0035% | 0.030% |

final-CU 错误率：

| 判定跳过数 | anchor 最终用了 LFNST | 错误率 | matched final CU 跳过率 |
| ---: | ---: | ---: | ---: |
| 5,236 | 673 | 12.85% | 4.72% |

问题：

* 错误率低很多；
* 时间收益太低，达不到 10%。

### Skip8：候选增益查表版本

实现方法：

* no-LFNST DCT2 后先做 quantized ROI gate；
* 如果 gate 通过，直接 `{0}`；
* 如果 gate 不通过，查 `LardLfnstCandGainTable.inc`；
* 查表 key 包含 QP、尺寸组、mode group、纬度桶、预测非零桶、last position 桶、ROI 能量桶、LF ratio 桶、相关性桶；
* 输出候选 mask，可为 `{0}`、`{0,1}`、`{0,2}`、`{0,1,2}`。

AerialCity 结果：

| TS | Y-BDBR | YUV-BDBR | WS-YUV | CPP-YUV |
| ---: | ---: | ---: | ---: | ---: |
| 3.169% | 0.357% | 0.348% | 0.344% | 0.376% |

问题：

* RD 还可以；
* 时间收益不足；
* 表很大，过拟合风险高。

### Skip9：mode-level skip + candidate-gain

实现方法：

* 在 Skip8 基础上增加 `LardLfnstModeSkipTable.inc`；
* 对特定 QP/尺寸/mode/纬度组合直接 local disable LFNST；
* 未命中 mode skip 时继续使用 candidate-gain 逻辑。

状态：

* 已实现；
* 未作为正式主结果。

问题：

* 对 final mode 分布依赖更强；
* 需要独立验证集确认。

### Skip10：second-response 模型

实现方法：

* no-LFNST 主变换后收集 LFNST 输入向量；
* 用 LFNST 矩阵传播候选输出方差；
* 用 maximum-entropy marginal rate bound 近似 rate；
* 加入 index rate proxy、失真项和 observed response gain；
* 输出 candidate mask。

AerialCity 一帧结果：

| 设置 | TS | WS-YUV | S-YUV | CPP-YUV |
| --- | ---: | ---: | ---: | ---: |
| `zeta=0.1, delta=0.25, ridx=1` | 7.587% | 0.613% | 0.522% | 0.687% |

问题：

* 计算比 Skip6/8 更重；
* trace/count/measure 模式会严重影响时间，不能直接当性能数据。

### Skip11：EffCols + covariance response

实现方法：

* 增加有效水平列判据：

```text
floor(width * cos(latitude)) < EffColsMin
```

* 再用 QP、面积、宽高、宽高比、shape mask、最低 DCT2 cost 等 gate 控制 second-response；
* 可启用相关性表 `LardLfnst2ndCorrTable.inc`。

状态：

* 已实现；
* 主要用于 response 模型探索。

问题：

* gate 参数多，调参空间大；
* 目前没有稳定证明跨序列 10% TS。

### Skip12：论文梯度 baseline

实现方法：

* 非 latitude baseline；
* 使用 primary transform coefficient 的边界梯度；
* 计算 `grad1` 和 `grad2`；
* 阈值为：

```text
TH1 = LardLfnstPaperGradTh1
TH2_l = scale * Qstep - offset_l
```

* 根据阈值跳过 LFNST candidate 1 或 2。

作用：

* 与已有 fast LFNST 思路做对比；
* 不是本文主模型。

### Skip13：Skip11 + paper baseline 融合

实现方法：

* 先走 Skip11 / second-response；
* 如果 response 没有有效裁剪，或配置允许 fallback，则使用 Skip12 梯度规则；
* 支持 score table 训练和候选预算扫描。

已知结果：

* trace-derived budget scan 中一个选中设置：candidate saving 36.14%，final-index error 6.18%；
* 一个 focused AerialCity closed-loop 测试：
  * TS 7.216%；
  * WS-YUV 0.377%；
  * CPP-YUV 0.427%。

问题：

* 部分表和评估来自 AerialCity，自身存在测试集调参风险；
* 可以作为探索，不宜作为最终泛化结论。

### Skip14：theory-space `{0}` skip

实现方法：

* 更接近论文理论链路；
* 使用低频有效水平支撑、方差传播、majorization、非零数、熵 proxy 等条件；
* 支持 ablation：
  * 0：full；
  * 1：support-only；
  * 2：majorization-only；
  * 3：non-zero-only；
  * 4：entropy-only；
* 支持 mode：
  * 0：hard AND；
  * 1：support-only；
  * 2：soft NZ + entropy protection；
  * 3：QP schedule；
* 支持 caller-side early disable、full ROI gate、proxy ROI gate、recall guard。

当前代码约束：

```text
LardLfnst14Mode 必须在 [0..3]
```

因此历史日志里如果出现 `LardLfnst14Mode=6`，不能作为当前代码的有效配置引用。

AerialCity 4 帧 stage/ablation 结果：

| Variant | TS | WS-YUV | S-YUV | CPP-YUV | 解释 |
| --- | ---: | ---: | ---: | ---: | --- |
| mode0 hard AND | 7.333% | 0.652% | 0.688% | 0.701% | 有速度，RD 损失偏高 |
| mode1 support-only | -5.264% | 0.045% | 0.042% | 0.044% | 安全但更慢 |
| mode2 soft NZ/rate | 5.439% | 0.637% | 0.731% | 0.673% | 中等速度，RD 接近上限 |
| mode3 QP schedule | same-run 6.012%，repeat median -0.026% | 0.357% | 0.386% | 0.341% | RD 好，但时间不稳定 |
| step2 majorization-only | 4.430% | 0.618% | 0.683% | 0.651% | 单独使用不足 |
| step3 NZ-only | -5.510% | 0.660% | 0.718% | 0.701% | 更慢且 RD 较差 |
| step4 entropy-only | -6.525% | 0.649% | 0.684% | 0.693% | 更慢且 RD 较差 |

hybrid / early ROI 观察：

* `hyb_B_q27soft1_q37soft1`：WS-YUV 0.375%，S-YUV 0.391%，CPP-YUV 0.352%，三次重复 median TS 2.17%，mean TS 4.94%；
* caller-side early-ROI proxy wide1：TS 2.25%，WS-YUV 0.353%，CPP-YUV 0.338%。

问题：

* 理论解释更完整；
* 在线开销大；
* 时间收益不稳定；
* 暂时不如 Skip6 适合作为工程主结果。

## 5. 按证据等级整理性能

### 5.1 高置信工程结果

Skip6 在 AerialCity medium 20 线程首帧测试中满足目标：

```text
TS > 10%
BDBR < 1%
```

这是当前最适合汇报为“快速算法效果”的版本。

### 5.2 低风险参考

Skip7 证明：如果强行降低 final-index 错误率，时间收益会显著下降。它适合作为保守版或风险下界，不适合作为目标 TS 版本。

### 5.3 机制实验结论

动机实验说明：

* ERP 纬度会改变残差频谱；
* 高纬水平高频比例和水平方向性下降；
* 但不能说高纬 LFNST 一定无效。

更严格的 full-RDO trace 显示：

* 条件在 LFNST 被测试的样本上，wasted RDO 比例从低纬到高纬下降；
* 正 LFNST RD gain 概率从 20.1% 增至 34.2%。

因此论文表述必须是：

```text
纬度改变 ROI 统计结构，必须结合量化 ROI / 候选收益证据裁剪；
不能简单说高纬直接关闭 LFNST。
```

### 5.4 多序列服务器结果

`server_results/other3840_ra_t20_f32_anchor_official` 中包含 DrivingInCity、DrivingInCountry、PoleVault_le，preset 为 faster/fast/medium/slow 的结果。

观察：

* BDBR 整体很小；
* 时间变化混合，有的序列/预设变快，有的变慢；
* official-anchor 对比中时间变化约从 -4.27% 到 +5.30%。

结论：

* 多序列泛化还没有证明稳定 10% TS；
* 当前最强结论仍然是 AerialCity medium 冻结测试。

## 6. 错误率定义

项目历史中存在两个错误率口径。

### 6.1 candidate-oracle 错误率

旧口径：

```text
预测跳过，但候选级 full-RDO oracle 认为 LFNST candidate 有收益
```

Skip6 旧结果约为 30.99% false skip among predicted skips。

### 6.2 final-CU 错误率

用户重新定义的口径：

```text
预测跳过，但 anchor 最终 RDO 选择了 lfnstIdx != 0
```

这是后续讨论“是否错跳原编码器最终采用的 LFNST”时应使用的口径。

AerialCity matched final-CU 结果：

| 版本 | 预测跳过 | 错误数 | 错误率 |
| --- | ---: | ---: | ---: |
| Skip6 | 20,790 | 6,963 | 33.49% |
| Skip7 | 5,236 | 673 | 12.85% |

注意：

* final-CU 总数 154,528；
* trace 匹配到 110,954；
* 覆盖率约 71.8%；
* 正式论文表格前应继续提高 trace join 覆盖率。

## 7. 当前存在的问题

1. **Skip6 是速度-质量最优点，但不是严格安全判据。** 它达成 10% TS，但 final-CU 错误率 33.49%。

2. **论文动机不能写成“高纬 LFNST 无效”。** 当前数据说明高纬频谱结构变化，但高纬 LFNST 正收益概率反而更高。

3. **Skip8/13/14 有过拟合风险。** 它们依赖大表或 AerialCity 派生结果，必须使用独立训练、验证、测试拆分。

4. **多线程时间收益不稳定。** 部分版本 RD 很好但 TS 为负，说明在线开销和线程调度影响明显。

5. **trace / measure 模式不能用于性能结论。** CSV 写入、final-stat、count 统计会显著改变时间。

6. **仓库中生成表和辅助文件很多。** 当前分支包含大尺寸 `.inc` 表、server migration 文件、部分 Python cache。后续正式发布前需要决定哪些保留，哪些移出仓库。

7. **历史配置和当前代码不完全一致。** 当前 `LardLfnst14Mode` 只允许 `[0..3]`，历史 mode6 日志不应当再引用为当前实现结果。

8. **final-CU error trace 覆盖不完整。** 当前匹配覆盖率约 71.8%，正式统计前需要补齐。

## 8. 后续建议

1. 工程主线继续使用 Skip6。
2. Skip7 作为低误跳参考。
3. Skip14 作为理论对齐和机制验证分支，不作为当前速度主结果。
4. 论文中分开写：
   * 工程性能：Skip6；
   * 低风险对比：Skip7；
   * 论文理论机制：Skip14 / controlled stretch；
   * baseline：Skip12；
   * 候选精细裁剪探索：Skip8/13。
5. 重新做完整训练、验证、测试拆分：
   * 训练：SJTU train；
   * 验证：SJTU validation；
   * 测试：AerialCity 和更多 ERP CTC 序列；
   * 不在测试集调参。
6. 改进 final-CU 和 candidate trace join，提升 final-index 错误率统计覆盖。
7. 建一个 artifact manifest，把每张论文表对应到具体 `lahtp_runs` 文件。

## 9. 关键溯源文件

已有文档：

* `docs/lard_lfnst_experiments.md`
* `docs/lard_lfnst_motivation_experiments.md`

关键结果：

* `lahtp_runs/aerialcity_final_4k_1f_medium_t20_skip6_theta45/aerialcity_final_skip6_theta45_t20_mean3_metrics.json`
* `lahtp_runs/aerialcity_final_4k_1f_medium_t20_skip6_theta45_recon/aerialcity_final_skip6_theta45_t20_ws_cpp.json`
* `lahtp_runs/aerialcity_low_error_skip7_lazy_4k_1f_medium_t20/skip7_vs_anchor_metrics.json`
* `lahtp_runs/aerialcity_final_decision_trace_anchor/final_cu_aligned_lfnst_error_rate.json`
* `lahtp_runs/aerialcity_skip8_qp_sweep_recon/aerialcity_skip8_metrics.json`
* `lahtp_runs/second_response_aerialcity3840_f1_lookup_ts_default/z0p1_d0p25_r1/metrics.json`
* `lahtp_runs/aerialcity_skip14_stages_steps_4f_t20_20260603/stages_steps_summary.json`
* `lahtp_runs/aerialcity_hybB_repeats_4f_t20_20260603/hybB_repeat_summary.json`
* `server_results/other3840_ra_t20_f32_anchor_official/compare_official_anchor_vs_proposed.csv`

由于大部分 `lahtp_runs` 输出被 `.gitignore` 忽略，本文档已经把关键数值写入报告，避免后续本地结果清理后无法回溯。
