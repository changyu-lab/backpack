# Skip21 Stage3-QARD Selective Activation — 2026-08-13

## 1. Frozen method boundary

Baseline remains Skip21 Stage1 + theory-table Stage2. The new Stage3 is empirical-second-moment QARD plus one-sided risk control. The activation gate only decides whether QARD is evaluated; it never directly prunes LFNST candidates.

Final decision remains:

`predMinNormQard - risk_margin >= 0  => prune lfnstIdx 1/2`

otherwise keep the original `{0,1,2}` RDO.

Recommended risk setup from the four-sequence development set:

- alpha = 0.005
- sequence-max one-sided calibration
- frozen risk margin = `6.845062255859375`

## 2. Why selective activation is necessary

All-eligible Model-3 has good RD validity but poor timing economics. The development analysis estimated an all-eligible prune rate around 4%, while QARD evaluation requires roughly 47–49% conditional prune to break even.

The activation search found a strong depth-3 rule (rule 121), but it uses `baseNnz`, which is not stored for free in the current coding path and would require an additional coefficient scan. That can invalidate the offline timing estimate.

For deployment this patch therefore uses the strongest near-zero-cost rule from the candidate set (rule 0):

- DCT-II quantized absolute coefficient sum `baseAbsSum >= 256`
- DCT-II real fractional-rate density `R0 / (W*H) >= 29697.1531` in VVenC SCALE_BITS=15 units

The second threshold is equivalent to approximately `0.906285` fractional bits/sample after multiplying by `FRAC_BITS_SCALE`.

Crucially, `baseAbsSum` is already computed inside `TrQuant::transformNxN()` as `uiAbsSum`. The patch exposes that existing value through an optional output pointer; inactive blocks therefore do not require a second coefficient scan.

## 3. Development-set evidence for the free gate (rule 0)

Held-out-style results from the uploaded activation analysis:

| sequence | activation | QARD-prune recall | conditional prune | estimated net saved time |
|---|---:|---:|---:|---:|
| AerialCity | 3.041% | 36.31% | 67.63% | +633,867,588 |
| Balboa | 2.113% | 35.06% | 76.54% | +1,142,511,234 |
| BranCastle2 | 2.829% | 36.96% | 62.73% | +1,441,129,000 |
| Gaslamp | 0.922% | 28.57% | 67.21% | +704,304,214 |

Weighted across the four development sequences:

- activation rate: ~2.015%
- conditional prune rate among activated blocks: ~66.84%
- retained fraction of all QARD-prunable blocks: ~34.71%

The low QARD-prune recall is not an RD-safety failure: an activation miss merely leaves the full `{0,1,2}` RDO in place. The gate cannot create a new wrong skip because the final prune is still controlled exclusively by the calibrated QARD lower bound.

## 4. New configuration

New parameter:

`LardLfnst21Stage3RdeActivationProfile`

- `0`: all eligible Model-3 blocks evaluate QARD (backward-compatible QARD-All)
- `1`: free DCT2 AbsSum + rate-density selective gate

Recommended final selective profile:

```text
LFNST=1
LardLfnstSkip=21
LardLfnst21Stages=123
LardLfnst21Profile=5
LardLfnst21Stage2Profile=12
LardLfnst21Stage2HighCostMode=1
LardLfnst21Stage2Debug=0
LardLfnst21Stage3Mode=0
LardLfnst21Stage3RdeMode=2
LardLfnst21Stage3RdeProfile=2
LardLfnst21Stage3RdeModel=3
LardLfnst21Stage3RdeActivationProfile=1
LardLfnst21Stage3RdeRiskMargin=6.845062255859375
LardLfnst21Stage3RdeIdxBits=1
```

`RdeProfile=2` is recommended for the selective profile because the free gate already makes 8x8 activation extremely rare and high-yield; there is no need to exclude 8x8 a priori.

## 5. Implementation details

Modified files:

- `include/vvenc/vvencCfg.h`
- `source/Lib/vvenc/vvencCfg.cpp`
- `source/Lib/apputils/VVEncAppCfg.h`
- `source/Lib/EncoderLib/IntraSearch.h`
- `source/Lib/EncoderLib/IntraSearch.cpp`
- `tools/lard_lfnst/calibrate_skip21_stage3_qard.py`

Key implementation:

1. `xIntraCodingTUBlock()` gets an optional `TCoeff* absSumOut`.
2. For DCT2/lfnstIdx=0 on Skip21 Model-3, the already-computed `uiAbsSum` is captured.
3. `xLardSkip21Stage3RdeEvaluate()` applies the activation gate before `xLardSkip21Stage3RdeBaseStats()`, LFNST-input collection, or QARD response.
4. If activation fails, Stage3 simply returns without a prune decision; the original nonzero LFNST RDO continues.
5. If activation passes, existing Model-3 QARD and the frozen risk rule run unchanged.

## 6. Local validation

A no-LTO Release build of `vvencapp` completed successfully. The build used `-Wno-error=maybe-uninitialized` only to bypass a pre-existing unrelated `LahtpFeatures lard2ndF` GCC warning; the selective Stage3 changes themselves compiled without a new warning.

Synthetic 256x128 10-bit AI smoke:

- Stage1+2, QARD-All with huge risk margin, and QARD-Selective with huge risk margin produced identical SHA-256 bitstreams:
  `558d993b71b082df83f999d2305649037682e848d27e9b0d555cd8db611e803b`
- With risk margin 0, QARD-All logged 128 QARD-evaluated blocks and QARD-Selective logged 58; both encoded successfully and produced the same bitstream on this smoke content.

These are code-path/state checks only, not paper performance results.

## 7. Formal experiment protocol

Treat AerialCity, Balboa, BranCastle2, and Gaslamp as development/calibration sequences because the activation-rule candidate set was discovered using these data. The current activation-search stdout indicates per-sequence rule discovery followed by a union of candidates; therefore the current output must not be described as a fully nested leakage-free LOSO gate search.

Freeze both the activation rule and risk margin before the final test.

Recommended independent-test comparison:

1. Anchor: `LFNST=1 LardLfnstSkip=0`
2. Stage1+2 only: Skip21 Stage1/Stage2, old Stage3 and QARD off
3. Old `S123AB_Q22All_RDMax`
4. QARD-All: Model3, ActivationProfile=0, alpha=0.005 margin
5. QARD-Selective (final): Model3, ActivationProfile=1, alpha=0.005 margin

Use unseen ERP sequences for the final claims. For timing, use paired/interleaved repeats and report median, trimmed/mean timing, positive-repeat count, and standard deviation. Do not enable per-block CSV logging during wall-clock measurement.

Report ordinary PSNR plus WS-PSNR, S-PSNR, and CPP-PSNR BD-rate. Also report Stage3 activation rate, conditional prune rate, candidate reduction, and (from shadow diagnostic runs) wrong-skip probability and regret tail.

## 8. Patch application

The original source tree uses mixed/CRLF line endings. Apply the supplied patch with Git:

```bash
git apply --check --ignore-space-change vvenc_stage3_qard_selective_20260813.patch
git apply --ignore-space-change vvenc_stage3_qard_selective_20260813.patch
```

A plain `patch -p1` may report line-ending mismatches.
