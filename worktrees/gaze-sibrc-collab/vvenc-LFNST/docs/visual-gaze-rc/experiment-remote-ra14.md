# 远端 RA32 / 14序列 / 17帧

2026-10-14 用户授权在其SSH服务器执行RA配置14序列通测。
主机 `rycpu2.9gpu.com:36016`；凭据不保存到仓库、脚本或实验记录。
独立目录：`/root/visual_gaze_ra17_20261014`，未修改已有项目或原始视频。

## 协议

- 沿用当前通测的模式0原VTMRC与模式1仅条带、QP22/27/32/37四目标、前17显示帧。
- 原始4K/6K/8K及8/10bit输入；CTU128，内部/输出10bit，faster preset。
- RA采用平台原生GOP32、PicReordering=1、POC0IDR=1、IntraPeriod=32、DecodingRefreshType=1。
- 17帧短于GOP32，属于部分GOP快速实验，不等同论文100帧稳态RA验证。
- 各目标来自同Linux编码器固定QP输出文件码率。平均BD-rate对全部14序列等权，任何缺失或无效曲线时不生成完整average。
- 每个RC码流独立VTM解码核对重建哈希，模式1最低目标重复检查。合计168次主编码及14次重复检查。
- μM=μS=1，条带方案与本地一致，不增加测试集调参。SIBRC比较仍需相同平台/长度/设置的独立基准。

## 资源与来源

远端32逻辑核、约47GiB物理内存，初查可用约45GiB；磁盘可用约14GiB。
原始源位于 `/data/360seqFull_17f/`，该目录名称虽有17f，文件实际长度足够32帧；只编码前17帧。
14序列的前17帧SHA与本地特征生成时的源前缀SHA全部一致，特征文件及μ/几何/search亦核对。
上传的是已验证特征、球点与源码；没有上传大体积原始视频。

源码基于独立分支提交e84f176，C++源码未修改，Python使用本次已验证overlay。
远端GCC Release构建成功，40/40 CTest通过。
17帧RA小尺寸四目标、模式0/1共8个RC点全部解码匹配，最低目标重复一致。

三个序列worker，每序列两个QP worker，共六路独立串行编码。
重建/解码原始YUV放入 `/dev/shm/visual_gaze_ra17_20261014`，验证后删除；
按最大8K、10bit输出每任务两份17帧重建预留容量，并检查内存盘余量。
每次run_experiment使用唯一临时目录，避免并发同名文件冲突。
OMP/BLAS线程固定1；并发wall time不能解释为算法复杂度增益。
评估源哈希覆盖实际评估的YUV420前缀，避免每个点重复读取未编码尾帧。

## 运行与恢复

远端构建、CTest、Python验证日志分别为 `build.log`、`ctest.log`、`python-tests.log`。
启动身份及PID保存在 `launch.json`，命令保存在 `command.json`，总日志为 `ra-batch.log`。
汇总：`results/summary.json`；每序列命令、指标、CSV、码流及日志在 `results/<sequence>/`。
正式任务以独立进程会话启动，SSH连接关闭后仍可运行。
按完整序列恢复，恢复前重新校验源/特征及码流/trace哈希；依赖变化时拒绝混用旧结果。

```bash
cd /root/visual_gaze_ra17_20261014/src
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 tools/visual_gaze/remote_ra.py \
  --sequences /data/360seqFull_17f --inputs /root/visual_gaze_ra17_20261014/inputs \
  --encoder /root/visual_gaze_ra17_20261014/src/bin/release-static/vvencFFapp \
  --decoder /root/ra14_tau_dev_20261003/bin/DecoderAppStatic \
  --sphere /root/visual_gaze_ra17_20261014/sphere_655362.txt \
  --output /root/visual_gaze_ra17_20261014/results \
  --scratch-root /dev/shm/visual_gaze_ra17_20261014 --sequence-workers 3 --qp-jobs 2
```
