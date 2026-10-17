# TPSM temporal-weight marginal-response experiment

本组结果未提供支持：当前 TPSM 权重能够可靠排序所测未来有限差分收益。主分析 rho=-0.0552、描述性置换 p=0.8914，只有10个当前帧失真改善的有效比值样本；其中5个后续总失真反而增加。高权重4个样本中2个出现负未来收益。这个小样本结果不能证明论文理论无效，也不能证明联合回归的唯一原因。

AerialCity3840x1920, LDP GOP16,65 frames, target818855bps derived from the completed300-frame CQP log. Repaired SIBRC v1 baseline. Frozen experiment source11b9236d; default algorithm behavior unchanged. Remote directory /root/spherical_sibrc_20261016_marginal.

## What was held fixed

Recorded and replayed picture-initialization and all requested CTU QP/lambda decisions. Baseline and zero replay are bit-identical to the historical65-frame SIBRC R2 (adf87f21575af859165eedc3a9e45447842372508fcafda7a8522775b2b8dccb). Each intervention changes exactly one CTU at POC8 by-1 or+1 QP with lambda2^(offset/3). All other requested decisions remain fixed. Coding modes, references, prediction, entropy and filtering can respond. Actual current/future bit changes are measured, not constrained to zero.

## Sample and pre-outcome feasibility amendment

Twelve CTUs (four each wt<1,wt=1,wt>1) were selected with seed20261016 from current full-inter CTUs with a complete configured preceding beta chain, no intervening scene reset and at least32 baseline bits. POC16 had onlyone eligible high-weight CTU, so baseline-only feasibility inspection selectedPOC8, which has26 low/43 neutral/4 high candidates and56 future frames. The frozen sample agrees with the independently archived local pre-outcome selection. No perturbation result informed sampling or strength/model tuning.

## Primary response and ranking

Let D be final-reconstruction frame-global spherical luma SSE. For each CTU, the central finite contrast is current improvement C=D_plus(POC8)-D_minus(POC8), future improvement F=sum over POC9..64 of(D_plus-D_minus), and observed amplification A=F/C only when C>0. Negative future responses remain; C<=0 is explicitly invalid for A and retained in the raw response analysis. This is a finite global contrast, not an analytic derivative or motion-isolated propagation coefficient.

| Ranking | Valid n | Spearman rho | Two-sided permutation p |
|---|---:|---:|---:|
| TPSM wt vs observed amplification A | 10 | -0.05521888072258639 | 0.8914 |
| TPSM wt vs raw future SSE improvement F | 12 | -0.29186115364847715 | 0.362 |

Permutation uses19999 shuffles and seed20261016. This small stratified one-frame sample has shared-frame dependencies and deliberate sampling; the p value is descriptive, not population-level significance. Raw F is additionally content/area/current-improvement confounded.

## Every frozen CTU

| CTU | Stratum | TPSM wt | Current SSE reduction C | Future SSE reduction F | F/C | Current extra bits | Future extra bits | Future mean WS-PSNR difference dB |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 262 | low | 0.980133 | +67737.372091 | +19905816.878535 | +293.867569 | +464 | -1632 | +0.01695130 |
| 265 | low | 0.982893 | +74728.868054 | +8239231.657327 | +110.255004 | +896 | -632 | +0.00721690 |
| 281 | low | 0.996850 | -31423.463917 | +12597296.100799 | invalid | -176 | -1768 | +0.01186926 |
| 294 | low | 0.992144 | +82425.147985 | +4994128.133620 | +60.589859 | +512 | +1416 | +0.00481717 |
| 219 | neutral | 1.000000 | +370.788267 | -2694211.677102 | -7266.172957 | +0 | -1928 | -0.00271602 |
| 266 | neutral | 1.000000 | -39532.183188 | -11281713.664169 | invalid | -32 | +3280 | -0.01079311 |
| 320 | neutral | 1.000000 | +6035.087586 | -11000924.022796 | -1822.827567 | +16 | -72 | -0.00926568 |
| 414 | neutral | 1.000000 | +50532.652168 | -9287664.678501 | -183.795314 | +56 | +2288 | -0.00798777 |
| 223 | high | 3.954074 | +203507.037827 | -5472437.801112 | -26.890656 | +872 | +80 | -0.00382697 |
| 253 | high | 3.876417 | +19961.315683 | +8258944.817142 | +413.747518 | +1072 | -3216 | +0.00715449 |
| 264 | high | 3.958291 | +55738.177720 | +9273414.857653 | +166.374561 | +552 | +384 | +0.00795455 |
| 283 | high | 3.917769 | +29864.317968 | -2910348.644184 | -97.452373 | +112 | -6144 | -0.00222710 |

