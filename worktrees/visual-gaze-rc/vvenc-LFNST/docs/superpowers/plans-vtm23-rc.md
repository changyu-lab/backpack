# VTM23 RC Compatibility Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the extracted kernel and independent reviews; execute integration in this isolated session. Track each task below.

**Goal:** Reproduce the local original VTM-23.0 RC kernel in VVenC and integrate deterministic CTU feedback, with independent replay and real coding evidence.

**Architecture:** Mechanically extract RateCtrl into a separate namespace, preserving arithmetic and licensing. A thin stateful adapter drives serial VVenC CTU coding and closes picture accounting without changing native RC.

**Tech Stack:** C++11, CMake, MSVC 19.29, Python unittest/replay tooling.

## Task 1: Baseline and provenance
- [x] Configure official VVenC with `cmake -S . -B build-anchor-vs2019 -G "Visual Studio 16 2019" -A x64 -DVVENC_ENABLE_LINK_TIME_OPT=OFF`.
- [x] Build with `cmake --build build-anchor-vs2019 --config Release --parallel 4` and run CTest.
- [x] Record SHA-256 of original VTM RateCtrl.cpp/.h and EncSlice/EncGOP call sites, local commit, version macro, and official-source verification limitations in `docs/vtm23-rc/provenance.json`.

## Task 2: Kernel extraction and independent replay
Files: `source/Lib/EncoderLib/VtmRcCompat/RateCtrl.{h,cpp}`, `Dependencies.h`, `test/vtmrc/{CMakeLists.txt,replay.cpp,compare_replay.py}`.
- [x] Add a replay driver compiled directly against unchanged local VTM sources/headers, then compare against a missing compat target to establish the failing baseline.
- [x] Extract core with names EncRCSeq -> VtmRcSeq, EncRCGOP -> VtmRcGOP, EncRCPic -> VtmRcPic, TRCLCU -> VtmRcCtuState, RateCtrl -> VtmRateCtrl, wrapped in vvenc::vtmrc. Only replace dependency includes and qualify the namespace; keep numerical statements unchanged.
- [x] Build the compatibility driver and compare identical inputs for target bits, QP, lambda, alpha/beta, and sequence/GOP/picture remaining bits at every step. Include IRAP/inter, partial CTUs, low budgets, multiple GOP sizes, model updates and rational frame rates.
- [x] Use integer equality and abs 1e-12 / rel 1e-10 floating tolerance. Inject a divergence to prove the comparator fails.
- [x] Audit the mechanical diff and preserve upstream license.

## Task 3: Configuration contract
Files: `include/vvenc/vvencCfg.h`, `source/Lib/vvenc/vvencCfg.cpp`, `source/Lib/apputils/VVEncAppCfg.h`, `test/vtmrc/config_test.cpp`.
- [x] Test that the opt-in controller and bitrate are recognized, native RC/QPA/WPP/IFP/tiles/lookahead/competing adaptations are rejected, and default behavior remains native.
- [x] Add independent config fields and CLI options, initialize defaults, validate effective configuration after preset inference. Document strict serial settings.

## Task 4: Controller adapter and feedback integration
Files: `source/Lib/EncoderLib/VtmRcCompat/Adapter.{h,cpp}`, `EncGOP.{h,cpp}`, `EncSlice.{h,cpp}`, `EncCu.cpp`, `source/Lib/vvenc/CMakeLists.txt`.
- [x] Test decision-before-feedback and out-of-order feedback rejection with a small adapter harness.
- [x] Map actual GOP entries and IRAP flags; initialize VTM picture budgets/lambda/QP before slice setup.
- [x] Before each CTU coding decision apply controller QP and lambda to RDO, quantization and prediction. After coding, run a dedicated maintained-context CABAC estimator pass on its completed tree, then supply integerized bits, effective-pixel/skip/MSE feedback before next CTU.
- [x] Complete VTM picture/GOP/sequence update at actual picture output, with header and total bit accounting corresponding to VTM EncGOP. Add JSONL/CSV traces and explicit order assertions.

## Task 5: Closed-loop validation and reporting
Files: `tools/vtmrc/{smoke.py,README.md}`, `docs/vtm23-rc/validation.md`.
- [x] Generate or select a documented nontrivial test clip; encode four increasing rates for sufficient frames and record bitrate/QP/lambda/budget distributions, PSNR and timing.
- [x] Repeat encoding and compare trace/bitstream hashes; decode streams with a available VVC decoder and check picture count.
- [x] Test native-RC/default regressions and invalid configurations, run independent replay after final changes.
- [x] Review spec compliance first, then code quality. Fix reported defects and rerun affected checks.
- [x] Commit verified implementation. Clearly distinguish local-source equivalence, official provenance status, short smoke evidence and long-sequence convergence. Do not merge or publish automatically.

Execution notes: baseline built with default LTO; compatibility disables it. Existing maintained-context CTU CABAC pass supplies feedback. Official VTM tag authentication is pending; hashed local kernel equivalence passes. Tests: tools/vtmrc/test_closed_loop.py, test_cli.py, test/vtmadapter; replay runner: compare.py.
