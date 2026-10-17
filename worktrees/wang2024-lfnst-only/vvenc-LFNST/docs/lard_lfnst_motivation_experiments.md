# LFNST Latitude Motivation Experiments

This note records the completed motivation experiments requested for the paper.
The generated artifacts are under:

`lahtp_runs/motivation_experiments/`

## Setup

Sequence: `I:\Sequences360\AerialCity_3840x1920_30fps_8bit_420_erp.yuv`

Coding setup:

| Experiment | Data source | QP | Frames | Preset |
| --- | --- | ---: | ---: | --- |
| 3.1 residual spectrum | fresh residual-spectrum trace | 32 | 1 | medium |
| 3.2 final LFNST usage | existing full-RDO final-CU traces | 22, 27, 32, 37 | 1 | medium |
| 3.3 true LFNST RD gain | existing full-RDO candidate block summaries | 22, 27, 32, 37 | 1 | medium |

For 3.1, tracing used `LardLfnstSkip=1` only to force residual feature
evaluation, with `LardLfnstThetaMinDeg=0`, `LardLfnstEnergyThr=0`, and
`LardLfnstLfRatioThr=1`, so the LFNST pruning condition is never satisfied.
The trace therefore records full residual-spectrum features without applying
the proposed pruning.

The encoder trace was extended to write the residual DCT energy grid
`spec00..spec63` from `org - pred` for each primary no-LFNST candidate. The
trace writer is protected by a mutex to keep 20-thread CSV output valid.

## 3.1 Latitude And Residual Spectrum Redistribution

Artifact files:

| Figure/table | File |
| --- | --- |
| Fig. 1(a) average residual spectrum heatmap | `fig1a_average_residual_spectrum_heatmap.png` |
| Fig. 1(b) horizontal-high energy ratio | `fig1b_horizontal_high_ratio.png` |
| Fig. 1(c) LFNST ROI low-frequency concentration | `fig1c_lfnst_roi_lf_concentration.png` |
| Fig. 1(d) directionality and total energy | `fig1d_directionality_and_total_energy.png` |
| Numeric table | `fig1_spectrum_metrics_by_latitude.csv` |

Key results:

| Latitude | Samples | E_HF/E_total | E_horizontal-high/E_total | E_LF/E_ROI | Directional ratio | Mean total spectral energy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [0,30) | 648913 | 0.095528 | 0.065459 | 0.506178 | 0.490013 | 460221 |
| [30,60) | 473640 | 0.111120 | 0.067194 | 0.510901 | 0.476401 | 334010 |
| [60,75) | 146586 | 0.137717 | 0.055948 | 0.507364 | 0.437753 | 160077 |
| [75,90] | 51409 | 0.157507 | 0.037054 | 0.456495 | 0.328171 | 188623 |

Interpretation: the horizontal-high residual energy ratio drops from `0.0655`
to `0.0371` between low latitude and the polar bucket, while the horizontal
directional ratio also drops from `0.490` to `0.328`. This supports the ERP
horizontal frequency-compression argument. The total residual energy is content
dependent and does not by itself explain the effect; the stronger evidence is
the ratio shift inside the spectrum.

## 3.2 Wasted LFNST RDO Versus Latitude

Artifact files:

| Figure/table | File |
| --- | --- |
| Wasted-RDO curve | `fig_wasted_lfnst_rdo_by_latitude_qp.png` |
| Paper table by latitude and QP | `table_wasted_lfnst_rdo_by_latitude_qp.csv` |
| Detailed grouping by latitude/QP/block size/intra mode/LFNST set | `table_wasted_lfnst_rdo_by_lat_qp_size_mode_set.csv` |
| Block-size grouped table | `table_wasted_lfnst_rdo_by_latitude_size.csv` |
| QP and block-size grouped table | `table_wasted_lfnst_rdo_by_latitude_qp_size.csv` |
| Exact block-size grouped table | `table_wasted_lfnst_rdo_by_latitude_qp_exact_size.csv` |
| Latitude/block-size heatmap | `fig_wasted_lfnst_rdo_heatmap_latitude_size.png` |
| Auxiliary final-CU usage table | `table_usage_lfnst_by_latitude_qp.csv` |

