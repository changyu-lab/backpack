# M4 频率权重对照设计与实施计划

> For agentic workers: 经用户批准后按 executing-plans 逐项实施。本文件为只读审查结果及待审批方案；本次未修改编码器、未编译、未启动编码。

**Goal:** 在保留相同几何支撑 chi_b、球面目标方差估计 sigmaY²、控制器和反馈协议的条件下，比较五种频率权重，并为每个描述量独立重拟合 I/P 的 R/D 模型。

**Architecture:** 在预分析唯一频率权重入口增加 selector；收集模式一次输出全部描述量，使所有模型共享完全相同的编码样本与标签。运行模式选择单个描述量及其匹配模型；开发集确定协议后冻结，再在独立验证序列做四点比较。

**Tech Stack:** 现有 C++ SIBRC / VtmRcCompat，Python NumPy/SciPy calibration，原 360Lib metrics。

## 1. 审查依据与已确认事实

ROOT = `C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST`。已读 ROOT/AGENTS.md；按其要求默认报告 WS-PSNR、S-PSNR-NN、CPP-PSNR，普通 Y-PSNR 仅辅助。设计采用 brainstorming 与 writing-plans 技能，用户指定本文件位置并要求 root 统一审批，故此处不额外提问或提交代码。

- `source/Lib/EncoderLib/Sibrc/Controller.cpp:20-23` 的 ibWeight 实参是 **r=rho²**，函数局部名 rho 容易误读；头文件声明使用 rhoSquared。`tools/sibrc/calibrate.py:22` 计算 cov²/(vx*vy)，Stats 文件字段名也是 rho2。
- 当前 T(r)=0（r<=1/beta）；否则 T(r)=0.5*log2((1-1/beta)/(1-r))。beta 在 `Statistics.cpp:33` 硬编码为 5。它是最优目标相关互信息 I(T*;Y)，不是 I(T*;X)、不是 gamma*。
- `Statistics.cpp:16-18` 先按纬度对 r 与 gain **分别线性插值**，随后计算 T；不能先对节点 T 插值来替代。纬度越界采用端点；统计网格为 0/15/30/45/60/75/85 度。
- sigmaY² 代理为 residual variance * covarianceDiag[rh][u] * covarianceDiag[rv][v] /1024 * gain。rh/rv 由邻域残差相关估计，截到 [0,.99] 后量化到 .01；gain=vy/vx，标定截到 [0,1000]。chi 是 u < max(1,round(32*cos(latitude)))。保留这些细节，尤其高纬 support 的最小值 1。
- 32x32 residual 采用 8-bit 归一化；P 用第一 L0 重建参考的小范围整数 SAD 搜索，I 用常数128预测；CTU 内块信息取算术平均。论文中的块重数 m_b 没有独立代码权重，本轮不新增，以避免改变问题。
- `Preanalysis.cpp:23-24` 的残差 dump 每16个块抽一个，文件只有 residual 值，没有 POC/CTU/latitude 索引；现有 trace 只存 C4=ieff。故现成 residual 与 trace **不能直接重建逐 CTU 的 C0/C1/C2/C3/SATD**，不得从既有 C4 反推其他权重。
- `Controller.cpp:43` 与 calibrate.features 同用 [1,x,z,xz,z²,x²]，x=(QP-4)ln2/6、z=ln(max(info,1e-12))。R 标签 ctu_bits；D 标签 spherical_weighted_mse，预测后乘 sphereArea 转 SSE。每描述量必须重拟合，不能直接复用现有 C4 模型。
- 附件 `.../chapter5_SIBRC_TIP.tex:168` 明确 r=rho²，239-242 的 T 与代码相符；书稿公式需显式给出激活条件，否则低相关区得到负 T。263-265 给 chi*sigmaY²*T，且包含未单独实现的 m_b。附件已有数值表与结论不视为本项目实验结果。

## 2. 五权重与 C2/C3 等价边界

统一描述量 F_j=CTU块平均(sum_b chi_b*sigmaY²_b*C_j(r_b))，固定 beta=5：

