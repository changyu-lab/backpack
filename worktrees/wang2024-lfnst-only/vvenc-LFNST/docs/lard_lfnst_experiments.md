# Latitude-Aware LFNST Pruning Experiments

This note records the experiments needed to replace the conservative default
parameters in the online LARD-LFNST decision with sequence-independent fitted
parameters.

## Implemented Online Decision

The encoder-side decision is enabled by `--LardLfnstSkip 1`, `2`, `3`, `4`, `5`, or `6`.
Mode 1 uses the conservative global thresholds. Mode 2 uses the grouped
zero-false fitted threshold table and is currently experimental. Mode 3 uses a
speed-oriented grouped table fitted for a larger controlled false-skip budget.
Mode 4 is a speed-target mode that uses only the analytic latitude threshold
and skips LFNST without ROI projection; it must be reported separately from
the conservative two-stage method.
Mode 5 is a target-speed upper-bound mode that prunes LFNST RDO candidates
encoder-side. It is intended for the user's target of around 10%+ time saving
with less than 0.5-1% BD-rate loss, and must not be presented as the
conservative two-stage model.
Mode 6 is the optimized full two-stage model: stage 1 still uses the analytic
latitude threshold, while stage 2 reuses the already computed no-LFNST primary
transform quantized ROI instead of running an extra online DCT approximation.
It remains a two-stage sparsity decision and avoids most of the extra ROI
projection overhead.

The online implementation performs:

1. ERP center latitude and block-span latitude calculation.
2. Closed-form latitude threshold:
   `theta_skip,l = atan(sqrt(log(A_l / C_l) / (gamma_l * psi)))`.
3. Effective horizontal frequency weight:
   `eta_u(theta; psi) = exp(-psi * (u / u0)^2 * tan(theta_max)^2)`.
4. A low-cost DCT-II approximation for the primary-transform LFNST ROI:
   16 coefficients for 4x4 candidates, and an 8x8 low-frequency set with the
   bottom-right 4x4 omitted for 48-coefficient candidates.
5. Laplacian tail non-zero prediction for the no-LFNST ROI coefficients.
6. Safety skip only if all conditions hold:
   `theta_max >= theta_skip`, normalized ROI energy `< T_E`,
   low-frequency concentration `> T_LF`, and predicted no-LFNST non-zeros
   `< T_N`.

The implementation does not change the bitstream syntax. If the test passes,
the luma LFNST search range is pruned to `lfnstIdx = 0`.

## Parameters That Must Be Fitted

Fit the following by QP group, block-size group, intra-mode group, and LFNST
set when enough samples are available:

| Encoder option | Method symbol | Fitting target |
| --- | --- | --- |
| `LardLfnstPsi` | `psi` | high-horizontal-frequency effectiveness decay |
| `LardLfnstU0` | `u0` | frequency normalization in `eta_u` |
| `LardLfnstGain1/2` | `A_l` | low-latitude sparse/RD gain of LFNST candidates |
| `LardLfnstCost1/2` | `C_l` | LFNST index plus distortion-normalized cost |
| `LardLfnstGamma1/2` | `gamma_l` | candidate sensitivity to latitude decay |
| `LardLfnstEnergyThr` | `T_E` | safe normalized ROI-energy threshold |
| `LardLfnstLfRatioThr` | `T_LF` | safe low-frequency concentration threshold |
| `LardLfnstNzThr` | `T_N` | safe predicted no-LFNST non-zero threshold |
| `LardLfnstTqKappa` | `kappa` | quantizer dead-zone tail threshold |
| `LardLfnstMeanAbsQGate` | cheap gate | normalized mean absolute residual pre-gate before ROI projection |

The current defaults are the conservative validation setting fitted from the
medium-preset pilot trace:

| Option | Default |
| --- | ---: |
| `LardLfnstEnergyThr` | `0.5` |
| `LardLfnstLfRatioThr` | `0.5` |
| `LardLfnstNzThr` | `2.0` |
| `LardLfnstMeanAbsQGate` | `1.5` |

They are suitable for smoke and pilot experiments. They are not final paper
parameters until the train/validation/test split below has been completed on
the full 360-degree sequence set.

## Required Trace Collection

Collect full-RDO traces with the pruning disabled. For every LFNST-eligible
luma block and every tested candidate, log:

