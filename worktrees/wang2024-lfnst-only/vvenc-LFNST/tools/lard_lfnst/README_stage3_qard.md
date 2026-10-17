# Skip21 Stage-3 QARD: implementation and experiment runbook

This file documents the new **Stage-3 quantization-aware differential RD (QARD)** path built on top of the existing Skip21 Stage1 + theory-table Stage2 baseline.

## 1. Locked baseline and non-goals

The baseline decision path remains:

```text
LFNST=1
LardLfnstSkip=21
LardLfnst21Stages=123
LardLfnst21Profile=5
LardLfnst21Stage2Profile=12
LardLfnst21Stage2HighCostMode=1
LardLfnst21Stage2Debug=0
```

- Stage1 is the existing geometry/support-ratio pre-screen.
- Stage2 is the existing Skip21 theory-table path (`xLardSkip21FindTheoryEntry()` + `xLardSkip21Stage2WeakCoupling()`).
- **Stage2 is not an online covariance estimator and is not described as one.**
- QARD runs only after Stage1/2 pass and after the real `lfnstIdx=0` DCT-II RDO has completed.
- The existing formal `Stage3Mode=3/Profile=5/RdProfile=3` implementation is left intact for comparison. QARD is selected through the previously experimental `Stage3RdeMode/Model` namespace so that old results remain reproducible.

For QARD experiments, set `LardLfnst21Stage3Mode=0` so the old Stage3 does not prune before QARD is evaluated.

## 2. Stage-3 model

### 2.1 Current-block second-order response

Let `x` be the standard LFNST input vector collected from the **actual current-block DCT-II coefficients** after the real DCT-II candidate has been evaluated. Model 3 uses the rank-one current-block empirical second moment

```text
Sigma_cur = x x^T.
```

This is deliberately called an *empirical second-moment / rank-one covariance surrogate* rather than a multi-sample covariance estimate. For a zero-mean residual model it is the single-observation covariance surrogate. The existing Stage1/2 supplies the projection/theory prior; Stage3 adds current-block evidence.

For nonzero candidate `l`,

```text
y_l = S_l x,
diag(S_l Sigma_cur S_l^T) = y_l^2.
```

The implementation evaluates `S_l x` with the same VVenC scalar/SIMD integer LFNST kernel used by the real encoder. It does **not** call candidate quantization, CABAC, inverse spatial reconstruction, or candidate RDO.

The zero-out/projection loss is measured in the DCT-II input domain by applying only the standard inverse LFNST linear kernel:

```text
L_proj,l = ||x - S_l^T y_l||_2^2
```

using the codec's integer scaling/rounding. This is an efficient implementation of the current-block linear response, not a full candidate probe.

### 2.2 Encoder-domain quantization step

The theoretical step is derived in the same integer-transform coefficient domain as VVenC using `QpParam`, DepQuant QP offset, transform shift, `needsSqrt2Scale()`, `g_quantScales`, and `QUANT_SHIFT`.

When at least three reliable DCT-II quantized coefficients exist, the current block provides a local observation `|c_i|/|level_i|`. A median estimate is log-domain shrunk toward the codec-theoretical step. This makes Stage3 quantization-aware while avoiding dependence on a fragile individual RDOQ level.

### 2.3 QARD distortion/rate surrogate

For response variance/energy `v >= 0` and coefficient-domain step `q`, the model uses

```text
Dhat(v,q) = v q^2 / (12 v + q^2)
Rhat(v,q) = 0.5 log2(1 + 12 v / q^2).
```

The distortion term has the desired limiting behavior: it approaches `v` when a coefficient is far below the quantization scale and approaches `q^2/12` in the high-rate regime.

For DCT-II (`l=0`):

```text
Dhat_0 = sum_i Dhat(x_i^2,q)
Rhat_0 = sum_i Rhat(x_i^2,q).
```

For LFNST candidate `l`:

```text
Dhat_l = L_proj,l + sum_r c_l,r Dhat(y_l,r^2,q)
Rhat_l = R_idx + sum_r Rhat(y_l,r^2,q),
```

where `c_l,r` is the fixed inverse-column energy. Since the VVC inverse matrix is the transpose of the forward matrix, this is the normalized forward-row energy; it is cached once. `R_idx` is the configurable LFNST-index syntax overhead proxy (`LardLfnst21Stage3RdeIdxBits`, default 1.0 bit). Systematic mismatch is protected by the risk calibration below.

### 2.4 Mapping to VVenC's RD-cost scale

For the integer DCT-II used by this code base, the coefficient-domain differential SSE is mapped to spatial SSE by

```text
a_WH = W H * 2^( 2*(bitDepth - maxLog2TrDynamicRange) ).
```

For common 10-bit / max-range-15 blocks this gives approximately `1/16` for 8x8, `1/4` for 16x16 and `1` for 32x32, matching direct residual/DCT energy checks up to integer-transform rounding.