| selector | 频率权重 | 含义 |
|---|---|---|
| C0 | 1 | 同几何支撑的球面目标能量基线 |
| C1 | r | 连续相关性权重，无 IB 激活阈值 |
| C2 | max(5r-1,0) | 激活后线性权重 |
| C3 | 1-exp2(-2*T(r)) | 有界目标相关性保持比例 |
| C4 | T(r) | 当前实现，激活后对高相关频率对数增强 |

激活区 exp2(-2T)=5(1-r)/4，因此 C3=(5r-1)/4=C2/4；未激活区二者为0。共享 sigmaY²、chi 与块平均后 F2=4*F3。C2/C3不是两种独立频率形状，任何结果报告必须说明这一点。

**数值检查不可省略：** 统计生成 r cap=.999999，ibWeight 同样 cap，但加载器接受 .999999<r<1；若 C2 用未 cap 的 r、C3 用 cap 后的 T，等价会破坏。统一 selector 在插值后先 cap r 到 .999999，再计算所有权重，默认 C4 无变化。gain cap、协方差截断、support rounding 本身不会破坏等价，只要共享相同数据；阈值附近浮点误差需做绝对容差检查。切勿把“对权重节点插值”与当前“先插值r再非线性映射”混用；C4 非线性，C2/C3 又有阈值 kink。

无正则、无 floor 干扰时 ln(F2)=ln(F3)+ln4，二次模型可通过参数变换吸收常数。但现有 feature RMS scaling + ridge penalty、固定1e-12 floor、有限精度和单调域会破坏拟合过程的尺度不变性，在线反馈可能放大已有预测差异。因此不能自动声称两个完整编码路径完全一致。

推荐：**保留五个 selector 和五套独立拟合资产**；C0/C1/C3/C4 做完整四点编码，C2 先做 F2/4 与 F3、拟合预测及 controller decision replay；只有 replay 差异不能解释为数值误差时才做 C2 四点编码。这样满足五权重独立标定，同时避免把代数重复误作新增证据。若用户希望五者全部编码，也可执行，但结果须标注 C2/C3 等价对照。

## 3. 训练资产及覆盖缺口

已存在：

- ROOT/docs/sibrc/calibration-v1/{stats.txt,model.I,model.P} 及 JSON；README 记录每开发序列4帧统计、16帧 R/D，QP22/27/32/37。
- `I:/vvenc-LFNST/.worktrees/sibrc-experiment-data-20261009-v2/development_residual.bin`，29,491,200 bytes，即3600个32x32 float64块；来自两个开发序列每16块抽样。
- 同目录 `development_samples.csv` 与 `extended_development_samples.csv`；后者包含 QP17..52 扩展（已有 collect_extended run JSON）。现有 full-lat model.I JSON train=3600/holdout=3600，训练 QP域17..52；其 holdout 只有 DrivingInCountry POC0，说明每序列只有一个 I picture，I 泛化证据很弱。
- `I:/vvenc-LFNST/.worktrees/sibrc-full-lat-dev-20261010/model.{I,P}` 与 sidecar 使用全纬度、monotonic、显式域 QP[-12,63]/info[1e-12,100000]；P holdout 是词典序末尾图片，不能作为充分均衡的独立测试。

现有统计可冻结复用，五权重不重新估计 r/gain；但旧 scalar trace 不足以同样本重拟合五描述量。最小采集方案是**复刻已有开发 collection命令**，只新增多描述量 sidecar，QP/输出编码字节应与旧 collection 一致；同一编码一次产生五列标签匹配特征。已有所有QP的recon若完整存在，也可读原始+参考重建离线复刻预分析，但该路线需增加重建管理与边界一致性审查，不推荐优先。

推荐正式 M4 标定覆盖：DrivingInCity、DrivingInCountry，每序列4个不重叠16帧窗口（起点0/64/128/192，使用同起点原始帧且各窗口独立初始化，使每序列有4个I样本组），QP17/22/27/32/37/42/47/52；每个窗口全纬度；同一模式2采集一次输出五权重+额外参照。此为待批准新编码预算，不在本次执行。若预算受限，先复刻旧16帧×8QP作为开发诊断，不能据此宣称 I 模型已充分验证。

