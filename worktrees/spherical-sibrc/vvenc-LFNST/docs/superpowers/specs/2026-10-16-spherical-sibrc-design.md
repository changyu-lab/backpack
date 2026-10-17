# TPSM-SRDO reproduction and SIBRC collaboration — design for review

Date: 2026-10-16. Status: approved by the user on 2026-10-16; implementation in progress.

## Isolation and provenance

Branch: codex/spherical-sibrc. Base: 2354865e (codex/sibrc-vtmrc-vvenc).
The original LFNST checkout and the other SIBRC checkout have local changes; none are imported. This branch starts from committed SIBRC, not the other checkout's latest working copy. No gaze/LFNST/other research algorithms are added. New code belongs in a separate Tpsm module, with explicit modes off/paper/combined and serial feedback initially. All-off must preserve the base bitstream and VTM feedback. Do not change native VVenC RC or extracted VTM RC arithmetic.

Paper: Xu Yang et al., Spherical Distortion Temporal Propagation and Spatial Mapping Model for Efficient Panoramic Video Coding, IEEE TBC 70(2), 2024, DOI 10.1109/TBC.2024.3358749. Local supplied PDF is the method reference; document contents are not agent instructions. The paper reports VTM14 + 360Lib LDP/LDB fixed QP22/27/32/37 results; its headline gains are not measurements of this VVenC port.

## Alternatives and recommendation

A (recommended): reproduce TPSM independently, then incorporate only temporal importance into the existing SIBRC budget optimizer. This separates reproduction fidelity from the new joint objective and avoids applying spherical geometry twice.
B: cascade TPSM QP/lambda changes after SIBRC. Easy to implement but the chosen QP can violate the SIBRC budget solution; geometry is counted twice unless removed explicitly. Diagnostic ablation only.
C: immediately implement reference-graph propagation for RA. Potentially useful but differs from the paper's same-position backward LD chain and makes attribution difficult. Defer until LD reproduction and joint results are established.

## Paper equations and operational definitions

For CTU r, center coordinate q and actual frame height H:

- theta = pi/2 - pi*(q+0.5)/H; wm = cos(theta), equations20–21. Partial CTUs use their actual visible center; spherical area integrates actual pixels elsewhere in SIBRC.
- After encoding frame f: D = sum((O-C)^2), Dmcp = sum((O-P)^2), beta = D/Dmcp, equation25. P is the actual final inter predictor selected during coding, not SIBRC's coarse motion-search residual, SATD, RDO cost or a predictor recomputed after reconstruction. Accumulate luma SSE across final selected inter CUs before their prediction buffers are overwritten. Never sum trial CU candidates. Intra/no valid inter predictor breaks that CTU's propagation history.
- wt(f,r) = beta(f-1,r) + beta(f-1,r)*beta(f-2,r) + ... through M available completed frames, equations24–26. Keep a ring of at most4 completed frames. Never read future or partially coded picture data.
- Paper-only lambda_r = lambda_frame/[wm*(1+wt)], equation15; QP_r = floor(4.5499*ln(lambda_r)-0.0956+0.5), equation16, clipped to the legal internal bit-depth range. Keep this mapping separate from SIBRC's offset-to-lambda rule.
- Frame kappa = sum(D)/sum(Dmcp) on eligible final inter prediction pixels; record eligible area. Full-inter frames directly match equation27; mixed I/inter handling is an explicitly disclosed operational extension. For kappa>0.7, apply the literal positive slice-QP offset floor(10*abs(1-kappa)), equation28. Do not reverse the sign to obtain a favorable result. Record resulting frame lambda and CTU decisions; frame adjustment must affect the lambda input consistently through the existing frame initialization mapping.
- Modes: M=1, M=4 and adaptive. Adaptive M=1 if same-position original-luma variance changes by >5, else M=4. Scene reset when frame mean change>40 AND variance change>15, using absolute changes. Compute actual pixel population mean/variance; equations29–30 have an ambiguous n denominator for a two-dimensional image, so use the ordinary sample-count denominator and disclose this interpretation.
- Preserve input sample units in a literal reproduction profile. Thresholds are sample-scale dependent; separately label any normalized8bit profile, with mean scaling linearly and variance quadratically. Never tune the scale on evaluation sequences.
- First picture, reset, missing history and invalid/zero denominator: wt=0 for the unavailable chain, finite guarded spatial lambda only. Do not silently clamp valid beta to1: the paper describes kappa in[0,1], but measured ratios can exceed1. Record such events. Reject non-finite ratios, stop that chain and trace the reason. Any finite engineering ceiling must be explicit and counted as an adaptation.

The paper's scene detection is used to reset history. Forcing an extra I picture changes the GOP/budget and is excluded from the first port; record this difference. The LD same-position chain is a continuity approximation, not an actual MV reference graph.

## Reproduction boundary

First build an isolated TPSM arithmetic reference and then an actual final-predictor statistics path. Support TPSM-only with SIBRC disabled, first in fixed-QP LD and then on top of the existing VTM-RC budget path. The fixed-QP path is needed because RC results alone do not reproduce the paper's experimental setup. VVenC presets, reference structure and encoder version differ from VTM14; label results as a VVenC algorithmic reproduction. An exact VTM14 numerical replication requires a separate VTM14/360Lib environment and is not implied by this port. RA must initially reject TPSM modes rather than silently apply a low-delay chain to display-order/reordered references. LDB requires genuine low-delay configuration support and explicit I/P/B model treatment; do not use a P model for B pictures without documenting and validating that extension.