VVenC's scaled RD cost is used. If `k_D` is the distortion cost of one SSE unit (`RdCost::calcRdCost(0,1)-calcRdCost(0,0)`), then

```text
ghat_l = k_D * a_WH * (Dhat_l - Dhat_0)
         + 2^SCALE_BITS * (Rhat_l - Rhat_0).
```

`ghat_l > 0` predicts that nonzero candidate `l` is worse than the already evaluated DCT-II candidate.

Normalize against the true DCT-II cost `J0`:

```text
mhat_l = ghat_l / max(1, |J0|)
mhat   = min(mhat_1, mhat_2).
```

Positive `mhat` means both nonzero candidates are predicted worse.

## 3. Risk-controlled pruning

Shadow mode always executes the original nonzero candidate RDOs and records truth:

```text
m_true = (min(J1,J2) - J0) / max(1, |J0|).
```

Positive `m_true` means it is actually safe to keep only `lfnstIdx=0` relative to the nonzero LFNST candidates tested by the baseline encoder.

Define calibration error

```text
e = mhat - m_true.
```

For target one-sided tail probability `alpha`, obtain an upper finite-sample quantile `q_(1-alpha)` of `e`. The calibrated lower bound is

```text
LB = mhat - q_(1-alpha).
```

Real pruning is enabled only when

```text
LB >= 0.
```