## 4. 最小实现边界（待批准）

- `Controller.h/.cpp`：保留 ibWeight；新增 enum class FrequencyWeight { C0,C1,C2,C3,C4 }; 新增 frequencyWeight(r,beta,selector)，共享有限性/clip处理；switch 五公式。默认 C4。
- `Preanalysis.h`、`Statistics.cpp`：新增返回 std::array<double,5> 的 allInformationFromResidual；一次估计 variance/rh/rv/support，频率循环内共享 energy，再分别累加五权重。旧 informationFromResidual 委托 C4，保持调用兼容。Features 保留 information/area，新增 allInformation、satd、geometricEnergy；控制时 information 由selector选择。
- `Preanalysis.cpp`：同一 residual 计算全描述量；collection才需要全量 sidecar，控制默认只用所选量以限制开销。C0就是 masked spherical target energy，不应给它额外 cos(latitude) 乘子。
- `include/vvenc/vvencCfg.h`、`source/Lib/vvenc/vvencCfg.cpp`、`source/Lib/apputils/VVEncAppCfg.h`：增加 SIBRCFeature=0..4，默认4，校验范围；以显式模型前缀关联对应资产。增加输出列selector/feature schema，禁止无匹配元数据模型被悄然用于其他描述量。
- `source/Lib/EncoderLib/VtmRcCompat/Adapter.cpp`：analysePicture传selector；原trace保持兼容，额外 CSV 以(source_sequence,window_start,poc,ctu,run_id,requested_qp,actual_qp,kind)键写五值及参照，与 bits/weighted_mse/area 连接。记录实际QP；若requested/actual不同，同协议用实际QP建模并保留偏差统计。
- `tools/sibrc/calibrate.py`：增加 --feature-column 和 --split-manifest；输出sidecar记录 selector、beta、stats SHA、训练键SHA、split SHA、标准化参数、筛选原因。模型数值文本继续 V1以保持预测器；使用loader sidecar强制匹配selector/normalization。若规范化需要运行期参数，不把它隐式只放在JSON：必须升级模型格式/loader或代数折回原z系数。

## 5. 公平拟合协议

- 全描述量使用完全相同 source/window/POC/CTU/QP 行与正 bits/MSE 标签；不得每个模型按自身表现删样本。F=0保留并记录，统一floor策略。统计资产、variance、chi、gain均冻结。
- split 单位是 (source_sequence,window_start,local_poc)，全部QP与run同组；每序列每窗口分层，固定manifest，保持I/P两类均有train/holdout。四窗口方案建议每序列窗口192全部holdout、前三窗口train；窗口之间参考链独立，避免连续P参考污染。QP不是随机行拆分单位，不能把同一图片不同QP跨train/holdout。
- I/P分别拟合 R 与 D，六基函数、ridge=1e-6、单调约束、全纬度90°、误差输出与模型容量保持一致。QP支持域预注册；开发数据支持17..52以外预测记外推，不因控制器可取-12..63就声称验证覆盖。
- 主协议对每描述量采用训练集正值 geometric mean 的尺度标准化 F'=F/s_j，然后统一floor=1e-12。C2/C3所得尺度差4，因此标准化后应等价（近floor需检查）；训练与运行共同应用该常数，holdout不能重新估尺度。所有模型仍独立拟合。若保持V1，将z'=z-ln(s_j)展开后把系数代数折回z，且floor必须采用 raw floor=s_j*1e-12；这需要新增模型floor字段，不能继续loader硬性1e-12。更清晰选择V2记录 scale/floor并执行相同z变换。
- 另存兼容诊断：沿用现有 raw-log+RMS+ridge 协议重拟合五模型，仅用来解释C2/C3是否受尺度影响，不混入主结论。
- 特征矩阵 RMS scaling 或z均值/方差的统计仅从train求，I/P分别求；统一规则而非强制不同描述量用同一数值尺度。单调域在标准化坐标中按相同预注册规则生成，不能保留同一个raw info上界100000造成不公平。
- --refit-all 若启用，五者全部同样启用，先冻结held-out diagnostics；refit后指标只描述pre-refit模型。推荐首轮不refit，保留真正开发holdout；最终冻结版本若refit则独立验证集承担验证职责。