Primary metric:

`Pr(best lfnstIdx = 0 | LFNST RDO tested, latitude)`.

The denominator only includes block/mode groups where the full-RDO trace has a
valid no-LFNST cost and at least one valid LFNST cost. This avoids the confound
that one latitude bucket may simply contain fewer LFNST-eligible blocks. The
numerator is `oracleSkip=True`, equivalently `Delta J_LFNST <= 0`.

| Latitude | QP22 | QP27 | QP32 | QP37 |
| --- | ---: | ---: | ---: | ---: |
| [0,30) | 0.856513 | 0.766811 | 0.763152 | 0.746949 |
| [30,60) | 0.827120 | 0.695708 | 0.677607 | 0.676636 |
| [60,75) | 0.784730 | 0.610942 | 0.591655 | 0.591508 |
| [75,90] | 0.700319 | 0.597497 | 0.589447 | 0.650650 |

All-QP wasted-RDO ratios are `0.7987`, `0.7512`, `0.6991`, and `0.6582` from
low to high latitude.

Block-size grouped all-QP wasted-RDO ratio:

| Latitude | area_16 | area_32 | area_64 | area_256 | area_1024 | area_large |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [0,30) | 0.755239 | 0.753571 | 0.819170 | 0.812345 | 0.856973 | 0.994131 |
| [30,60) | 0.746899 | 0.729123 | 0.766770 | 0.739788 | 0.774941 | 0.981609 |
| [60,75) | 0.756609 | 0.700609 | 0.688565 | 0.683331 | 0.721108 | 0.975502 |
| [75,90] | 0.740130 | 0.646761 | 0.625966 | 0.633266 | 0.734129 | 0.935004 |

Interpretation: after conditioning on LFNST actually being tested, the
probability that the RDO ends up choosing `lfnstIdx=0` decreases with latitude.
Thus high latitude is not where LFNST is most often "white-done"; low and
mid-latitude blocks waste more LFNST RDO attempts under this trace. This trend
also holds within the common block-size groups `area_32`, `area_64`, and
`area_256`. Very large blocks have high wasted-RDO ratios in all latitude
buckets and should be treated as a separate size-dependent pruning signal.
This is a stronger and fairer result than raw final LFNST usage because the
denominator is the set of LFNST-RDO-tested samples.

## 3.3 True LFNST RD Gain Versus Latitude

Artifact files:

| Figure/table | File |
| --- | --- |
| Fig. 2(a) delta-J boxplot | `fig2a_delta_j_boxplot_by_latitude.png` |
| Fig. 2(b) positive-gain ratio | `fig2b_positive_gain_ratio_by_latitude.png` |
| Fig. 2(c) QP-grouped gain curve | `fig2c_gain_curve_by_qp.png` |
| Fig. 2(d) block-size grouped distribution | `fig2d_gain_distribution_by_block_size.png` |
| Main numeric table | `table_rd_gain_by_latitude_qp.csv` |
| Distribution quantiles | `table_rd_gain_distribution_by_latitude.csv` |

Definition:

`Delta J_LFNST = J0 - min(J1, J2)`.

Positive values mean at least one LFNST candidate beats no LFNST.

Main results:

| Latitude | Samples | E[Delta J_LFNST] | Pr(Delta J_LFNST > 0) |
| --- | ---: | ---: | ---: |
| [0,30) | 2018536 | -25029975.41 | 0.201151 |
| [30,60) | 1626957 | -12902065.20 | 0.248683 |
| [60,75) | 579550 | -5265612.17 | 0.300776 |
| [75,90] | 246820 | -6329082.88 | 0.341715 |