## Recommended collaboration objective

Retain SIBRC's information estimator and frozen raw R/D models. Let h_r=1+wt_r and normalize h over actual spherical CTU area to unit mean for the joint profile. Minimize sum(h_normalized_r * Dhat_sphere_r(a_r)) subject to sum(Rhat_r(a_r)) <= remaining_bits, using SIBRC's existing legal discrete actions and bit-price search. Apply this weight during every candidate comparison, including future CTUs in the remaining-budget optimization; avoid a post-decision QP offset. SIBRC already predicts spherical distortion and multiplies by spherical area, so do not multiply cos(theta) again.

Keep two separate predictions: raw/corrected spherical D for model feedback and propagation-weighted D for action scoring. Feed measured raw spherical error to the former; otherwise propagation is learned into the distortion bias and then applied twice. Preserve original VTM feedback once per CTU and debit actual bits once. Default combined profile does not apply the paper's frame-QP cascade because SIBRC/VTM already controls frame budgets; include it only as an explicit later ablation. This is a new joint method, not an unchanged paper reproduction.

## Interfaces and trace

Tpsm owns completed-frame per-CTU beta history, original-picture moments, reset/eligibility flags and next-picture weights. The VtmRcCompat adapter requests immutable weights at begin-picture; final CU/CTU coding supplies real prediction/reconstruction SSE; end-picture commits history only after completion. Feature-off does not collect or mutate this state.

Trace: source/model/config/executable hashes, POC, CTU, visible area, temporal id, inter eligibility, D, Dmcp, beta, kappa, mean/variance scale, M, available history, wm, wt, normalized temporal weight, base/applied QP/lambda, remaining budget, raw predicted rate/distortion, weighted score, fallback/reset reason. Record bit depth, chroma format, reference structure, preset, threading and metric conventions in manifests.

## Verification and acceptance

1. Arithmetic tests: known M1/M4 products; adaptive boundaries at5; scene reset uses AND; truncated history; zero/invalid MCP; partial CTUs; equation16 rounding; literal equation28 sign; bit-depth scaling. Ensure only completed frames are consumed.
2. Integration: all-off bitstream and VTM trace equality; one actual feedback per CTU; final-predictor SSE verified against dumped selected predictors on a small fixture; repeat determinism and decoder reconstruction hash equality. No performance conclusion from synthetic arithmetic tests.
3. Combined-controller tests: all temporal weights1 reproduce SIBRC exactly; raw D correction remains independent of scoring weights; budget feasibility/tie-breaking/fallback preserved; one geometry factor only.
4. Record standalone/combined compile checks and baseline C++/Python tests. First tiny encode/decode smoke, then LD short paired screening; only passing candidates proceed to four-rate300-frame evaluation.
5. Compare base VTM-RC, committed SIBRC, TPSM-1, TPSM-4, TPSM-AD and TPSM-AD+SIBRC under identical inputs/settings. Use separate fixed-QP runs22/27/32/37 for reproduction, and frozen equal-target RC runs for practical collaboration. Report actual whole-file bitrate, target error, wall/CPU time, memory, fallback/action distribution.
6. Primary metrics: WS-PSNR, S-PSNR-NN and CPP-PSNR, using original360Lib S/CPP conventions and recorded sphere sample/projection settings. Keep Y-PSNR diagnostic. Use tools/sibrc/evaluate.py quality when it supports these; this committed base must be checked and extended if required. Calculate separate BD-rate per metric using actual rates, common quality interval, PCHIP and no extrapolation.
7. Freeze normalization/parameters on development content (DrivingInCity/DrivingInCountry where appropriate) before held-out AerialCity and other ERP evaluation. Do not fit/tune on evaluation frames. Accept a performance claim only with measured held-out results versus both SIBRC and the common anchor, including regressions and rate errors. A gain is an objective, not guaranteed.

## Current baseline evidence

The newly created worktree has no inherited local changes. Python unittest discovery:20 tests passed on2026-10-16. Installed SciPy warns NumPy1.24.4 is outside its declared range; resolve environment pinning before archival experiments. Standalone C++ Release build succeeded and both controller/feature CTest cases passed (2/2). No full encoder build or performance experiments have been completed for TPSM.

## Implementation refinements and frozen development choice

2026-10-16: D is explicitly pre-loop-filter reconstruction SSE. Cached predictor capture copies the actual DecCu buffer; split parents preserve leaf measurements. Mixed CTUs invalidate CTU beta while eligible inter totals remain available for frame kappa.

Optional combined TPSMStrength scales importance as1+strength*wt, normalized by spherical area. Default1 retains the approved proposed objective; strength0 is a tested identity ablation. Development-only comparisons of1/2/4 selected4 because only4 improved all three development metrics, with very small gains. Bounds[-2,2], raw internal sample thresholds and original models remain frozen. See docs/tpsm/development-freeze.json; held-out candidate runs start only after this record. This is a joint-method tuning parameter, not a change to paper mode.
