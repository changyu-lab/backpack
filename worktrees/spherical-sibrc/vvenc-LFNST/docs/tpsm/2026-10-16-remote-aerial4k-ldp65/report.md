# AerialCity 4K LDP 65-frame remote comparison

SIBRC is best in this test (WS-BDBR -4.1799%). Joint WS-BDBR is -3.7807%, a +0.4502% regression relative to SIBRC. Standalone TPSM regresses by +22.5590%. The largest rate errors are 0.310% for anchor, 0.391% for SIBRC, 0.403% for joint, and 2.608% for TPSM.

3840x1920, 30 fps, frames0..64, LDP GOP16, faster preset. Frozen algorithm revision 36c604e8, Linux executable reused unchanged from the verified 17-frame experiment. Independent directory: /root/spherical_sibrc_20261016_aerial4k_ldp65.

## Targets calculated from 300-frame logs

Targets are independently parsed from completed 300-frame AerialCity CQP logs under /root/sibrc-ldp16-300-20261015/runs/AerialCity/cqp. Calculation: summary bitrate in kbps multiplied by 1000 and rounded half up to integer bps. All four 300-frame POC sets and source prefix hashes were verified.

| Point | CQP | Log kbps | Target bps |
|---|---:|---:|---:|
| R1 | 37 | 365.2984 | 365298 |
| R2 | 32 | 818.8552 | 818855 |
| R3 | 27 | 2261.4968 | 2261497 |
| R4 | 22 | 11859.1576 | 11859158 |

The 65-frame test uses the same GOP16 configuration as the 300-frame target logs. The previous 17-frame experiment used GOP8 and different historical targets; changes between the two experiments cannot be attributed solely to frame count.

## BDBR relative to a fresh 65-frame VTM anchor

Negative is better. Actual complete Annex-B rates include the initial I frame. Quality is the arithmetic mean of per-picture dB; original360Lib S-PSNR-NN and CPP-PSNR. PCHIP is integrated over each pair's overlapping quality interval without extrapolation.

| Method | WS-PSNR | S-PSNR-NN | CPP-PSNR |
|---|---:|---:|---:|
| TPSM adaptive | +22.5590% | +22.4983% | +21.1052% |
| SIBRC repaired | -4.1799% | -4.0940% | -4.2661% |
| TPSM + SIBRC repaired | -3.7807% | -3.7468% | -3.7967% |

## Joint relative to each standalone method

| Reference | WS | S-NN | CPP |
|---|---:|---:|---:|
| SIBRC repaired | +0.4502% | +0.4002% | +0.5272% |
| TPSM adaptive | -21.4957% | -21.4234% | -20.5696% |

## Every operating point

| Method | Point | Target Mbps | Actual Mbps | Error | WS | S-NN | CPP |
|---|---:|---:|---:|---:|---:|---:|---:|
| VTM anchor | R1 | 0.365298 | 0.366428 | +0.309% | 32.43795 | 32.42352 | 32.54131 |
| VTM anchor | R2 | 0.818855 | 0.820287 | +0.175% | 35.59058 | 35.58231 | 35.82932 |
| VTM anchor | R3 | 2.261497 | 2.263473 | +0.087% | 37.73065 | 37.72626 | 38.16427 |
| VTM anchor | R4 | 11.859158 | 11.862288 | +0.026% | 39.70954 | 39.71122 | 40.39609 |
| TPSM adaptive | R1 | 0.365298 | 0.366816 | +0.416% | 33.28785 | 33.27472 | 33.42180 |
| TPSM adaptive | R2 | 0.818855 | 0.822524 | +0.448% | 34.77063 | 34.76220 | 34.99466 |
| TPSM adaptive | R3 | 2.261497 | 2.320468 | +2.608% | 37.29791 | 37.29381 | 37.71768 |
| TPSM adaptive | R4 | 11.859158 | 12.025170 | +1.400% | 39.82649 | 39.82807 | 40.51884 |
| SIBRC repaired | R1 | 0.365298 | 0.366724 | +0.390% | 32.46958 | 32.45287 | 32.57553 |
| SIBRC repaired | R2 | 0.818855 | 0.820198 | +0.164% | 35.68594 | 35.67816 | 35.93237 |
| SIBRC repaired | R3 | 2.261497 | 2.264411 | +0.129% | 37.80830 | 37.80013 | 38.25118 |
| SIBRC repaired | R4 | 11.859158 | 11.869104 | +0.084% | 39.83569 | 39.83612 | 40.53832 |
| TPSM + SIBRC repaired | R1 | 0.365298 | 0.366768 | +0.402% | 32.46725 | 32.45816 | 32.57311 |
| TPSM + SIBRC repaired | R2 | 0.818855 | 0.820375 | +0.186% | 35.69981 | 35.69140 | 35.94690 |
| TPSM + SIBRC repaired | R3 | 2.261497 | 2.264843 | +0.148% | 37.79069 | 37.78515 | 38.23154 |
| TPSM + SIBRC repaired | R4 | 11.859158 | 11.867177 | +0.068% | 39.80317 | 39.80276 | 40.49782 |

## Scope and verification

SIBRC and joint retain the two optional bias/intra-anchor repairs, v1 I/P models, QP bounds[-2,2]. Joint temporal strength is 4. Standalone TPSM uses adaptive paper mode1; joint uses mode2. No retraining or sequence-specific parameter tuning.

All 16 streams were independently decoded with matching reconstruction hashes. Decoder POCs are exactly 0..64. All metric arrays contain 65 finite values. R2 anchor also matches the historical remote encoder bit-for-bit under the same 65-frame command. Frozen assets are unchanged. Local download integrity and all 36 pairwise metric BDBRs were independently verified.

Controller fallback and nonzero P-CTU offsets are recorded per rate in evidence/controller-diagnostics.json. temporal-quality-diagnostics.json reports post-hoc I/early-P/later-P quality differences within these 65-frame runs; it is not a causal comparison with the previous 17-frame encode. Standalone TPSM includes spatial/frame decisions, whereas the current joint injects temporal importance into SIBRC; measured standalone gains do not establish pure temporal gain. A single 65-frame sequence is not full 300-frame or unseen-content validation.

Evidence includes the original 300-frame CQP logs and run records, copied GOP16 configuration, command lines, hashes, per-frame qualities, compressed CTU traces and logs, runner and audit scripts. integrity.json verifies the byte-preserved originals and gzip transformations. Remote bitstreams and the executable remain available. Own reconstruction files were removed only after metrics and decoder checks.
