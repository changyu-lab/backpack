# TPSM marginal-importance validation: implementation and identity gates

Status: experiment prepared,24 scientific perturbation cases have NOT run. Additional remote script transfer is awaiting exact-file authorization. Do not interpret these implementation checks as a positive or negative result about TPSM importance.

The user authorized the proposed finite CTU perturbation experiment. Implemented default-off VTMDecisionRecord/Replay and single P-CTU +/-1 probe with corresponding lambda multiplier. Both picture initialization and final requested CTU decisions are replayed. Actual modes, motion choices, filtering and future bits remain endogenous coding outcomes.

## Verified gates

- Release Windows encoder build passed;5 standalone CTests and31 Python tests passed.
- Four synthetic probe smoke streams independently decoded; record and zero-replay match original repaired SIBRC bitstream. Full picture-initialization schedules match. Only target CTU changes requested QP/lambda by the exact specified amount; all prior frames are byte-identical.
- Real AerialCity4K LDP GOP16 65-frame R2 target818855bps baseline bitstream matches the preceding remote experiment exactly: adf87f21575af859165eedc3a9e45447842372508fcafda7a8522775b2b8dccb.
- Real65-frame zero replay also matches that bitstream and every reconstructed frame hash and spherical SSE value. Both independently decoded.
- Original authorized9-source/test payload uploaded to remote isolated directory /root/spherical_sibrc_20261016_marginal. Separate Linux build and2 replay/TPSM CTests passed; existing source/experiments were preserved.
- Code review findings addressed: exact row/key/offset/lambda/picture checks, P-only target, complete preceding beta chain eligibility, completed checkpoint published after trace archival and own reconstruction cleanup. Final review found no further actionable issues.

## Pre-outcome sample feasibility

Original POC16 had only1 eligible high-weight CTU, so the baseline-only run stopped after passing identity gates. No perturbation response had been observed. An explicit baseline-only diversity audit of POCs8/16/24/32/40/48 found POC8 has26 low/43 neutral/4 high eligible CTUs. Use POC8 and its56 strictly future frames. Twelve CTUs were frozen using seed20261016 and current full-inter eligibility, complete configured preceding beta chain, no intervening reset and at least32 baseline bits. See reviewed-selection-poc8.json. This is a documented feasibility amendment, not selection by measured perturbation gain.

## Planned measurement

For each frozen CTU run -1 and+1 QP, with every other requested picture/CTU QP/lambda unchanged. Primary descriptive response is future frame-global spherical luma SSE reduction divided by current-frame SSE reduction, when positive. Record current/future/total bit changes, per-frame WS-PSNR, raw future benefit, negative/zero responses and invalid denominators. Compare rankings with TPSM weight using Spearman and a permutation null. This one-frame stratified finite-contrast sample cannot establish population significance, pure motion-following propagation, or general coding gains.

## Authorization state

User approved transfer of9 source/test files. Automatic review then rejected the expanded12-file payload because marginal.py, marginal_run.py and test_marginal.py were not explicitly included in that authorization. Original9-file transfer/build proceeded; the expanded payload has NOT been uploaded. An explicit12-file authorization question is pending. No workaround or indirect upload was performed.

Archive files preserve original bytes via .gitattributes. state.json records exactly which work is complete. Source and runner are in the same isolated branch; no algorithm defaults were changed.
