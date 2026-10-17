# Three additional ERP sequences: experiment execution plan

Goal: repeat the frozen AerialCity 300-frame experiment on PoleVault (3840x1920), BranCastle2 (6144x3072), KiteFlite (8192x4096), native 8-bit ERP at 30fps. These sequences are absent from the frozen model's DrivingInCity/DrivingInCountry development set.

- [ ] Freeze encoder/config/model.I/model.P/stats and original 300-frame source hashes; cache source on SSD without scaling.
- [ ] Validate native-resolution command generation and small encode/decode/metric pilot on each resolution.
- [ ] Encode four CQP points 37/32/27/22 per sequence, round complete Annex-B bitrate to integer targets.
- [ ] Encode four anchor and four SIBRC full I/P points per sequence with identical frozen RC/coding settings. Keep sequential CTU feedback, QPA/nativeRC/WPP/tiles/frame parallelism off. Parallelize independent runs with memory-aware limits.
- [ ] Verify 300 POCs, source and asset hashes, actual stream bitrate and SIBRC intra safety contract.
- [ ] Independently decode each RC stream to SSD, compute official WS/S-NN/CPP luma metrics and ordinary Y diagnostic, record per-frame arrays and metric provenance, remove validated temporary reconstruction.
- [ ] Compute three independent four-point BD-rates using actual bitrate and common-range PCHIP; retain ordinary Y result and rate errors.
- [ ] Export 2400-row CSV per sequence, report and eight separate compact panels: four-sided axes, inward ticks, transparent, no grid, minimal margins, legend exactly anchor/SIBRC. Preserve all frames, bitrate log axis. Validate PNG alpha/DPI/layout.
- [ ] Aggregate the four sequences including existing AerialCity, archive reports and scripts in isolated project. Means only from completed sequence results; no favorable-sequence selection or model retuning.

Execution cache: D:/SIBRC-cache-20261010 (SSD on same physical disk as C); results: I:/vvenc-LFNST/.worktrees/sibrc-three-300-20261010. One decoded 8K stream at a time (~30.2GB), source cache ~26.9GB total. Serial sequence stages with independent encode jobs in parallel; 4K max4, 6K/8K initially max2 pending measured memory. Evaluation one stream at a time with native frame-worker limits 3/2/1 for 4K/6K/8K.
