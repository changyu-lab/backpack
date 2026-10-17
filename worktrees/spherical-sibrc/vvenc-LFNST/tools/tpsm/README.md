# Isolated TPSM-SRDO reproduction and SIBRC collaboration

Branch: `codex/spherical-sibrc`, committed SIBRC base `2354865e`. Other research checkouts and their uncommitted changes are excluded.

## Encoder modes

- `TPSMMode=0` (default): unchanged coding and no TPSM collection.
- `TPSMMode=1`: paper-only spatial/temporal lambda and equation16 QP mapping; `SIBRCMode=0`. Works in CQP or with independent VTM RC.
- `TPSMMode=2`: SIBRC's budget solver scores raw predicted spherical distortion times normalized temporal importance. Requires `SIBRCMode=3` and VTM RC. The existing spherical area is used once. Raw model predictions and bias feedback never include temporal importance.
- `TPSMChain=1`, `4`, or `0` (adaptive, default). `TPSMTrace=<fresh CSV>` is mandatory for enabled modes.
- `TPSMStrength=1` is the proposed joint objective. Optional development tuning uses `1 + strength*wt`, spherical-area normalized to mean1, with strength in[0,4]. Strength0 must reproduce SIBRC exactly. This parameter is rejected in paper mode when different from1. No strength is selected using held-out outcomes.
- `TPSMNormalize8Bit=0` (default) keeps original-picture moments in internal sample units. Set1 for a separately labeled8bit-normalized threshold adaptation. Ratios are scale invariant, variance thresholds are not.
- `TPSMAudit=<fresh binary>` exports original/prediction/reconstruction triples for final selected inter CUs. Use only for small fixtures: retaining trial snapshots until CTU completion increases memory.

Use the serial LDP configuration in `docs/vtm23-rc/aerialcity16_ldp.cfg`; turn off native RC, LMCS, MCTF, QPA, BIM, luma QP adaptation, STA, lookahead, picture/CTU threading, WPP and tiles. Standard lossy coding only. Reordered pictures are rejected. Combined B pictures are rejected because the frozen SIBRC model has only I/P identities. Paper-only low-delay B is not a validated experimental claim.

## Numerical and encoder definitions

The spatial factor is the cosine at the visible CTU center. Temporal importance is the sum of backward beta products from at most4 completed pictures, using matching CTU positions. Adaptive length is1 for absolute original-luma population variance change>5, else4. Scene reset uses BOTH frame mean change>40 and variance change>15. Intra pictures reset history. A mixed intra/inter CTU breaks its own history; frame kappa still uses the available eligible inter pixels. Missing/invalid/zero-MCP history terminates that chain. Finite beta>1 is preserved. Overflow fails explicitly rather than silently clipping beta.

D and MCP SSE come from the actual accepted leaf CU, with CU copies retaining the measured scalars. Split parents preserve child measurements. Cached reconstruction produces prediction in DecCu's private buffer, so that actual predictor is copied to CS before capture. Ordinary skip/inter/merge use CS prediction. IBC is ineligible for temporal propagation.

**D uses pre-loop reconstruction (before deblocking, SAO and ALF).** End-picture commits saved statistics; it does not replace D with filtered-reference distortion. The paper does not explicitly establish this sampling point, so this is an operational VVenC port boundary. Audit verifies saved final pixel arithmetic and non-overlapping CU eligibility; code review additionally checks predictor-buffer origin. Audit alone cannot prove that a wrong but internally consistent predictor source was not used.

The literal positive frame-QP cascade is retained in paper mode. CQP reruns the existing frame lambda mapping after the offset; VTM RC uses the same declared QP-to-lambda rescaling as its adapter. Joint mode leaves frame budgeting/cascade to SIBRC/VTM. Near-integer floating-point noise in equation28 is snapped within8 machine epsilons before floor. Legal QP clipping and invalid-history handling are disclosed engineering guards. Scene detection resets history without forcing a new I picture.

This is an algorithmic port of Yang et al., IEEE TBC2024, DOI10.1109/TBC.2024.3358749, not an exact numerical VTM14/360Lib replication. Preset/reference structure, variance denominator interpretation, mixed-pixel eligibility and guard policies are recorded differences. The paper's published gains are not this branch's measured gains.

## Verification

Configure standalone CMake projects in `test/tpsm` and `test/sibrc`, build Release, then run CTest. Tests do not depend on disabled Release assertions.

```text
python -m unittest discover -s tools/tpsm -p "test_*.py"
python -m unittest discover -s tools/sibrc -p "test_*.py"
python tools/tpsm/smoke.py --help
python tools/tpsm/screen.py --help
python tools/tpsm/audit.py <audit.bin> <trace.csv>
```

`smoke.py` creates fresh512x256 synthetic and192x192 partial fixtures, runs coding/decoding/independent pixel audits, disabled identity, deterministic repeat, optional independently built baseline identity, and an MTT-depth3 fixture that must select cached inter CUs. Supply `--encoder`, `--decoder`, `--output`, optionally `--baseline`.

