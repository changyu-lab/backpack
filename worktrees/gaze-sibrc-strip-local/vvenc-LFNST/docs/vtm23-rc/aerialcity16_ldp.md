# AerialCity ERP16 LDP validation

Status: VVenC four points complete. Same-input VTM four-point16frame reference is running; full paired effect comparison remains pending.

Input: I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv, first16frames,3840x1920,30fps,8bit420. Internal/output10bit. Encoder built at dbdf602; no production coding changes in this experiment.

Explicit VTM P-frame GOP8 reference lists, all TId0, CTU128. Threads0,frame parallel0,IFP0,WPP0,single tile/slice. NativeRC,QPA,MCTF,BIM,STA and lookahead disabled. VVenC preset faster; VTM uses its complete LDP coding tool configuration.

Targets: VTM-23.0/paper_evidence/config.json suites.core.targets.AerialCity:1.6/3.2/6.4/12.8Mbps. The frozen source table uses32frames; these runs use16. Historical16frame CQP-derived targets and4432x2216 resampling are excluded from this paired original-resolution experiment.

## VVenC closed loop

| Target Mbps | Actual RC Mbps | Error % | Mean Y PSNR dB | Mean Y WSPSNR dB |
|---:|---:|---:|---:|---:|
|1.6|2.417235|+51.077188|35.467962|34.701429|
|3.2|3.283140|+2.598125|36.016283|35.280671|
|6.4|6.404025|+0.062891|39.014506|38.314404|
|12.8|12.805350|+0.041797|39.980841|39.315712|

Each point:16pictures,7200 ordered CTU decisions/feedbacks; picture/sequence debits checked. All four streams decode to exactly the encoder reconstruction. Repeated6.4Mbps bitstream and CSV SHA256 hashes match. PSNR is the mean of16picture PSNRs; WSPSNR uses ERP cosine latitude weights.

## Actual-input kernel replay

Independently calculate first-frame Walsh SATD, preserving8x8 rounding, CTU accumulation and10bit-to8bit normalization. Supply identical actual CTU bits,QP,lambda,skip,MSE to separate programs linked against original local VTM RateCtrl and compat kernel. Compare both outputs and live encoder CSV decisions.

Four points:1800 actual CTUs,7208records,16224fields pass. Integers exact; floats abs1e-12/rel1e-10. Deliberate integer divergence rejected. Scope: firstIRAP initialization/CTU decisions/CTU feedback only, excluding picture-final and remaining15frames. Existing eight-scenario independent replay additionally covers inter/model updates etc:4200records,13192fields pass.

## Low-rate startup overshoot

At1.6Mbps the full16frame budget is853333bits, but both original and compat kernels target1287075bits for the firstIRAP (150.83% of whole budget). At3.2Mbps firstIRAP1748232bits exceeds whole1706666bit budget slightly. These explain low-rate short-window overshoot; logic equivalence does not imply accurate rate at every target.

## Paired accounting and limitations

RC bitrate = sum of actual picture feedback bits *30/16. VVenC: CSV picture bits. VTM: [RC360RC][FrameBits] actualBits. VTM POC log counts AnnexB startcodes; retain poc_log_bps separately. Whole-file AnnexB bitrate is separate. Require exactly16unique POCs0..15, and always decode the current stream.

Reference: same raw input,16frames,30fps,CTU128,explicit LDP P/GOP8,internal/output10bit,KeepHierarchicalBit2,LCUSeparateModel1,InitialQP0,ForceIntraQP0,TemporalFilter0,FbTc0. Actual bits/distortion differ between coding engines, so QP/PSNR equality is not required. All four VTM IRAP targets match compat integers: 1287075, 1748232, 2849550 and 3870538 bits. Actual firstIRAP bits differ because the coding engines differ.

For operational convergence, additionally test128frames and report whole-sequence,first16 and last16 errors. The main experiment remains16frames. Artifacts: build-vtmrc/aerialcity16_ldp. CTU64 precheck is archived separately and excluded from final figures. Official VTM tag authentication is still pending; source equivalence refers to the local hashes in provenance.json.