Current extra bits compare the entire perturbed frame, not a CTU-local isolated entropy cost. Future bits can change at fixed QP/lambda because prediction and mode decisions respond. Per-bit benefit is reported only for positive current cost; nonpositive costs are retained. Both one-sided comparisons against baseline and the central contrast are available in remote-evidence/run/results.json.

## Descriptive counts and strata

Valid amplification samples: 10/12. Negative future responses: 6/12. Nonpositive current extra-bit costs: 3/12. Minus-probe unchanged streams: 1; plus-probe unchanged streams: 0.

| Stratum | n | Valid A n | Median wt | Median A | Negative F n |
|---|---:|---:|---:|---:|---:|
| low | 4 | 3 | 0.9875186562291365 | 110.25500414916776 | 0 |
| neutral | 4 | 3 | 1.0 | -1822.8275673930866 | 4 |
| high | 4 | 4 | 3.935921295937048 | 69.74195244628064 | 2 |

## Supplementary window sensitivity

These are post-hoc sensitivity analyses; the primary response remains the full56-frame future. All fixed windows are reported. The configured-chain window has variable length and cannot separate a chain-length counting effect from propagation quality.

| Future window | n | Spearman rho with F_window/C | Permutation p |
|---|---:|---:|---:|
| 1 | 10 | -0.17792750455055617 | 0.63185 |
| 4 | 10 | 0.27609440361293197 | 0.44675 |
| 16 | 10 | -0.03067715595699244 | 0.9457 |
| 56 | 10 | -0.05521888072258639 | 0.8914 |
| configured_chain | 10 | 0.1533857797849622 | 0.6781 |

## Verification and limits

Adaptive chain length is fully confounded with the broad strata here: every high-weight sample uses M4, and every low/neutral sample uses M1. Exact chain lengths are preserved in selection.json and summarized in summary.json; this experiment cannot separate chain-length effects from beta or content effects.

All26 streams independently decoded with matching reconstruction hashes and exactly65 decoder POCs. Full picture-initialization and requested CTU schedules were independently compared: only the intended action differs by the specified QP/lambda. All POC0..7 reconstructed-frame hashes, bits and SSE match baseline. Selection, all paired contrasts and both permutation results were independently recomputed after download. Baseline per-picture WS-PSNR matches the preceding65-frame reference. Remote31 Python tests and2 replay/TPSM CTests passed.

Some positive denominators remain small or cancellation-prone: CTU219 has current frame-global SSE improvement about371 and amplification about-7266. Positivity alone does not guarantee stable ratios. The rank statistic is descriptive and should not calibrate a numerical propagation multiplier from these values.

TPSM beta is measured from selected inter reconstruction before deblocking/SAO/ALF; the measured response here is filtered final frame-global spherical reconstruction SSE. This tests practical predictive usefulness across those definitions, not equation-level numerical equivalence. Modes and actual future bit costs can change despite fixed requested QP/lambda, so the response is not a pure isolated reference-error derivative.

The experiment tests a local importance proxy at one frame and one operating point. It does not validate or invalidate the entire paper, establish coding gain, identify pure motion propagation, or separate chain length from beta/content correlation. It also does not establish whether strength4 is well calibrated. Full-case costs and counterexamples remain visible.

The user explicitly authorized all12 source/test/statistical files; both earlier automatic transfer rejections and their resolution were respected. Raw uploaded payload hashes and archive are preserved. The previous preparation-state/report files document the earlier identity gates and pre-outcome selection. The final executable is retained remotely as vvencFFapp-probe.

Evidence: compressed original CTU traces/logs, per-frame SSE and reconstruction hashes, bitstreams, commands, record/replay schedule, frozen selection/protocol, independent audit, and uploaded12-file payload. No reconstructed YUV remains after verified evaluation. The archive-integrity.json records every raw/downloaded file hash and any lossless gzip transform.
