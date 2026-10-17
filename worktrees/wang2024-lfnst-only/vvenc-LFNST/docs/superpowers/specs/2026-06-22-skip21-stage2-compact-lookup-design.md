# Skip21 Stage-2 Compact Lookup Design

## Purpose

Replace the current per-decision linear scan of the 13,440-entry Skip21
theory table with a constant-time compact lookup. The change separates the
Stage-2 weak-coupling algorithm from its online deployment cost so that timing
results measure pruning value rather than table-search overhead.

This is a deployment optimization. It does not change the Stage-2 theoretical
gate or its D1/D2/D3 thresholds.

## Confirmed Root Cause

`xLardSkip21FindTheoryEntry()` currently scans every theory-table row until it
finds a six-field key match. The function runs for every eligible Skip21
decision. AerialCity diagnostics observed about 8.14 million eligible
decisions, so the linear lookup dominates the Stage-2-only timing result.

The current generated covariance metrics repeat across `modeGroup` and
`qpBucket`. Computing those dimensions and searching their duplicate rows adds
cost without adding discrimination.

## Compact Table

The first compact table uses this key:

```text
latBin, sizeId, setIdx, transpose
```

The packed index is:

```text
idx = (((latBin * NUM_SIZE + sizeId) * NUM_SET + setIdx) * 2 + transpose)
```

Online access is a single bounds-checked integer index into a static array:

```text
entry = g_lardLfnstSkip21TheoryCompactTable[idx]
```

The runtime path must not contain a linear scan, binary search, dynamic
fallback search, floating-point calculation, division, matrix operation, or
dynamic allocation.

The generator must verify that all source rows collapsed into one compact key
have identical Stage-2 metrics. A mismatch is a generation error rather than a
runtime fallback condition.

Every compact key has an array slot. Missing source combinations are filled
with an invalid full-RDO entry:

```text
valid = 0
oxQ = large
diagDominanceQ = small
gmaxCovQ = large
```

An invalid entry can never trigger early zero.

The compact entry retains the integer metrics needed by the current theory and
diagnostics:

```text
valid
supportRatioQ
oxQ
diagDominanceQ
g1CovQ
g2CovQ
gmaxCovQ
diffCovQ
```

`modeGroup` and `qpBucket` remain part of the offline source model and may be
restored as dense key dimensions when their covariance templates contain real
conditional differences. They are intentionally excluded from the first
compact deployment because the current templates do not model those effects.

## Stage-2 Debug Modes

Add the persistent encoder option:

```text
LardLfnst21Stage2Debug = 0, 1, or 2
```

The option is independent of `LardLfnst21Profile` and
`LardLfnst21Stage2Profile`. Algorithm profiles continue to represent threshold
choices only.

### Mode 0: Normal

The Stage-2 path computes the compact key, performs the O(1) lookup, compares
the integer `oxQ`, `diagDominanceQ`, and `gmaxCovQ` values with the selected
profile, and applies early zero when the gate passes.

### Mode 1: NoLookup

The Stage-2 entry point immediately returns full RDO. It does not compute the
compact key, read the table, compare thresholds, or modify the candidate loop.
This mode measures insertion-point and function-entry overhead. Its bitstream
must match the anchor exactly.

### Mode 2: NullLookup

The Stage-2 path computes the compact key, performs the real O(1) lookup, and
evaluates the selected threshold gate, but always returns full RDO. This mode
measures compact key, lookup, and comparison overhead. Its bitstream must match
the anchor exactly.

Stage1-only operation must not execute any Stage-2 key calculation or table
lookup.

## Runtime Data Flow

For an eligible Skip21 decision:

1. Evaluate Stage 1 only when Stage 1 is enabled.
2. Skip Stage 2 when it is disabled or Stage 1 already selected early zero.
3. In Stage-2 `NoLookup` mode, return full RDO immediately.
4. Otherwise compute `latBin`, `sizeId`, `setIdx`, and `transpose` once.
5. Access the compact table by packed index.
6. Treat an invalid entry as full RDO.
7. Evaluate the integer weak-coupling gate.
8. In `NullLookup` mode, discard the gate result and use full RDO.
9. In normal mode, apply the gate result to the candidate loop.

Diagnostic tracing may record the compact entry metrics, but disabled tracing
must not perform file or synchronization work.

## Verification

### Generator and Unit Tests

Tests must establish:

- duplicate `modeGroup` and `qpBucket` rows have identical compact metrics;
- every valid source row maps to the expected packed index;
- missing combinations generate invalid non-triggering entries;
- D1/D2/D3 decisions from the compact table match the existing table for all
  generated rows;
- generated C++ contains direct indexing and no lookup loop;
- debug values outside `0..2` are rejected;
- `NoLookup` bypasses key construction and `NullLookup` evaluates the gate but
  suppresses pruning.

The C++ encoder must build successfully after table replacement.

### Server Timing Validation

Use the clean-server AerialCity protocol already used for Stage-2 validation:

```text
QP 22/27/32/37
8 frames
5 paired repeats
medium preset
20 threads
```

Run in this order:

1. D3 with `Stage2Debug=1` (`NoLookup`)
2. D3 with `Stage2Debug=2` (`NullLookup`)
3. D3 with `Stage2Debug=0` (compact normal)

Acceptance expectations:

- NoLookup: exact anchor bitstream and median TS near zero;
- NullLookup: exact anchor bitstream and median TS near zero;
- D3 compact: early ratio near 8.45%, max Y-BDBR near the previous +0.083%,
  and median TS materially above the previous -4.671% result.

The preferred D3 result is non-negative median TS, with +1% or more as the
useful target. Stage1+Stage2 combined validation is deferred until compact D3
is near zero or positive. If NoLookup is negative, investigate the insertion
point. If NoLookup is near zero but NullLookup is negative, investigate key
calculation and lookup. If both are near zero but normal D3 remains negative,
the pruning coverage does not recover enough encoder time.

## Scope Boundaries

This work does not add D4/D5 thresholds, train an RD mask, modify the covariance
theory, add mode/QP-conditioned templates, or run Stage1+Stage2 combined
experiments. Those changes require evidence from the compact D3 validation.
