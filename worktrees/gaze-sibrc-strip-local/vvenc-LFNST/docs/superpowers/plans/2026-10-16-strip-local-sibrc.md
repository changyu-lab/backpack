# Strip-local SIBRC implementation plan

Approved by user 2026-10-16; run AerialCity first, four frozen RA32 targets, actual32frames/refs1. Use isolated codex/gaze-sibrc-strip-local. Execute continuously with test-first steps and independent review.

Goal: attachment strip budgets constrain SIBRC search within current CTU row; no alpha blend, frozen C4 models/stats/offsets.
Architecture: Runtime exposes strip ledger; Controller accepts end index with default frame-end; adapter passes strip_left/end, consumes real feedback once, diagnostic trace provides reachability and failure reason. Legacy paths remain byte compatible.
Stack: C++14/CMake, Python/numpy metrics, remote GCC11.

- [x] Create attached worktree from 3c43e4d and named branch, preserving old worktrees.
- [x] Baseline: run existing formula/controller tests. Add failing tests for Controller bounded end, future-strip independence, negative/too-low budget reason and min/max predictions. Implement optional end index and diagnostics without changing legacy numeric selection. Preserve update residual across rows.
- [x] Add strip ledger observability (target/start/end/remaining); first failing tests prove target initialization at row start, real debit once and next row uses frame remainder. Runtime exposes immutable ledger access after target().
- [x] Add GazeSibrcStripLocal bool defaultfalse; require mode1/SIBRC3/alpha1. Adapter mode branches target=strip target; calls Controller decide with strip end and real strip_left; logs row ledger before/after, model bounds, reason, decisions, actual bits and frame budgets.
- [x] Build and run full CTest, Python and real CLI validation. Review specification and core control flow. Legacy A/G/S/alpha0 and old mixture representative SHA gates must match.
- [x] Runner: four AerialCity frozen matched32 targets, original full C4 args, independent folder/encoder/traces, hashes, independent decode, Python and native sphere metrics; validate complete row boundaries, strip debits/continuity, frame debits, range, correction persistence and both mechanisms activity. Retain all infeasible/negative cases and metrics, no exclusions.
- [x] Freeze source commit; create own remote source/build/results directory using available disk/RAM; don't delete other jobs or old outputs. Maximize concurrency subject to actual RAM and scratch space.
- [x] Summarize 4/4 outcomes: all metrics BD vs same Anchor and SIBRC; fourpoint bitrate/quality, totalencodingtime/DeltaT, row budgets/fallback reasons and activity; keep negative result if any. Preserve branch, no merge/push. User requested AerialCity first: do not silently substitute development City/Country or claim full8/14 results.

Completed 2026-10-16: AerialCity4/4; all41CTest+41Python; 5legacygates; 57600CTU/1920strip verified. S-NN BD versus SIBRC +4.819737%, versus purestrip -7.503833%. Originalfilesunchanged, rawfallbackallretained. City/Country8point and14sequence validation NOT executed.