## Performance protocol

`screen.py --stage cqp` runs QP22/27/32/37 for anchor and paper1/4/AD. It writes `targets.json` from the same sequence's actual anchor rates. `--stage rc --targets <that file>` uses identical targets across anchor/SIBRC/paper/joint. `--profiles anchor sibrc joint --strength <development-frozen value>` narrows a tuning run. Both stages require original8bit420 source, explicit dimensions/frames/fps and fresh output directory. Inputs are never modified. Source prefix, tools, stats, models, frozen targets and originating CQP manifest are hashed. Duplicate profiles are rejected. A STOP file stops between jobs; stopped experiments are not complete comparisons.

Quality always includes WS-PSNR, original360Lib S-PSNR-NN and CPP-PSNR; Y-PSNR remains supplementary. Actual bitrate includes the complete Annex-B file, including the first I picture and headers. The S/CPP executable and sphere file are mandatory, never silently approximated. See `metrics360/README.md` and its recorded source hashes. BD-rate is separate for each metric, using actual rates, common quality interval, PCHIP log-rate integration and no extrapolation. Decoder output must match encoder reconstruction SHA256 at every point.

Short16frame/reduced-resolution screening is not evidence of300frame/full-resolution/general performance. Keep negative results and target-rate errors. Freeze any tuning on Driving content before inspecting held-out AerialCity candidate quality. Use the same commands with full ERP sources and at least300frames for a formal evaluation after a candidate survives screening. Training and held-out evaluation identities remain separate; no recalibration is performed by the runner.

Installed Anaconda SciPy warns that NumPy1.24.4 is outside its declared range. Unit/metric runs complete, but this existing environment is not advertised as a pinned archival runtime. Record exact versions with formal experiments.

## Measured adoption decision

See `docs/tpsm/2026-10-16-results.md`. The strength4 joint candidate failed held-out16frame screening and is not adopted. Expanded independent models and wider action bounds did not improve the development result. The implementation stays default-off. The runner accepts `--model-prefix` and `--qp-radius` for explicit, hashed ablations; never report calibration/range changes as propagation-only gains.


## Optional SIBRC repairs

`--SIBRCBiasRepair=1` accumulates the residual against the already bias-corrected prediction (gain 0.1, unchanged log(4) bound and per-picture reset). The legacy extra decay remains the default.

`--SIBRCIntraAnchor=1` preserves VTM decisions on all intra pictures, including periodic refresh; P pictures still use SIBRC. Both options require SIBRCMode=3 and default to off. They can be used independently. In bypassed I trace rows the offset and prediction columns are zero; VTM still receives actual bits and distortion exactly once.

Use `screen.py --bias-repair --intra-anchor` for paired evaluation. These options fix calibration/control behavior; they do not repair out-of-domain R/D models or guarantee bitrate feasibility. Intra anchoring can still exceed a very low short-sequence target. Treat the AerialCity sequence previously inspected during diagnosis as a regression sequence, not new unseen validation.


## Experimental finite CTU contrasts

`VTMDecisionRecord` writes a strict ordered `VTM_REPLAY_V1 frames ctus` schedule: one `poc -1 qp lambda` row for picture initialization, then `poc ctu qp lambda` rows for all CTUs. `VTMDecisionReplay` freezes that complete requested schedule. Record and replay are mutually exclusive. An optional `VTMProbePOC`, `VTMProbeCTU`, `VTMProbeOffset=-1|1` changes only one P CTU and scales its lambda by2^(offset/3). These research options require VTM RC and default off.

Frozen requests do not freeze coding modes, prediction choices, entropy state or loop filtering. Use the zero-replay bitstream identity gate before interpreting an intervention. `probe_smoke.py` checks picture initialization, exact QP/lambda changes, CTU row coverage, prefix frames and independent decode hashes. `marginal_run.py` first verifies the real-sequence baseline against an expected historical hash, then verifies zero replay, freezes twelve CTUs at POC8 before any probe outcome, and runs plus/minus probes. It selects four samples each below/equal/above temporal weight1, requiring current full-inter eligibility, a complete configured prior beta chain with no intervening reset, and at least32 baseline bits. If diversity is insufficient it stops and reports, rather than manufacturing samples.

The primary response is strictly future frame-global spherical luma SSE contrast divided by current-frame SSE contrast when the denominator is positive. Current and future bit changes, raw future SSE, sum of future per-picture WS-PSNR differences, nonpositive costs and invalid denominators remain explicit. Spearman/permutation diagnostics on a stratified one-frame sample are descriptive; they do not establish population inference or a motion-isolated derivative. Only requested QP/lambda decisions are frozen, so actual future coding bits and modes can change. No model or fusion strength is tuned by this experiment.
