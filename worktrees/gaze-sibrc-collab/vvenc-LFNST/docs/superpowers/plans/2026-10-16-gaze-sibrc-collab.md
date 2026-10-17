# Gaze–SIBRC collaboration implementation plan

Approved 2026-10-16. Implement inline in independent branch codex/gaze-sibrc-collab.

**Goal:** Preserve each frozen method and run sixteen controlled hybrid RA32/32-frame points.
**Architecture:** Original VTM CTU target and strip target are blended before the VTM QP/lambda estimate; unchanged SIBRC C4 then selects the final offset. Single real feedback per controller. No dependency/gaze-lambda additions.
**Stack:** C++14, CMake/MSVC/GCC, Python/numpy; frozen remote model/stats and old RA commands.

- [x] Isolation: managed worktree from ea58bb96, named branch, copy approved design, preserve original worktrees and data.
- [x] Frozen baseline: old C++ controller extraction unchanged; run existing numerical/formula tests on Linux before integration comparison gates.
- [x] Import SIBRC Controller/Preanalysis/Statistics byte-for-byte from frozen source; copy only new working tree files. Import public/CLI fields/default/checks and register source glob. Add GazeSibrcAlpha (default1, [0,1]) and GazeSibrcTrace. Both methods enabled only for VisualGazeMode1 plus SIBRCMode3.
- [x] TDD: independent blend tests for alpha0 identity, alpha1 identity, finite/range checks, positive mixed targets and exact rounding. Controller helper added only after missing implementation failure.
- [x] Adapter: preserve original path when SIBRC off, bypass gaze Runtime entirely at combined alpha0, calculate one baseline target, mix once, estimate VTM parameters once, SIBRC final decision. Freeze SIBRC base/feedback behavior. Trace original/strip/mixed target, SIBRC base/applied QP/lambda, actual bits and budgets.
- [x] Build, run complete CTest (40/40) and Python checks (28/28 final). Review core integration and reference/feedback contracts separately from runner review.
- [x] Remote isolated folder with independent build and frozen source hashes; no changes to existing source/exe/models/results; four R1 gates passed, before/after SHA audit passed. Gates: A modeoff matches old Anchor; G alone matches old strip; S alone and combined-alpha0 match old C4. Complete dev/source/metric identity checks before reusing old comparisons.
- [x] Trial: DrivingInCity and DrivingInCountry, two alphas .10/.25 x four frozen targets =16 hybrid points. Use same 32 frames, refs1, C4 stats/models/beta, 8/10-bit path, all spherical metrics and independent decoding. Per-CTU activity evidence must show both real mixed-target changes and SIBRC nonzero decisions.
- [x] Report all candidates and losses, compare against frozen SIBRC (not merely Anchor), retain hashes and metadata. Do not claim guaranteed gains. Select one alpha only if dev criteria pass; fourteen-sequence validation is a subsequent stage, not automatic test-set tuning.

Original methods and models stay frozen. Known LMCS feedback conventions in frozen SIBRC are preserved for identity; do not silently fix or recalibrate them in this experiment.

Completed: 16/16 points, all decoded and four-trace verified; alpha .10 and .25 fail to improve any average metric against SIBRC. No candidate promoted to fourteen-sequence validation. See docs/visual-gaze-rc/collab-ra32-dev-20261016/report.md.
