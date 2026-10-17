# 与 SIBRC 线程匹配的 RA32 / 实际32帧重跑

2026-10-15 用户明确要求沿用隔壁线程实验参数，复用 Anchor，仅重跑14序列复现方法。
此前 RA32/17帧与本次实验不同，不混用数据。目标是同条件比较，不根据测试结果调整方法。

## 冻结条件和比较范围

参考资料来自对话“建立 VTM23-RC 独立兼容层”及其已保存的命令/运行/质量记录。
冻结远端基准：`/data/vtmrc-vvenc-ra32-20261014`。
逐点克隆 `runs/<sequence>/anchor/R{1..4}.run.json` 中完整 command，
仅替换编码器路径、输出/trace路径，加入 VisualGazeMode=1、特征文件和重建输出。
原始输入路径、实际32帧、fps、8/10bit、内部10bit、preset、参考配置和目标均原样保留。

`ra.cfg`：GOPSize32、PicReordering1、POC0IDR1、IntraPeriod32、DecodingRefreshType1、
CTU128、NumRefPics1、NumRefPicsSCC0；QPA/BIM/MCTF/LookAhead/STA关闭，VTMRC严格串行。
R1–R4为隔壁线程低至高目标，不再对应本线程17帧的QP档位。
不生成新CQP目标，不重跑正式56点Anchor，仅新增模式1的56个方法点。
32帧仍是POC0–31的窗口，按冻结RA32配置运行；要求日志完整覆盖32POC并含I/B帧。

原VTM数值内核源码相同不能单独证明二进制平台等价。因此增加四个模式关闭的兼容性检查：
DrivingInCity、AerialCity、Balboa、ChairliftRide各R1码流必须与旧Anchor SHA完全一致。
这是4K/6K/10bit8K代表点的经验门槛，不声称验证了全部源和全部目标的二进制等价性。
已单独核实 DrivingInCity R1：SHA为 `d2e2c1fd34b5f2ed7c401da7a523c5a831b5466fb2bc79b8930ab6b6c60a8eb9`，完全一致。
其余兼容性检查通过前，正式方法任务不会开始。2026-10-15已核对四点全部通过，
完整门槛摘要及启动身份见 `matched-ra32f-provenance.json`；正式队列已进入32帧特征生成。

## 来源及指标核对

每个旧Anchor须通过原32POC/RA验证，核对全部输出哈希、quality与bitstream、sphere/native metric身份。
每个源重新计算前32帧哈希，与冻结source_prefix_sha256一致。
重新预分析全部32帧，μM=μS=1，保持此前自适应Canny和前显示原帧运动搜索约定；不把17帧特征改头伪装成32帧。
特征metadata记录实际分析的YUV420帧前缀SHA，避免长源文件尾帧导致缓存失效。

每点独立解码并核对完整32帧重建SHA；PSNR/WS/S-NN与此前口径一致。
S-NN逐帧与隔壁使用的同一原生metrics360工具交叉核对，最大差必须≤1e-8dB，
并使用该工具计算CPP-PSNR。原生数组必须各含32个有限值。
各项BD-rate仅以旧Anchor实际文件码率和质量为基准；完整average要求全部14序列全部指标有效。
保存全部正负结果，不剔除困难序列，不将并发耗时称为算法复杂度收益。

## 资源、恢复与路径

新目录：`/root/visual_gaze_ra32f_matched_20261015`，不修改隔壁源、配置、Anchor、CQP或模型。
最多6个worker；另有24GB预留上限及实际available内存门槛，并计入编码器和两份原始重建。
32帧8K每份重建约3.22GB，最坏预算限制同时运行的8K任务数。
原始重建放 `/dev/shm/visual_gaze_matched32_20261015` 的唯一临时目录，验证后删除。
本任务trace在成功后gzip并记录压缩前/后哈希；仅删除本任务原CSV。
磁盘不足800MB时等待，不盲删其他任务的数据。
已完成点逐个核对SHA后复用，失败/不完整点重新生成；完整批次身份变化时拒绝续用。

检查点：`results/manifest.json`、`results/compatibility-approved.json`、`results/summary.json`。
日志：`tests.log`、`pipeline.log`；启动信息：`launch.json`。
每点：`results/<sequence>/R*.result.json`，序列报告：`results/<sequence>/report.json`。
独立进程会话运行，SSH断开后继续。密码不写入文件或仓库。

## 验证

本轮本地17项Python测试通过。远端首次测试因独立目录缺少测试cfg被阻止启动，
补齐测试配置后重验；正式RA配置始终使用冻结基准文件，不受测试cfg影响。
远端重验17项全部通过。
脚本评审已核对命令克隆、资源预算、PoleVault别名、gzip与逐点恢复和average规则。
