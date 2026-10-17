# Skip21 Stage-1 Validation Design

## Goal

Validate the Skip21 Stage-1 projection-support early gate before adding Stage 2 or Stage 3. The immediate output is a stronger E5/E10 timing and RD result plus explanatory pruning distributions showing why the observed BDBR loss stays small.

## Scope

In scope:

- Keep online decision behavior limited to `LardLfnstSkip=21 LardLfnst21Stages=1`.
- Re-test E5 and E10 with paired repeats under the existing AerialCity, QP 22/27/32/37, medium preset, 20-thread methodology.
- Add lightweight Skip21 Stage-1 diagnostic counters in separate diagnostic runs and aggregate them into a diagnostic summary.
- Preserve the existing rec-YUV cleanup and hash-stability checks.

Out of scope:

- Do not enable Stage 2 or Stage 3.
- Do not train or fit a mask table.
- Do not change the Skip21 Stage-1 gate thresholds except by selecting existing E5/E10 profiles.
- Do not use `LardLfnstTheoryTable.inc` for online decisions in this phase.

## Experiment Matrix

Main profile:

- `Skip21-S1-E5`: `LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile=0`
- Run as 5 paired repeats with 8 frames first. It is stable if median TS > 5%, mean TS > 3%, positive repeats >= 4/5, max-Y BDBR < 0.3%, and TS/max-Y BDBR > 10. Move to 16 frames only if 8-frame timing still looks noisy.

Aggressive profile:

- `Skip21-S1-E10`: `LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile=2`
- Run as 10 paired repeats with 4 frames first. If `abs(mean TS - median TS) > 3` percentage points or positive repeats < 7/10, run an additional 8-frame, 5-paired-repeat validation.

Discarded profile:

- `Skip21-S1-E7` is not re-tested unless a later code change makes it generate different bitstreams from E5.

## Diagnostic Data

Timing and diagnostics are separate run classes:

- Formal timing runs are used for final TS/BDBR. They do not write per-decision CSV, per-block trace, or per-decision trace. They output timing, BD-rate, byte delta, hash stability, and rec-YUV cleanup status.
- Diagnostic runs explain the pruning distribution. They may write Stage-1 stat CSV and aggregate by QP, size, latitude bin, and support-ratio bin. They are not used for final TS decisions.

The top-level report may contain both `timing_result` and `diagnostic_stats`, but `timing_result` must come from formal no-CSV timing runs.

Add a Skip21 Stage-1 stat CSV that is active only during diagnostic runs. Each row represents one LFNST-eligible caller-side decision opportunity, not every transform candidate.

Required row fields:

- `QP`, `x`, `y`, `w`, `h`
- `latBin`
- `sizeId`
- `modeGroup`
- `setIdx`
- `transpose`
- `supportRatioQ`
- `earlyZero`: whether Stage 1 pruned all nonzero LFNST candidates and forced `{0}`
- `stage1Decision`: `0 = full`, `1 = early_zero`
- `candidateBefore`
- `candidateAfter`

`candidateBefore` is the number of nonzero LFNST candidates that would be tested before Stage-1 pruning. `candidateAfter` is the number of nonzero LFNST candidates that remain after Stage-1 pruning. A full nonzero search records `candidateBefore=2, candidateAfter=2`; Stage-1 early `{0}` records `candidateBefore=2, candidateAfter=0`. Non-LFNST-eligible opportunities are not logged.

Do not require a row-by-row join between early decisions and final CU/TU results. `final_lfnst_idx_distribution` is collected from final-stat aggregation separately. If a later implementation needs joins, it must add a stable unique key including POC, CTU identity, CU/TU geometry, intra mode, LFNST set index, and a decision serial.

## Summary Additions

The validation report should expose formal timing separately from diagnostics:

```json
{
  "timing_result": {},
  "diagnostic_stats": {}
}
```

`timing_result` is produced by formal paired-repeat runs without diagnostic CSV. `diagnostic_stats` is produced by separate diagnostic runs and may write CSV sidecars for inspection.

Required aggregate fields:

- `early_zero_count`
- `early_zero_ratio`
- `candidate_before_total`
- `candidate_after_total`
- `nonzero_candidate_reduction`
- `by_qp`
- `by_size`
- `by_lat_bin`
- `early_zero_by_support_ratio_bin`
- `final_lfnst_idx_distribution`

The candidate reduction is computed as:

```text
(candidate_before_total - candidate_after_total) / candidate_before_total
```

Rows with `candidate_before_total == 0` are excluded from the ratio denominator.

Each grouped diagnostic section must include:

- `eligible_count`
- `early_zero_count`
- `early_zero_ratio`
- `candidate_before`
- `candidate_after`
- `candidate_reduction`

`early_zero_by_support_ratio_bin` uses support-ratio ranges `[0,0.25)`, `[0.25,0.5)`, `[0.5,0.75)`, and `[0.75,1.0]`. The expected theory-consistent pattern is higher early-zero ratio in low support-ratio bins and high-latitude bins.

## Acceptance Criteria

E5 is considered stable enough for the main Pareto profile if:

- Median TS > 5%.
- Mean TS > 3%.
- Positive repeats >= 4/5.
- Maximum Y-BDBR < 0.3%.
- TS/max-Y-BDBR > 10.

E10 remains an aggressive Pareto profile if:

- Median TS > 8%.
- Maximum Y-BDBR < 0.3%.
- TS/max-Y-BDBR > 10.
- Positive repeats >= 6/10 in the 4-frame, 10-repeat run, or >= 4/5 in the 8-frame fallback run.
- The diagnostic distributions show the extra pruning is concentrated in theoretically expected support-shrunk bins rather than broad unrelated bins.

If E10 misses the positive-repeat requirement, report it as a high-speed exploratory point rather than a stable Pareto result.

Stage 2 is considered only after this validation, and only if E10 timing stability is weak or later multi-sequence testing shows sequence-local BDBR spikes.

## Stage-2 Note

The eventual Stage-2 direction is a theoretical table lookup, not a trained mask route. The offline table shape remains:

```cpp
struct LardLfnstTheoryEntry
{
  uint8_t latBin;
  uint8_t sizeId;
  uint8_t modeGroup;
  uint8_t setIdx;
  uint8_t transpose;
  int16_t supportRatioQ;
  int16_t g1CovQ;
  int16_t g2CovQ;
  int16_t gmaxCovQ;
  int16_t diffCovQ;
};
```

Online Stage 2 should only look up this table. It should not compute covariance matrices online.

## Reporting Text

The current phase conclusion should be reported as preliminary until the E5/E10 validation reruns complete:

Preliminary 4-frame paired results show that the Stage-1 projection-support early gate can convert ERP-induced support shrinkage into actual wall-clock saving. The low-risk E5 profile reached 6.12% median TS with +0.204% maximum Y-BDBR, while the aggressive E10 profile reached 10.94% median TS with +0.259% maximum Y-BDBR. The current validation phase re-tests E5 and E10 with longer or repeated paired runs and adds pruning-distribution diagnostics to verify that the speedup originates from theoretically expected support-shrunk bins. Since E5 and E7 generate identical bitstreams, E7 is treated as a redundant timing-noise point and is removed from the Pareto set.