The default calibration mode is `sequence_max`: compute the finite-sample upper quantile independently for every calibration sequence (pooling that sequence's QPs) and take the maximum. This prevents a long/easy sequence from dominating the margin. Calibration and held-out test sequence labels are required to be disjoint.

The encoder additionally clamps the risk margin to be non-negative, so calibration can never make the analytic predictor *more aggressive* than `mhat >= 0`.

## 4. Configuration

New/extended Stage3-RDE options:

```text
LardLfnst21Stage3RdeMode       0 off; 1 shadow; 2 real prune
LardLfnst21Stage3RdeProfile    0: outN=16 and area>=256
                               1: outN=16
                               2: all QARD-eligible blocks
LardLfnst21Stage3RdeModel      2: full online covariance QARD reference
                               3: fast current-block empirical second-moment QARD
LardLfnst21Stage3RdeRiskMargin calibrated normalized one-sided margin
LardLfnst21Stage3RdeIdxBits    LFNST index bit-overhead proxy (default 1)
LardLfnst21Stage3RdeStatFile   shadow/diagnostic CSV path
```

Model 2 additionally uses `KappaH/KappaV/RhoBaseH/RhoBaseV`. These parameters are retained in generated profiles for reproducibility but are not part of the fast Model-3 response.

## 5. Recommended experiment protocol

### 5.1 Sequence split

Split by **sequence**, never by TU/block. Suggested roles:

1. development sequences: implementation/model diagnostics only;
2. calibration sequences: determine the one-sided risk margin;
3. held-out test sequences: never used for model/margin selection.

For the final paper, a leave-one-sequence-out check is recommended in addition to the fixed split if runtime permits.

### 5.2 Collect full-RDO shadow truth

Run each calibration/test sequence at all target QPs. Example for one sequence:

```bash
PYTHONPATH=. python -m tools.lard_lfnst.run_skip21_stage3_qard_shadow \
  --encoder bin/release-static/vvencapp \
  --orig /data/Sequence.yuv \
  --size 3840x1920 --fps 30 --bitdepth 10 \
  --qps 22,27,32,37 --frames 32 --config RA --gop 8 \
  --preset medium --threads 1 --profile 1 --model 3 \
  --out-dir results/shadow/Sequence
```

Use one thread for calibration CSV collection unless a separate experiment has proven logging/order to be safe under the chosen multi-thread setup.

### 5.3 Calibrate and validate the risk margin

Multiple QP CSVs from the same sequence should use the **same label**, so they are pooled inside that sequence rather than treated as independent sequences:

```bash
PYTHONPATH=. python -m tools.lard_lfnst.calibrate_skip21_stage3_qard \
  --calibration CAL_A=results/shadow/CAL_A/qard_shadow_QP22.csv \
  --calibration CAL_A=results/shadow/CAL_A/qard_shadow_QP27.csv \
  --calibration CAL_A=results/shadow/CAL_A/qard_shadow_QP32.csv \
  --calibration CAL_A=results/shadow/CAL_A/qard_shadow_QP37.csv \
  --calibration CAL_B=results/shadow/CAL_B/qard_shadow_QP22.csv \
  --test TEST_X=results/shadow/TEST_X/qard_shadow_QP22.csv \
  --test TEST_X=results/shadow/TEST_X/qard_shadow_QP27.csv \
  --alpha 0.01 --margin-mode sequence_max --profile 1 --model 3 \
  --out-dir results/calibration/a001_p1
```

Outputs:

- `stage3_qard_calibration.json`: accuracy/risk/regret/timing diagnostics;
- `stage3_qard_real.additional.txt`: calibrated real-pruning config;
- `stage3_qard_shadow.additional.txt`: shadow config;
- `stage3_qard_profiles.json`: dynamic profiles for the formal 360Lib runner.

Key reported diagnostics include:

- eligible-block skip rate;
- wrong-skip rate conditional on skip and overall;
- normalized RD regret mean/P95/P99/max;
- one-sided lower-bound violation rate;
- Pearson/Spearman and MAE (diagnostic only; risk metrics are primary);
- Stage3 evaluation median/1%-trimmed mean;
- nonzero-LFNST RDO timing;
- gross and **net-after-Stage3** estimated RDO saving.

### 5.4 Standalone real-pruning run

```bash
PYTHONPATH=. python -m tools.lard_lfnst.run_skip21_stage3_qard_real \
  --encoder bin/release-static/vvencapp \
  --orig /data/Sequence.yuv \
  --additional-file results/calibration/a001_p1/stage3_qard_real.additional.txt \
  --size 3840x1920 --fps 30 --bitdepth 10 \
  --qps 22,27,32,37 --frames 32 --config RA --gop 8 \
  --preset medium --threads 1 --repeats 3 \
  --out-dir results/real/Sequence
```

Do not enable the Stage3 CSV logger in formal wall-clock runs.

### 5.5 Formal 360Lib paired experiment

The existing formal runner can load calibrated profiles without hard-coding the data-derived margin:

```bash
PYTHONPATH=. python -m tools.lard_lfnst.run_skip21_stage12_ra_360lib \
  --encoder /path/to/vvencapp \
  --360convert /path/to/360ConvertApp \
  --seq-root /path/to/360_sequences \
  --sphere-file /path/to/sphere_points.txt \
  --out-root results/formal_qard \
  --qps 22,27,32,37 \
  --profiles S123_QARD_REAL_CAL \
  --profile-json results/calibration/a001_p1/stage3_qard_profiles.json \
  --threads 1 --preset medium --encode-config RA --ra-gop 8 \
  --repeats 3 --expect-count <N>
```

The formal report should retain ordinary PSNR, WS-PSNR, S-PSNR and CPP-PSNR BD-rate, paired-repeat wall-clock timing, and per-sequence results.

## 6. Required ablations for the paper

At minimum compare:

1. **Anchor:** `LFNST=1 LardLfnstSkip=0`.
2. **Stage1+2 only:** locked Skip21 Stage1 + theory Stage2, old Stage3 and QARD off.
3. **Existing S123AB_Q22All_RDMax:** current old `Stage3Mode=3/Profile=5/RdProfile=3` baseline.
4. **QARD Model 2 shadow/reference:** full online covariance; theoretical reference, not expected deployment winner.
5. **QARD Model 3 shadow:** full-RDO truth and prediction diagnostics.
6. **QARD Model 3 real:** calibrated deployment.
7. Risk sensitivity: `alpha` = 0.005, 0.01, 0.02 (and optionally 0.05 only as an aggressive diagnostic).
8. Eligibility sensitivity: QARD profile 0/1/2.

Do not tune the final alpha or margin on held-out test BD-rate. Select the operating point using calibration-side risk/complexity criteria, freeze it, then evaluate test sequences.

## 7. Acceptance criteria before claiming the final method

A final deployment profile should satisfy all of the following on held-out sequences:

- no unexplained systematic underestimation of destructive nonzero-LFNST gains;
- one-sided bound violation close to or below the calibrated target, with sequence-wise breakdown;
- very small wrong-skip RD regret even when wrong-skip count is nonzero;
- Stage3 evaluation overhead clearly below the expected skipped candidate RDO time;
- positive **paired wall-clock** gain after Stage3 overhead;
- negligible ordinary/WS/S/CPP BD-rate loss under the paper's chosen threshold;
- stable behavior over QP and sequence, not a gain concentrated in a single content class.

Candidate-reduction percentages alone are not evidence of complexity reduction; paired wall-clock time is the final criterion.

## 8. Local implementation smoke status

The implementation has been compiled in Release and exercised on a generated 10-bit 4:2:0 256x128 synthetic AI frame. This is a code-path smoke test, **not evidence of 360-video coding performance**.

For the optimized Model 3 on that smoke case:

- 2,090 shadow QARD samples were recorded;
- Stage3 evaluation median was about 3.0 microseconds;
- the two nonzero LFNST RDOs had a combined median of about 6.1 microseconds;
- a synthetic alpha=0.05 calibration produced a real-pruning profile for smoke purposes only;
- the real-pruning output bitstream SHA-256 exactly matched the full-RDO shadow output on this sample.

The full-covariance Model 2 was also implemented and tested but was much slower (roughly an order of magnitude above candidate-RDO cost in the initial smoke), so it is retained as a theoretical/ablation reference rather than the recommended deployment model.

Formal ERP conclusions require the user's actual sequence corpus and 360Lib evaluation environment; no synthetic result above should be reported as a paper performance number.
