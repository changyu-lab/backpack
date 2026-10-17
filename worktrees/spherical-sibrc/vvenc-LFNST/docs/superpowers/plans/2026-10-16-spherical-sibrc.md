# Spherical TPSM + SIBRC Implementation Plan

> **For agentic workers:** Use executing-plans inline, task by task. The approved design is docs/superpowers/specs/2026-10-16-spherical-sibrc-design.md.

**Goal:** Implement isolated TPSM-1/4/AD and a temporal-weighted SIBRC controller, with honest reproduction boundaries and paired validation.
**Architecture:** A standalone Tpsm history/arithmetic library supplies immutable next-picture weights. Encoder integration captures final selected inter predictor errors on CodingUnit objects, preserving the measurements with selected CU copies. A separate picture driver supports both fixed-QP and VTM-RC; combined mode changes only SIBRC action scores, never its raw distortion feedback.
**Tech Stack:** C++11, VVenC1.12, MSVC2019, CMake, Python unittest, original360Lib evaluation.

### Task1: Arithmetic/history reference
- [x] Create test/tpsm/tpsm_test.cpp and CMakeLists.txt. Assert four beta=.5 frames give wt=.9375; M1=.5, zero MCP breaks history, scene thresholds use AND, partial histories and normalized area mean are exact.
- [x] Configure/build with cmake -S test/tpsm -B I:/vvenc-LFNST/.tmp/tpsm-test -G "Visual Studio 16 2019" -A x64. Verify missing implementation fails, then add source/Lib/EncoderLib/Tpsm/Model.h/.cpp.
- [x] Include explicit API Moments, Observation, Weights, History::begin/finish, spatialWeight, paperDecision, normalizeImportance. Verify finite ratio guards, literal frame offset, threshold boundaries and lifecycle errors using executable checks active in Release.

### Task2: Joint optimizer
- [x] Add test/sibrc/temporal_test.cpp covering neutral identity, changed allocation under a fixed budget, unchanged raw predictions and equal raw bias updates.
- [x] Add optional temporal weights to Controller::begin; store separately from spherical area. Score each action as temporal[i]*prediction.distortion + price*prediction.rate. Feedback continues to use raw prediction.distortion.
- [x] Run all standalone C++ tests and Python regression tests.

### Task3: Final predictor capture
- [x] Add finite luma MCP/reconstruction SSE and eligible pixels to CodingUnit; reset in initialization and copy in operator=.
- [x] Capture when a single-CU candidate is accepted in EncCu::xCheckBestMode, using original, prediction and reconstructed buffers before reuse; sum only final CUs at CTU completion.
- [x] Reject LMCS/MCTF/QPA initially so all three samples use one domain. Add optional binary pixel triples for a tiny-fixture independent SSE audit.

### Task4: Encoder driver and options
- [x] Add Tpsm/Encoder.h/.cpp, attach nonowning driver to Picture and owned driver to EncGOP. begin-picture computes original moments and immutable weights; end-picture commits completed CTU observations.
- [x] Add TPSMMode0/1/2, TPSMChain1/4/0(adaptive), TPSMNormalize8Bit, TPSMTrace and TPSMAudit paths; defaults off. Reject RA, B combined models, parallel feedback, native RC, LMCS and other adaptive QP features.
- [x] Integrate paper CQP decisions in EncSlice and paper RC decisions in VtmRcCompat adapter. Enable DQP for standalone TPSM. Apply literal frame offset before slice initialization. Combined mode passes normalized temporal weights to SIBRC only.
- [x] Compile full encoder. Test option rejection, all-off identity, deterministic repeats and predictor audit.

### Task5: Paired experiment tooling
- [x] Add tools/tpsm smoke/audit and paired runner with explicit commands, hashes, actual rates and no overwrite. Reuse existing independent SIBRC statistics/models only when their hashes and feature definitions match committed code.
- [x] Use fixed-QP22/27/32/37 for paper modes, then matched-target RC for anchor/SIBRC/paper/combined. Save short results before deciding on300-frame evaluations.
- [x] Resolve original360Lib metric executable/sample assets; record WS/S-NN/CPP separately. If unavailable, report missing artifacts instead of substituting ordinary PSNR.

### Task6: Review and evidence
- [x] Review geometry counted once, feedback once, no future frames, frame-QP consistency, source scaling, trial-CU isolation and fixed-QP/RC labeling.
- [x] Run CTest, Python suites, full build, smoke/audit, decode comparison where decoder available and git diff --check.
- [x] Save exact completed checks and measured limitations in tools/tpsm/README.md and docs/tpsm. Commit implementation on codex/spherical-sibrc; keep other worktrees untouched.

Research outcome: implementation and planned screening completed; joint performance gate failed. No formal300frame promotion; see docs/tpsm/2026-10-16-results.md.