## Completed paired point R1

Same16frame raw3840x1920 CTU128 protocol, both decode/reconstruction checks passed. VTM actualRC2.416350Mbps (error+51.021875%); VVenC actualRC2.417235Mbps (error+51.0771875%). Achieved rate difference0.036625%; rate-error difference0.0553125percentage points. The R2 paired point is also complete; R3 and R4 remain pending. The overshoot is nearly the same in this completed pair, not proof of bitrate accuracy.

## Completed R2 paired result

At 3.2 Mbps, VTM RC actual rate is 3,290,175 bps (+2.817969%), versus VVenC compatibility RC 3,283,140 bps (+2.598125%). The achieved-rate difference is -0.213818% relative to VTM. Both 16-frame streams decode to their encoder reconstructions. Mean picture Y PSNR is 36.829620 dB for VTM and 36.016283 dB for VVenC; this coding-quality difference does not establish a rate-control logic difference.

Actual CU QP can differ from requested CTU QP because the coding engine infers QP for CUs without residual coefficients. Both VTM and VVenC contain this normative inference path. The compatibility feedback follows VTM's first-luma-CU actual-QP convention. Requested/actual QP equality is therefore not used as a reproduction criterion.


## Reproduction commands

Run from this isolated worktree. For each RATE in 1600000, 3200000, 6400000, 12800000, use a unique output LABEL:

```powershell
bin/release-static/vvencFFapp.exe --preset faster -c docs/vtm23-rc/aerialcity16_ldp.cfg -i I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv -s 3840x1920 -fr 30 -f 16 -b LABEL.vvc -o LABEL.yuv --InputBitDepth=8 --InternalBitDepth=10 --OutputBitDepth=10 --VTMTargetBitrate=RATE --VTMRCTrace=LABEL.csv --Threads=0 --MaxParallelFrames=0 --IFP=0 --TileParallelCtuEnc=0 --Tiles=1x1 --WaveFrontSynchro=0 --WppBitEqual=0 --HrdParametersPresent=0 --SEIBufferingPeriod=0 --PerceptQPA=0 --BIM=0 --MCTF=0 --LookAhead=0 --STA=0
```

The original VTM commands and executable fingerprint are retained in build-vtmrc/aerialcity16_ldp/vtm_runs.json. Its cfg path is I:/001-IBRC-exps/VTM-23.0/cfg/encoder_lowdelay_P_vtm.cfg; overrides include TemporalFilter=0, RateControl=1, KeepHierarchicalBit=2, LCULevelRateControl=1, RCLCUSeparateModel=1, InitialQP=0, RCForceIntraQP=0, WaveFrontSynchro=0 and RC360FbTc=0.

```powershell
python tools/vtmrc/aerialcity_replay.py
python tools/vtmrc/test_aerialcity_analysis.py
python tools/vtmrc/analyze_aerialcity.py --decoder I:/001-IBRC-exps/VTM-23.0-paper-scc-rc/bin/vs16/msvc-19.29/x86_64/release/DecoderApp.exe
```

## Lambda feedback review

Independent read-only review of the current faster configuration confirmed that setUpLambda stores the requested luma RD lambda, and encodeCtu does not rewrite it with QPA/BIM disabled. Chroma weighting, normative QP inference and motion-search lambda selection do not alter the luma RD lambda. Thus feedback of rcDecision.lambda matches this configuration's coding path. This is static call-chain evidence; no additional runtime lambda measurement was performed.

## Completed R3 paired result

At 6.4 Mbps, VTM RC actual rate is 6,403,305 bps (+0.051641%), versus VVenC compatibility RC 6,404,025 bps (+0.062891%). The achieved-rate difference is +0.011244% relative to VTM. Both 16-frame streams decode to their encoder reconstructions. Mean picture Y PSNR is 39.384556 dB for VTM and 39.014506 dB for VVenC. Only R4 remains pending.
