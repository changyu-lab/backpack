# Visual gaze RC implementation plan

**Goal:** Implement the approved complete modular VTMRC@VVenC port, with explicit provenance for incompletely specified paper parameters.

**Architecture:** Keep the mechanically extracted VTM RC kernel unchanged. Add a separate budget/parameter controller at the adapter boundary and offline, POC-indexed feature/ScanDMM inputs. Use actual reconstructed CTU feedback for dependency, not future distortion.

**Tech stack:** C++14, MSVC2019/CMake/CTest, Python/numpy/OpenCV, official ScanDMM/PyTorch in its own environment.

## Execution record (2026-10-12)

Tasks 1–5 completed for the platform port; verification and real-input evidence are in
`docs/visual-gaze-rc/README.md`, `provenance.json`, and `aerialcity-smoke-report.json`.
40 CTests and 9 Python tests pass; original RC extraction/replay are unchanged.
Review found and fixed LMCS-domain feedback and 360Lib spherical-metric conventions.
The actual integration checks were added alongside integration rather than all being written beforehand;
CLI rejection relies on configuration validation and strict parser unit coverage, without a separate negative CLI test suite.
The full paper dataset/protocol and original ACO/undisclosed coefficient recovery remain outstanding;
the completed smoke experiment does not establish the published RD gains.

## Frozen implementation conventions

- LIavg is the arithmetic mean of strip latitude sums over the whole frame; CTU latitude is the mean over actual source pixels. Eq.(10) is applied literally, without product renormalization.
- wf is the nonnegative CTU feature; zero feature totals use pixel-count proportions and are explicitly traced. Nonpositive budgets yield the existing RC minimum of one bit per CTU, with raw strip budget retained.
- MSE normalized by `(2^bitdepth-1)^2`; squared Pearson correlation on original collocated blocks, zero for zero-variance or absent neighbors. Distortion is measured from original versus reconstructed luma, including references after their reconstruction filters.
- Offline current/reference original-frame features avoid cyclic dependence on final encoding MV. Deterministic block motion preanalysis and adaptive Canny are explicit port conventions until original HPRC code is available. f, muM, muS must be provided, not attributed to the paper.
- Mode 0 off, 1 strips, 2 strips+dependency with no key CTUs, 3 complete (requires exactly 49 gaze points per POC). POC mappings are explicit. QP clipping uses original VTM lambda mapping and +/-2 bound; lambda clipped to the corresponding mapping interval.
- Offline inputs carry dimensions, CTU size, frame count and bit depth in headers. Malformed, duplicate, incomplete or out-of-range inputs fail. Synthetic data is limited to verification.

## Task 1: baseline
- [x] Configure `cmake -S . -B build-gaze -G "Visual Studio 16 2019" -A x64 -DVVENC_ENABLE_LINK_TIME_OPT=OFF`.
- [x] Build Release and run `ctest --test-dir build-gaze -C Release --output-on-failure`; preserve baseline executable before edits.
- [x] Check original kernel extraction with `python test/vtmrc/check_extraction.py`.

## Task 2: numerical controller
Files: `source/Lib/EncoderLib/VtmRcCompat/VisualGaze.{h,cpp}`, `test/visualgaze/controller_test.cpp`, root `CMakeLists.txt`.
- [x] Write tests for latitude symmetry/partial CTUs, literal strip allocations, debits, three Eq.(16) cases, missing rows and strict trajectory validation. Run them and observe the missing controller failure.
- [x] Implement `StripBudget::target(ctu,frameLeft)` and `feedback(bits)` with ordered guards; implement `optimize(lambda,qp,phi,key,complex,bitdepth)` and strict feature/gaze readers.
- [x] Register CTest executable, run it and verify manually calculated fixtures (uniform features: central strip receives more bits; phi=.5 scales key lambda .5 and low-complexity lambda 2).

## Task 3: adapter integration and configuration
Files: adapter header/source, public configuration header/default/check/string functions, application CLI.
- [x] Add strict input-parser/configuration validation and real closed-loop integration tests (see execution-order deviation above).
- [x] Add mode, input, trace and dependency-strength options, disabled by default. Reject native RC, parallel and crop/padding ambiguity through existing VTMRC checks plus explicit geometry checks.
- [x] At beginPicture select feature rows and reference originals by actual Slice POCs. At decideCtu replace CTU target bpp without modifying the RC kernel, apply dependency/key optimization, record applied decision. At feedback compute luma MSE and debit strip; at finishPicture flush diagnostics.
- [x] Verify disabled bitstream identity with preserved baseline; verify all enabled decisions, QP bounds, finite lambda, budgets and RA POC order.

## Task 4: offline inputs and reproducibility
Files: `tools/visual_gaze/prepare.py`, `tools/visual_gaze/test_prepare.py`, `tools/visual_gaze/evaluate.py`, documentation.
- [x] Test coordinate conversion, exactly49 observers, POC sorting, tail lengths, finite coordinates, temporal features and repeatability before implementation.
- [x] Implement raw YUV preprocessing and `(49,N,2)` ScanDMM conversion with model/source/array hashes and explicit source-to-target POC manifest. Generate official inference commands per display GOP; never substitute random trajectories for evaluation.
- [x] Provide four-QP target provenance, RC error and WS-PSNR/S-PSNR evaluation using existing repository metrics tooling where applicable, buffer Eq.(32), BD-rate and full ablations. Refuse unsupported sphere sampling conventions rather than invent S-PSNR results.

## Task 5: evidence and review
- [x] Rebuild; run CTest, original RC extraction/replay, Python input tests, enabled serial/RA encoding and decoder checks, repeat hashes.
- [x] Self-review reference lifetime, error paths, budget ordering, POC alignment and CLI defaults; fix findings and rerun affected tests.
- [x] Save exact commands/results/limitations in `docs/visual-gaze-rc/README.md`. Commit only task files on `codex/visual-gaze-rc` after verification.

Execution is inline in the already authorized independent branch. Missing original parameter values/weights do not justify claims of reproducing published RD gains; keep empirical acceptance separate from software validation.