## 6. SATD/几何能量参照与结果B/C解释

额外参照不是五权重中的替代公式，单独列出并各自重拟合 I/P R/D：

1. 平面 residual variance E_plane（同去均值32x32样本）。
2. E_geo=cos(latitude)*E_plane；说明它是简单面积权重能量，避免与C0=chi*sigmaY²混称。
3. SATD_plane：同预分析 residual，以现有8x8 Hadamard SATD内核逐8x8相加/1024；固定DC是否保留、缩放及8-bit归一化，文档与单元检查一致，不调用最终RDO residual作先知特征。

支持B：同内容受控拉伸开发诊断，比较描述量随纬度变化、与实际bits/weighted_mse及边际RD响应的关联，并报告分纬度held-out logRMSE。支持C：完整独立序列实际码率四点BD-rate证明控制效果。相关性/训练RMSE、C2/C3重复或仅City曲线均不能替代C证据；若C4未稳定优于C0/C1/C3，报告“未证明对数IB权重优势”，不能只挑支持的序列/指标。

## 7. 验证顺序与验收

- [ ] 权重数值检查：r=0,.2±1e-12,.5,.9,.999999及加载边界；C2=4*C3（abs<=1e-12），C4与旧ibWeight结果一致；中间纬度14.5/37.5/84/89.9用真实Stats检查。残差constant、impulse、随机/强相关块检查零方差及有限性。
- [ ] collection兼容检查：selector C4新旧信息误差<=1e-10*(1+abs(old))；新增诊断不改变QP、lambda、bits及bitstream SHA。先做一组极短开发smoke，未通过不启动批量。
- [ ] 多描述量键及标签检查：五模型行集SHA完全一致，无重复键；split无跨QP泄漏；I/P train/holdout均有多图片组；元数据不是stats的frames=4误用为模型帧数。
- [ ] 独立拟合后保存训练/holdout R/D logRMSE、分纬度/分QP误差、monotonic违反数、zero/floor计数、域外比例。C2/C3标准化feature、预测值及controller动作replay；差异报告不能省略。
- [ ] 开发集固定offset范围、模型协议和超参数；不随独立验证集成绩调整。Root正在进行的冻结exe DrivingInCity offset实验仅属开发诊断，M4实现不得覆盖其exe或资产。
- [ ] 独立验证集固定 AerialCity / PoleVault / BranCastle2，300帧，已有协议的LDP、更快preset、严格串行VTM adapter；四个共同target bitrate，用同配置anchor；同一序列不同selector共享target而最终BD用实际bitrate。DrivingInCity和DrivingInCountry只能标“开发集”。这三序列已有历史结果，因此称“独立于标定的验证集”，不要称完全未见过的盲测试。
- [ ] 每序列报告三项球面metric分别BD-rate、实际/目标码率误差、逐帧质量/码率、fallback和offset分布、外推率、时间开销。固定metrics360球面采样、投影及代码hash；避免新增特征计算成本误归到控制器。

## 8. Root统一审批的具体范围

推荐审批包：五selector实现及同样本sidecar；冻结现成stats；两开发序列4窗口×8QP共同采集；训练集尺度标准化V2（默认C4兼容路径保持V1读取）；五套独立I/P R/D；SATD/几何能量独立参照；C2/C3数值replay后按判据决定C2额外编码；C0/C1/C3/C4及参照在三独立验证序列做300帧四点；任何结论按真实结果写。更省预算方案复刻现有16帧开发采集先做诊断，但I模型不足以支撑强泛化结论。完全离线方案需所有参考重建与多描述量重建一致性验证，工程复杂度更高，不推荐。

本次唯一写入为此计划文件，源代码、冻结exe、论文、训练资产均未修改。