`sequence, poc, qp, x, y, w, h, intraMode, modeGroup, mtsIdx, lfnstIdx,
absLatDeg, thetaMaxDeg, ROI coefficients, E_ROI, E_LF, rho_LF, N0_pred,
nonZero, lastPos, roiDim, signed ROI coefficients `roiQ00..roiQ47`,
absLevelSum, fracBits, distortion, rdCost, selected`.

Also log per-block derived labels:

`J0, J1, J2, bestLfnstIdx, G1 = J0 - J1, G2 = J0 - J2,
oracleSkip = (min(J1,J2) >= J0), DeltaN = N0 - min(N1,N2),
DeltaL = L0 - min(L1,L2)`.

## Fitting Workflow

1. Split sequences into training, validation, and final test sets. Do not tune
   thresholds on the final test set.
2. Fit `psi` and `u0` from horizontal frequency-bin decay. Regress measured
   high-horizontal-frequency effectiveness against
   `(u/u0)^2 * tan(theta)^2` using least squares or robust Huber regression.
3. Fit `A_l` and `gamma_l` by candidate:
   fit positive-gain samples to
   `DeltaS_l(theta) = A_l * exp(-gamma_l * psi * tan(theta)^2)`.
4. Fit `C_l` from `r_l + (D_l - D0) / lambda`, grouped by QP, size, mode group,
   and LFNST set. Use robust medians or upper quantiles for conservative skip.
5. Calibrate `kappa` by minimizing Brier score or RMSE between predicted and
   real quantized non-zero probabilities.
6. Select `T_E`, `T_LF`, and `T_N` on the validation set to satisfy a target
   false-skip rate. The recommended primary constraint is false-skip RD loss,
   not skip ratio.
7. Select `LardLfnstMeanAbsQGate` as a speed guard after the safety thresholds
   are fixed. It may only reject blocks that would fail the full ROI safety
   test on the validation set; report any lost skip opportunities separately.

## Validation Experiments

Report these before claiming the model is complete:

1. Latitude-bucket LFNST usage and true RD gain.
2. Horizontal frequency-bin redistribution: low-bin gain, high-bin decay, and
   total-energy behavior.
3. `eta_u(theta; psi)` fit quality: RMSE, MAE, and `R^2`.
4. ROI covariance prediction: diagonal, block-diagonal, and full covariance.
5. LFNST output variance prediction for candidates 1 and 2.
6. Laplacian/Gaussian/GGD coefficient distribution fitting.
7. Non-zero probability calibration and expected non-zero-count prediction.
8. Rate model ablation: `N` only, `N + log(lastPos)`, and
   `N + log(lastPos) + absLevelSum`.
9. RD gain sign accuracy, AUC, false-skip rate, and missed RD gain.
10. Candidate pruning versus direct-index prediction.
11. AI main coding performance: Y-BD-rate, WS-PSNR BD-rate, CPP-PSNR BD-rate,
    total encoding time, and LFNST-module time.
12. RA/LDB/LDP secondary performance and complexity breakdown.
13. Generalization across sequence, dataset, resolution, QP, block size, and
    intra-mode group.

## Medium-Preset Pilot Results

Pilot setup:

| Item | Value |
| --- | --- |
| Sequences | `AerialCity_half_960x480`, `BranCastle2_half_768x384`, `DrivingInCity_half_960x480` |
| QP | `22, 27, 32, 37` |
| Frames | first frame only |
| Preset | `medium` |
| Coding | AI-style intra period `1`, QPA off, single thread |
| Path used | `I:\Sequences360\low` |

The user-provided `I:\sequence360` path was not present on the machine; the
available ERP directory was `I:\Sequences360`.

Trace-based threshold fitting on the 12 pilot cases gave:

| Constraint | `T_E` | `T_LF` | `T_N` | Predicted skip / eligible | Predicted false skip |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1% false-skip-in-predicted-skips | `0.5` | `0.5` | `2.0` | `1745 / 1182601` (`0.148%`) | `10 / 1745` (`0.573%`) |
| 5% false-skip-in-predicted-skips | `2.0` | `0.3` | `2.0` | `4714 / 1182601` (`0.399%`) | `225 / 4714` (`4.773%`) |

Real no-trace encoding with the 1% setting was byte-identical on all 12 pilot
cases and reduced total measured encoding time from `207.527 s` to `199.934 s`
(`3.66%`). The 5% setting changed the bitstream size on 2 of the 12 pilot
cases, so it is not used as the default safety setting.

