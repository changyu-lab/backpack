# 附件 strip 间预算 + SIBRC strip 内优化

2026-10-16。用户提出新分层结构；本文固定可执行接口及首轮试验。状态：用户已确认实施；首个实验改为AerialCity四点，随后是否扩展依据其结果判断。原混合实验和两种独立方法保持冻结。

## 上一轮为何不能回答本方案

旧协同先以alpha混合两个CTU目标，再让冻结SIBRC在当前CTU至帧末搜索全局价格，受全帧剩余预算约束。strip没有作为SIBRC优化范围或预算约束。因此它没有实现用户指定的strip间/strip内分工。原16点的负结果只针对软CTU目标串接。

## 选定结构

一条strip是一行CTU；4K 3840x1920、CTU128时每条30个CTU，共15条。以下全部采用真实编码顺序，不引入额外编码slice或tile，也不改参考关系。

1. 帧级预算、初始pictureQP/lambda继续由原VTMRC产生。
2. 每条strip开始时，依现有附件移植的特征/纬度公式，从当前真实frame_left计算strip_target：frame_left * 当前strip特征和 / 未编码全部strip特征和 * 当前strip纬度因子 / 全图strip纬度均值。零特征使用现有像素回退。第一轮不同时改成另一套归一化公式。
3. 明确保存strip_begin、strip_end（末端不包含）、strip_target和strip_left。strip边界只重建行预算，不重置帧内SIBRC预测校正状态。
4. SIBRC候选集合只覆盖 [current_ctu,strip_end)，约束改为strip_left；全帧剩余预算继续负责VTM反馈和下一条strip预算来源。不得仅将全帧budget换成strip_left而仍预测到帧末，这会造成量纲/范围不一致。
5. 去掉alpha混合。保留附件现有strip内特征比例生成CTU的初始target，用其得到VTM基准QP/lambda；SIBRC在当前strip余下CTU上以原C4模型进行率失真优化并决定最终动作。该CTU比例仅作为参数初值，不作为绕过SIBRC的最终决定或每CTU硬约束。
6. 第一轮保留冻结I/P模型、统计、beta5、动作范围[-2,+2]及I帧QP反馈合同。未来CTU基准仍采用冻结SIBRC的pictureQP近似，明确这是可达性风险，先测不可达比例，不同时改模型/动作范围。
7. 每个CTU完成后，同一真实bits分别更新frame_left、strip_left及SIBRC校正一次。strip_left=strip_target-本strip累计真实CTUbits，不按alpha缩放，不将strip预算再次从frame预算扣减。
8. 行末不将结余人为补花，也不凭空归零全局差额；实际全帧余额已包含本行欠支/超支，下一行按原公式重新分配，完成跨行补偿。不能在所有strip开始前固定分配预算后忽略真实反馈。

## 预算可达性与失败处理

该方案只约束预测比特，真实编码比特无法由离散QP动作保证精确等于strip预算。原附件行公式的纬度因子不保证每一步预算都在未来CTU可达区间内；不可对用户宣称数学硬预算保证。

每次记录候选最小/最大预测剩余率、strip_left、fallback原因（负预算、预测无效、低于最低可达率、价格搜索失败）。不把strip_left裁剪后静默当作满足原分配。先保留冻结SIBRC回退动作及所有质量结果。

如果大量不可达或仍无增益，另做有标记的第二方案：先将strip目标投影到合法动作的可达率区间，并保留全帧预留约束。这会改变原strip分配，必须单列为协同扩展，不冒称原方法公式未变。

## 三种路线的取舍

- 首轮采用上述严格限制搜索范围的分层方案，直接检验用户提出的结构；改动小，且两种机制职责可观察。风险是原strip目标与±2动作不匹配。
- 可达预算投影：增强稳定性，但必须评价对附件条带先验的削弱，单独做消融。
- 扩大/重定位strip基准QP：可能提升预算可达性，但涉及lambda映射、I帧反馈合同及模型外推，暂不与首轮混用。

## 隔离及验证

新独立分支codex/gaze-sibrc-strip-local，从已归档协同分支创建新工作区；保留原SIBRC、原条带、alpha混合三个路径及归档结果。新显式模式控制strip-local路径，默认关闭。Controller增加有界end参数，默认仍帧末，不能修改原模式语义。

- 单元：范围只含本strip；下一strip特征不影响本次搜索；预算扣减一次；行末余额传播；预测校正跨行保留；边界/零特征/负预算/不可达原因覆盖。
- 回归：新模式关闭时原Anchor、G-only、S-only及alpha0代表性码流SHA一致；原混合配置继续可重现。
- 生效：strip_target随特征/纬度变化；SIBRC存在真实非零动作；trace显示预测范围严格等于当前strip余下CTU、budget==strip_left。不能只修改日志。
- 首轮：DrivingInCity、DrivingInCountry，RA GOP32、实际32帧、refs1，冻结四目标、旧sphere/metrics/models，合计8正式点；不进行alpha搜索，不重跑全套Anchor。原始码流、完整trace、独立解码、四指标和失败点均保存。
- 汇报：逐序列四指标BD-rate对SIBRC、两序列全平均、真实码率误差、strip预算偏差/可达率/fallback、I/B帧及纬度比特与质量转移。
- 晋级：两序列各项平均BD-rate不高于SIBRC、两机制真实起作用且码率误差可接受，才固定方案做14序列验证。不能保证一定有增益。

用户已确认预算与结余规则，实施计划见 plans/2026-10-16-strip-local-sibrc.md；本轮先实验AerialCity。
