# RC360 Uprop Full Lookahead Design

## Goal

Replace the current partial, per-picture Uprop analysis with a stable application-level
lookahead that gives every inter picture, including POC 8, access to its complete future
propagation window before encoding.

## Input Queue

`EncApp` owns a queue of encoded-domain original pictures. Input conversion, 360
processing, padding, and optional source scaling happen before a picture enters this
queue. The queue is filled far enough ahead to cover one complete GOP-sized window.
The front picture is passed to `EncLib` in the original coding order, so rate control,
DPB behavior, and bitstream ordering remain unchanged.

Before passing the current picture to `EncLib`, `EncApp` publishes read-only analysis
views for the current propagation window. The view contains POC, luma dimensions,
stride, and luma samples. `Rc360Uprop` copies no reconstruction state and never reads
the input file directly.

## Analysis Windows

Propagation windows are non-overlapping and anchored at GOP boundaries:

- POC 0 through 7 for the first window.
- POC 8 through 15 for the second window, allowing POC 8 to receive future propagation.

Each window has a stable key and is analyzed at most once. Results remain cached until
all pictures that query the window have been encoded.

## Legal References

For every future POC, the configured `RPLEntry` supplies `m_deltaRefPics`. The analysis
builds an explicit list of legal reference POCs and searches only references present in
that list and in the analysis window. No edge may be created from an arbitrary earlier
picture.

If a legal reference lies before the cached window, it is omitted because no current
window CTU can receive an edge for it. The search keeps the best legal reference region.

## Propagation

The existing dependency formula, overlap weighting, reverse recursion, per-frame median
normalization, clipping, and CTU beta exponent remain unchanged. `satdDiff()` is renamed
to `sadDiff()` because the implementation computes sampled SAD.

## Verification

Unit tests cover:

- Legal-reference filtering rejects a lower-cost illegal reference.
- A cached window is analyzed once when queried repeatedly.
- A window containing POC 8 through 15 can propagate edges into POC 8.
- Existing reverse recursion and normalization remain correct.

Runtime smoke checks require one Stats line per analyzed picture per window, a cache-hit
diagnostic instead of repeated Stats blocks, and nonzero POC 8 edge count.

B0 must reproduce the frozen 6A result before B1/B2/B3 are rerun.