The online implementation also uses `LardLfnstMeanAbsQGate = 1.5` as a cheap
pre-gate. On the pilot trace, no block that satisfied the fitted 1% safety
conditions had `meanAbsQ > 1.5`; therefore this gate removes many expensive
ROI projections without changing the fitted skip set on the pilot validation
data. This must be revalidated on the full training/validation split.

Threading note: 20-thread paired pilot runs are RD-safe but do not yet show a
stable time gain on the low-resolution one-frame subset. With the conservative
defaults, the paired 20-thread pilot measured `98.109 s` for anchor and
`98.954 s` for the proposed encoder (`-0.86%` time saving), with byte-identical
output on all 12 cases. This indicates that the current conservative skip rate
is too low to overcome online-decision overhead when encoder parallelism is
high. The cheap gate reduces this overhead but does not by itself create enough
skips for a positive 20-thread result.

Grouped fitting status:

| Fitting setup | Predicted skip / eligible | Trace false skip | Real 20-thread byte changes |
| --- | ---: | ---: | ---: |
| Global 1% stage-1 thresholds | `2723 / 1182601` (`0.230%`) | `13` | not selected |
| Grouped 1% stage-1 thresholds | `4198 / 1178602` (`0.356%`) | `4` | `2 / 12` |
| Grouped zero-false stage-1 thresholds | `4054 / 1178602` (`0.344%`) | `0` | `2 / 12` |

The grouped table is therefore kept as `LardLfnstSkip=2` only. It is useful for
continued fitting research, but it is not yet conservative enough for the main
reported method because single-block oracle labels do not fully capture
closed-loop encoder interactions.

Speed-target results:

| Mode | Description | 20-thread TS | Avg Y-BDBR | Avg YUV-BDBR |
| --- | --- | ---: | ---: | ---: |
| `LardLfnstSkip=4` | analytic latitude threshold only | `2.10%` | `-0.036%` | `0.047%` |
| `LardLfnstSkip=5` | target-speed LFNST candidate prune | `17.35%` | `0.423%` | `0.470%` |
| `LardLfnstSkip=6` | optimized lazy two-stage sparsity model | `17.67%` | `0.443%` | `0.455%` |
| `LFNST=0` | tool-off upper bound | `31.34%` | `0.771%` | `0.595%` |

On the current medium-preset 20-thread pilot subset, `LardLfnstSkip=6` satisfies
the practical target of at least 10% time saving with less than 0.5-1% BD-rate
loss while keeping the two-stage latitude plus sparsity-decision structure.
`LardLfnstSkip=5` remains a useful upper-bound target-speed comparison.

## SJTU 4K Refit Protocol

The refit for the optimized two-stage model uses only SJTU data:

| Split | Sequences | Frames | QP |
| --- | --- | --- | --- |
| Train | `AcademicBuilding`, `EastGate`, `Library` from `I:\SJTU8K360sequence\first100f` | first frame | `22,27,32,37` |
| Validation | `AdministrationBuilding`, `SouthGate` from `I:\SJTU8K360sequence\first100f` | first frame | `22,27,32,37` |
| Test | `I:\Sequences360\AerialCity_3840x1920_30fps_8bit_420_erp.yuv` | not used during fitting | report only |

The trace used for this refit records the no-LFNST primary-transform quantized
ROI, not the earlier online DCT approximation. This matches the optimized
`LardLfnstSkip=6` implementation.

Fitted train-table candidates:

| Candidate | Train eligible skip | Train trace false-skip | Validation eligible skip | Validation trace false-skip |
| --- | ---: | ---: | ---: | ---: |
| grouped 20%, closed-form stage-1 | `12.21%` | `1.22%` | `10.54%` | `0.87%` |
| grouped 30%, closed-form stage-1 | `20.85%` | `10.91%` | `17.54%` | `10.45%` |
| grouped 20%, refit stage-1 disabled for fitting | `44.27%` | `1.08%` | `45.54%` at `theta_min=0` | `0.95%` |

Validation closed-loop results for the selected no-stage train table:

