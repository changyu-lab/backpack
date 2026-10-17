# VTM23 RC compatibility anchor

Isolated branch: `codex/vtm23-rc-anchor`. Base: official VVenC v1.12.0 `e9fa71223a3ffc2b35ed4026aea9cde1886cf6a9`. Native RateCtrl.cpp/h are unchanged. Compatibility is opt-in; public configuration struct changed, so rebuild SDK clients.

The separate `VtmRcCompat` kernel mechanically extracts the specifically hashed local VTM23 RateCtrl files. See [provenance.json](provenance.json): the local checkout contains modified call sites, and official VTM tag authentication remains pending. Replay proves local-file logic equivalence, not whole-encoder or official-tag identity.

## Build and use

```powershell
cmake -S . -B build-vtmrc -G "Visual Studio 16 2019" -A x64 -DVVENC_ENABLE_LINK_TIME_OPT=OFF
cmake --build build-vtmrc --config Release --parallel 4
bin/release-static/vvencFFapp.exe --preset faster -i input.yuv -s 256x192 -fr 30 -f 129 -b output.vvc --GOPSize=8 --PicReordering=0 --POC0IDR=1 --DecodingRefreshType=0 --IntraPeriod=-1 --VTMTargetBitrate=60000 --VTMRCTrace=rc.csv --Threads=0 --MaxParallelFrames=0 --IFP=0 --TileParallelCtuEnc=0 --Tiles=1x1 --WaveFrontSynchro=0 --WppBitEqual=0 --HrdParametersPresent=0 --SEIBufferingPeriod=0 --PerceptQPA=0 --BIM=0 --MCTF=0 --LookAhead=0 --STA=0
```

`VTMTargetBitrate` is bits/second, distinct from native `TargetBitrate`. `VTMKeepHierarchicalBit` defaults to 2. Explicit frame count and single-pass operation are required. QPA, native RC, parallel processing, tiles, lookahead, HRD/CPB signaling and competing adaptations are rejected. Threads=0 executes on the calling thread. Supported configured GOP sizes: 1,4,8,16,32; standard VVenC GOP definitions still apply.

The adapter initializes sequence/GOP/picture state, applies CTU QP/lambda before search, immediately supplies completed-tree CABAC estimated bits and selected-tree distortion/skip feedback, then debits actual picture NAL bits and headers at output. CTU bits exclude SAO/ALF in the same estimation path as VTM; picture actual bits close the final accounting. CSV records each begin/decision/feedback/picture with targets, remaining budgets and model state.

Separate CTU models are always enabled because the local upstream picture update dereferences their storage even when disabled. Zero total intra SATD and nonpositive remaining intra average budget are explicitly rejected before upstream undefined numeric operations; no fallback formula is substituted. This is a documented input-domain limitation. The default mode remains this independently controlled anchor. Optional SIBRC redistribution is documented in tools/sibrc/README.md; its initial screening did not achieve BD-rate gain (docs/sibrc/initial-screening-20261010.md).

## Validation, 2026-10-09

- CTest: 39/39 passed; CLI/config/order tests passed.
- Independent original-source replay: 4,200 records, 13,192 fields across eight scenarios; integers exact, floating abs 1e-12 / rel 1e-10. Deliberate divergences rejected. Mechanical extraction audit and reference SHA256 passed.
- RA GOP16 (19 frames) and GOP32 (35 frames) tail flush passed. Constant intra/1bps inputs reject explicitly.
- Native fixed-QP and native single-pass RC produce bit-identical streams to the preserved official anchor on a 17-frame fixture.
- 256x192 synthetic motion texture, 129 frames, 30fps: four-rate closed loop, ordered feedback and budget debits passed. Decoder output equals encoder reconstruction. Repeated 240kbps trace/bitstream hashes match; RD is monotonic.

| Target kbps | Actual RC kbps | Error % | Y PSNR dB |
|---:|---:|---:|---:|
|30|30.0167|0.0558|31.8299|
|60|60.1786|0.2977|34.6645|
|120|120.0949|0.0791|38.1770|
|240|240.3181|0.1326|43.7903|

RC bitrate counts picture NAL bits; Annex B file bitrate additionally includes start codes and signaling. Remaining CTU/picture budgets can become negative, as in the original controller; these are traced rather than clamped. This short synthetic test does not establish general long-sequence convergence or strict HRD buffer compliance. Full commands, QP/lambda ranges and hashes: [smoke-report.json](smoke-report.json).

Reproduce core checks with `test/vtmrc/README.md`. Run CLI/closed-loop tests with `VVENC_VTMRC_EXE` set to the executable. Run `python tools/vtmrc/smoke.py --encoder bin/release-static/vvencFFapp.exe --decoder <VVC DecoderApp.exe>`; numpy is required. Generated artifacts stay under ignored build directories.
