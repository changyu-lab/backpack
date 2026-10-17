# AerialCity 4K LDP 17-frame remote results

Remote: rycpu2.9gpu.com:36016. Isolated directory: `/root/spherical_sibrc_20261016_aerial4k_ldp17`. Frozen algorithm revision: `36c604e8`. 3840x1920, 30 fps, first 17 frames, LDP GOP8, faster preset, serial coding. Source prefix SHA256 and all four anchor bitstreams match the existing reference exactly.

Historical target bitrates are reused unchanged: 359510, 792057, 2196112, 11820750 bps. Their origin is 300-frame CQP experiments; these are not newly generated 17-frame CQP targets. Actual complete Annex-B file rates include the initial I frame.

TPSM uses paper mode1 with adaptive chain and default sample scale. SIBRC and joint use both optional repairs, unchanged v1 models, QP offsets [-2,2]. Joint uses mode2 with temporal strength4. No model refit or test-sequence parameter search.

## BDBR relative to the existing VTM anchor

Negative is better. Arithmetic mean of per-picture dB; WS-PSNR, original360Lib S-PSNR-NN and CPP-PSNR. PCHIP integration on each pair's overlapping quality interval without extrapolation.

| Method | WS-PSNR | S-PSNR-NN | CPP-PSNR |
|---|---:|---:|---:|
| TPSM adaptive | -40.8264% | -40.8713% | -40.5591% |
| SIBRC repaired | -0.4717% | -0.4527% | -0.4761% |
| TPSM + SIBRC repaired | -0.3528% | -0.3443% | -0.3598% |

## Joint relative to each standalone method

| Reference | WS | S-NN | CPP |
|---|---:|---:|---:|
| SIBRC repaired | +0.1227% | +0.1119% | +0.1201% |
| TPSM adaptive | +67.3985% | +67.5534% | +66.6115% |

## All measured operating points

| Method | Point | Target Mbps | Actual Mbps | Rate error | WS | S-NN | CPP |
|---|---:|---:|---:|---:|---:|---:|---:|
| VTM anchor | R1 | 0.359510 | 1.189581 | +230.890% | 33.18628 | 33.18318 | 33.32068 |
| VTM anchor | R2 | 0.792057 | 1.679802 | +112.081% | 33.96000 | 33.95175 | 34.13174 |
| VTM anchor | R3 | 2.196112 | 2.628353 | +19.682% | 34.90836 | 34.90128 | 35.14325 |
| VTM anchor | R4 | 11.820750 | 11.772649 | -0.407% | 39.21086 | 39.20878 | 39.84384 |
| TPSM adaptive | R1 | 0.359510 | 1.003285 | +179.070% | 33.40770 | 33.40526 | 33.54402 |
| TPSM adaptive | R2 | 0.792057 | 1.388654 | +75.322% | 34.36067 | 34.35366 | 34.54651 |
| TPSM adaptive | R3 | 2.196112 | 2.198174 | +0.094% | 36.31069 | 36.30750 | 36.62351 |
| TPSM adaptive | R4 | 11.820750 | 11.281228 | -4.564% | 39.29641 | 39.29389 | 39.94101 |
| SIBRC repaired | R1 | 0.359510 | 1.189581 | +230.890% | 33.18628 | 33.18318 | 33.32068 |
| SIBRC repaired | R2 | 0.792057 | 1.679802 | +112.081% | 33.96000 | 33.95175 | 34.13174 |
| SIBRC repaired | R3 | 2.196112 | 2.628353 | +19.682% | 34.90836 | 34.90128 | 35.14325 |
| SIBRC repaired | R4 | 11.820750 | 11.869849 | +0.415% | 39.30526 | 39.30058 | 39.94954 |
| TPSM + SIBRC repaired | R1 | 0.359510 | 1.189581 | +230.890% | 33.18628 | 33.18318 | 33.32068 |
| TPSM + SIBRC repaired | R2 | 0.792057 | 1.679802 | +112.081% | 33.96000 | 33.95175 | 34.13174 |
| TPSM + SIBRC repaired | R3 | 2.196112 | 2.628353 | +19.682% | 34.90836 | 34.90128 | 35.14325 |
| TPSM + SIBRC repaired | R4 | 11.820750 | 11.866504 | +0.387% | 39.28771 | 39.28450 | 39.93044 |

## Verification and interpretation

All 16 encodes independently decoded; reconstruction hashes matched. Decoder POCs are exactly 0..16. All metric arrays contain 17 finite values. Four Linux CTests and 24 Python tests passed. Local archive verification and independent recalculation reproduced all 36 pairwise metric BDBRs within 1e-10 percentage points.

The first three SIBRC and joint operating points have zero P-CTU QP offsets and are bit-identical to anchor. Controller fallback exceeds 99.9% there. Final per-point diagnostics are in controller-diagnostics-final.json. Joint does not show additional gain over repaired SIBRC.

TPSM has the best measured curve under this protocol. The large negative BDBR must be read alongside severe short-sequence target overshoot (anchor R1 +230.89%, R2 +112.08%; TPSM R1 +179.07%, R2 +75.32%). This is not evidence for a 40% gain under strict bitrate matching, long sequences, or unseen content.

Standalone paper TPSM includes spatial lambda/QP and frame decisions. The current joint method injects temporal importance into SIBRC; it does not retain that complete standalone decision path. These results do not identify pure temporal-propagation gain.

## Reproduction and evidence

Frozen source archive was exported from git commit36c604e8. Source archive and Linux executable hashes are in evidence/protocol.json. Linux build preserved algorithm source; -Wno-error=misleading-indentation allowed existing single-line formatting warnings while all other errors remained enabled. Initial strict build failure and the first rejected TPSM invocation (joint-only strength parameter mistakenly applied to standalone mode) are preserved; corrected commands produced the results.

The evidence directory contains commands, original anchor metadata, per-frame quality arrays, hashes, compressed CTU traces/logs, runner and audit scripts. integrity.json maps every archived file and verifies lossless log compression. Remote bitstreams and executable remain in the isolated experiment directory. Temporary reconstructed YUVs were removed only after metric and decoder-hash checks; existing experiments were untouched.
