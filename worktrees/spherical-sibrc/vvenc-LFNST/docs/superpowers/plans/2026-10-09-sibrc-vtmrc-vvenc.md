# SIBRC VTM-RC@VVenC implementation plan

Approved user design: docs/superpowers/specs/2026-10-09-sibrc-vtmrc-vvenc-design.md. Execute with subagent-driven-development and TDD. Existing isolated checkout is retained; feature branch codex/sibrc-vtmrc-vvenc starts from validated VTM compatibility work. No other research branch changes.

## Task1: Close statistics and calibration definitions
- [x] Read author chapter and related source assets; identify complete X/Y correlation and energy construction, or define and record independently calibrated controlled-stretch pairs.
- [x] Freeze block32, beta5, frequency multiplicity1, 8bit energy normalization, ERP latitude at sample/block centre. Any adaptation from manuscript is explicit.
- [x] Record model training/evaluation separation: development DrivingInCity and DrivingInCountry, evaluation AerialCity. Models are separate I/P or I disabled if no defensible intra model; do not silently assign inter model to intra.

## Task2: Pure controller and mathematical tests
Files: source/Lib/EncoderLib/Sibrc/Controller.h and .cpp; test/sibrc/CMakeLists.txt and controller_test.cpp.
- [x] Write and run tests first: IB activation rho2=0.1 beta5 =>0; rho2=.8 => 0.5*log2(4); polynomial feature order; candidate monotonic filter; infeasible budget =>zero offset; finite zero feature handling; lambda mapping offset3=>2x; feedback delta=.5 eta=.1 residual2 => .65.
- [x] Implement Model containing six rate and six distortion coefficients, metadata and strict file loading; x=(QP-4)*ln2/6, z=ln(max(I,1e-12)); rate is CTU bits, D is sphere-weighted MSE times CTU spherical area for additive optimization.
- [x] Implement current CTU baseline QP/future picture QP, offsets[-2,2], codec clamps, finite candidate checks, deterministic ties (prefer zero then lower abs offset then higher QP), nonnegative bit-price bracketing/bisection and feasible-side retention; infeasible fallback explicit.
- [x] Corrections deltaR/D per picture start0; actual residual against corrected prediction, bounded eta=.1 and delta[-ln4,ln4]; zero bit/distortion samples skip log update with diagnostic counter.
- [x] Unit build command: cmake -S test/sibrc -B test/sibrc/build -G "Visual Studio 16 2019" -A x64; cmake --build test/sibrc/build --config Release; test/sibrc/build/Release/sibrc_controller_test.exe.

## Task3: Feature preanalysis and feedback integration
Files: source/Lib/EncoderLib/Sibrc/Preanalysis.h/.cpp; VtmRcCompat/Adapter.h/.cpp; vvenc config and apputils option definitions; library CMake glob verified.
- [x] Deterministic32x32 residual preanalysis at picture begin with reconstructed nearest L0 reference and bounded integer search; explicitly documented intra fallback. Cache perCTU information and spherical area. Stats source resolved in Task1.
- [x] Add optional SIBRC config: enable, collect-only, model/stat asset path, trace path. Default off performs no added scans or mutations. Missing/malformed assets fail configuration rather than silently produce fake predictions.
- [x] Preserve original baseline decision trace; optional adjustment after VTM decide. Feedback VTM with applied lambda/actual QP, original distortion. Separately compute actual spherical distortion for SIBRC from current original/recon CTU; debit frame budget once using existing VTM remaining bits.
- [x] Collect-only logs I/QP/bits/weighted distortion with no coding changes, used for independent model training. Build encoder with existing build-vtmrc Release target.
- [x] Verify default-off bitstream and original CSV exact against preserved anchor; collect-only same bitstream; strict serial trace and decoder reconstruction; compare C++ information calculation with independent Python fixture.

## Task4: Offline model calibration and experiment tools
Files: tools/sibrc/calibrate.py, experiment.py, evaluate.py and tests.
- [x] Collect development samples at fixed CTU QP22/27/32/37 with compatible LDP tool config and a collection-only hook independent of native RC; at least multiple development pictures. Use whole development pictures for held-out fit diagnostics, not random CTU leakage.
- [x] Fit log-quadratic rate and distortion using stable scaled least squares/ridge, preserving coefficient transform back to physical x/z. Freeze model/domain/feature/provenance. Do not import AerialCity-specific old coefficients.
- [x] BDBR test anchor identical =>0; uniform 10% lower rate at same quality =>-10%; disjoint quality range fails; no extrapolation. Implement shape-preserving interpolation on quality/lograte common interval using scipy PCHIP. Use actual AnnexB rates, mean picture ERP WSPSNR; RC accounting separately.
- [x] Runner captures exact commands, hashes, return codes,16/128 unique POCs and configuration. Use raw reconstruction to stream quality evaluation. Decode all final evaluated streams and compare hashes.

## Task5: Screen and assess objective
- [x] Paired AerialCity ERP16 LDP same four existing targets (integration smoke). No unchanged-configuration requirement for historically run candidate unless binary/config fingerprints match; prefer fresh paired runs.
- [x] Main AerialCity128 LDP four same-platform CQP-derived target rates. Freeze grid and compare anchor/full. Fit and tuning remain development-only. Run ablations with frozen settings after full pipeline valid.
- [x] Report actual rates, WSPSNR/PSNR, BD-rate, errors, time and action/guard counts. Negative BDBR is a goal, never a fabricated acceptance claim. If no gain, diagnose trace/model/domain on development data, retest frozen evaluation honestly; no cherry-picked points.
- [x] Spec review then quality review, required checks, clean feature commit and final results report. Preserve both positive and negative runs and reconstruction provenance.

Outcome: implemented and tested; negative BD-rate objective NOT achieved. See docs/sibrc/results-20261010.md. Expanded-calibration128frame experiment was not run; do not imply otherwise.