Interpretation: the probability of a positive LFNST RD gain increases with
latitude (`20.1%` to `34.2%`). Mean delta-J remains negative in every bucket
because many candidates are strongly worse than no LFNST, but the high-latitude
region is not an RD-dead zone for LFNST.

## 12.2 Controlled Stretch Mechanism Validation

The final mechanism-validation design is a patch-level controlled sequence
experiment, not an offline spectrum warp.  From the SJTU train and validation
splits, sample 256 fixed `128x128` ERP patches per split with seed `20260524`.
Sampling is latitude-stratified: `[0,30)`, `[30,60)`, `[60,75)`, and `[75,90]`
each contribute 64 patches.  For each stretch factor

`s = {1, 1.15, 1.41, 2.00, 3.86, 5.00}`,

the same patch manifest is horizontally stretched inside each patch using
periodic wrap and then packed as a `512x512`, 16-frame YUV420 sequence
(`4x4` patches per frame).  The stretch factors correspond to
`theta_s = acos(1/s)` at approximately `0`, `29.6`, `44.8`, `60.0`, `75.0`,
and `78.5` degrees.

Run the full experiment:

```text
powershell -ExecutionPolicy Bypass -File tools/lard_lfnst_patch_stretch_12_2_run.ps1
```

Run the smoke subset (`validation`, `s={1,2}`, `QP32`):

```text
powershell -ExecutionPolicy Bypass -File tools/lard_lfnst_patch_stretch_12_2_run.ps1 -Smoke
```

The workflow scripts are:

| Step | Tool |
| --- | --- |
| Patch sampling and stretched YUV generation | `tools/lard_lfnst_patch_stretch_12_2.py` |
| Encoding orchestration and analysis call | `tools/lard_lfnst_patch_stretch_12_2_run.ps1` |
| Trace/manifest mechanism analysis | `tools/lard_lfnst_patch_mechanism_12_2.py` |

Required outputs under `lahtp_runs/sjtu_patch_stretch_12_2/analysis/`:

| Mechanism check | Output table |
| --- | --- |
| `E_ROI/E_total` and `E_LF/E_ROI` versus stretch, source latitude, and block size | `table_12_2_energy_by_stretch_lat_size.csv` |
| `E_LF/E_ROI` grouped by positive/negative LFNST gain | `table_12_2_lf_roi_by_gain_sign.csv` |
| signed ROI `C_off` and per-block `C_proxy` versus `DeltaJ` | `table_12_2_correlation_deltaJ.csv` |
| signed ROI covariance eigenvalue concentration | `table_12_2_roi_cov_eigen.csv` |
| `DeltaN=N0-min(N1,N2)` and `DeltaL=L0-min(L1,L2)` | `table_12_2_deltaN_deltaL.csv` |
| Candidate 1/2 preference versus stretch, latitude, and block size | `table_12_2_candidate_preference.csv` |

The encoder trace has been extended with `nonZero`, `lastPos`, `roiDim`, and
`roiQ00..roiQ47`, so `DeltaN`, `DeltaL`, signed ROI covariance, and true
`C_off` can be measured directly.  This patch-level controlled sequence is for
mechanism validation only and must not be reported as full ERP coding
performance.

## Conclusion For The Paper

The motivation should be adjusted:

1. ERP latitude measurably changes the residual spectrum. The clearest signal
   is horizontal-high energy compression and lower horizontal directionality at
   high latitude.
2. After conditioning on LFNST being tested, high latitude does not show a
   higher wasted-RDO probability; the wasted-RDO ratio is lower at high
   latitude on this trace.
3. High latitude also does not imply lower probability of true positive LFNST
   RD gain.
4. Therefore the proposed method should be motivated as a latitude-aware
   **sparsity/ROI candidate pruning** method, not as a blanket high-latitude
   LFNST disabling method. Ordinary fast LFNST is insufficient because it does
   not use ERP latitude plus quantized ROI evidence to distinguish high-latitude
   blocks where LFNST remains useful from high-latitude blocks where LFNST
   candidates are predictably wasteful.