| Stage-1 setting | Validation TS | Avg Y-BD-rate | Avg YUV-BD-rate |
| --- | ---: | ---: | ---: |
| closed-form stage-1 | `7.77%` | `-0.037%` | `0.014%` |
| `LardLfnstThetaMinDeg=45` | `8.50%` | `-0.055%` | `-0.007%` |
| `LardLfnstThetaMinDeg=30` | `6.59%` | `-0.055%` | `-0.007%` |

The selected refit configuration before final test is therefore:

```text
LardLfnstSkip=6
LardLfnstThetaMinDeg=45
T_E/T_LF/T_N/A_l/C_l/gamma_l from LardLfnstFitTable.inc
```

`MeanAbsQGate` is not used by `LardLfnstSkip=6`; it remains only for the older
extra-DCT online variant. Re-fitting it would require a separate residual-stat
trace and should not affect the selected lazy two-stage method.

## AerialCity Frozen Test Result

Final test uses the selected SJTU-refit configuration without any test-set
tuning:

```text
LardLfnstSkip=6
LardLfnstThetaMinDeg=45
```

Test setup:

| Item | Value |
| --- | --- |
| Test sequence | `I:\Sequences360\AerialCity_3840x1920_30fps_8bit_420_erp.yuv` |
| Frames | first frame |
| QP | `22,27,32,37` |
| Preset | `medium` |
| Coding | AI-style intra period `1`, QPA off |
| Threads | `20` |
| Timing | three repeated paired runs, mean time reported |
| Output root | `lahtp_runs\aerialcity_final_4k_1f_medium_t20_skip6_theta45` |

Per-QP timing and RD points:

| QP | Anchor mean time | Proposed mean time | TS | Anchor kbps | Proposed kbps | Anchor Y | Proposed Y | Anchor YUV | Proposed YUV |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 22 | `39.466 s` | `36.118 s` | `8.48%` | `178211.28` | `178296.48` | `44.9080` | `44.9032` | `45.6675` | `45.6663` |
| 27 | `24.705 s` | `20.563 s` | `16.77%` | `69055.44` | `69466.56` | `41.6400` | `41.6370` | `42.6690` | `42.6658` |
| 32 | `15.347 s` | `13.075 s` | `14.80%` | `36282.24` | `36478.56` | `39.8754` | `39.8642` | `40.9563` | `40.9483` |
| 37 | `10.981 s` | `9.168 s` | `16.50%` | `20435.76` | `20537.76` | `37.9442` | `37.9136` | `39.0766` | `39.0468` |

Final frozen-test summary:

| Metric | Value |
| --- | ---: |
| Total TS | `12.790%` |
| Y-BD-rate | `0.709%` |
| U-BD-rate | `0.643%` |
| V-BD-rate | `0.272%` |
| YUV-BD-rate | `0.701%` |
| Bitstream byte delta | `0.261%` |

All repeated timing runs produced consistent anchor/proposed bitstream sizes.
The frozen two-stage method therefore meets the target on this first-frame
medium-preset AerialCity test: time saving is above `10%`, and BD-rate loss is
within the requested `0.5-1%` envelope.

Spherical-metric BDBR is computed from reconstructed YUV output. The simple
`vvencapp` frontend does not expose reconstruction output, so `vvencFFapp` was
built and used only for the reconstruction dump. The reconstructed files are
10-bit little-endian because the encoder internal bit depth is 10; the metric
script scales them back to 8-bit-equivalent error before computing PSNR. WS-PSNR
uses 360Lib ERP cosine row weights, and CPP-PSNR uses the 360Lib Craster
Parabolic valid-domain equations with bilinear sampling of the ERP error plane.

Spherical-metric frozen-test summary:

| Metric | BDBR |
| --- | ---: |
| WS-Y-BD-rate | `0.672%` |
| WS-U-BD-rate | `1.057%` |
| WS-V-BD-rate | `1.197%` |
| WS-YUV-BD-rate | `0.730%` |
| CPP-Y-BD-rate | `0.722%` |
| CPP-U-BD-rate | `0.981%` |
| CPP-V-BD-rate | `1.208%` |
| CPP-YUV-BD-rate | `0.780%` |

For the luma and combined YUV spherical metrics used in 360-degree coding
reports, the final method remains within the requested `0.5-1%` BD-rate loss
envelope: `WS-Y=0.672%`, `WS-YUV=0.730%`, `CPP-Y=0.722%`, and
`CPP-YUV=0.780%`.
