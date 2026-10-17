# Uprop CTU Signal Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime-selectable current, spherical-base-only, and propagation-excess-only CTU Uprop signals for the A3 ablation.

**Architecture:** Keep graph construction and backward recursion unchanged. After total raw propagation is solved, select the CTU signal before frame-median normalization: mode 0 uses `Uraw`, mode 1 uses `u0`, and mode 2 uses `max(Uraw-u0, 1e-9)`. Frame Uprop remains disabled in every A3 experiment.

**Tech Stack:** C++17, VTM EncoderLib, program-options configuration, CMake/CTest.

---

### Task 1: Core signal selection

**Files:**
- Modify: `tests/rc360_uprop_core_test.cpp`
- Modify: `source/Lib/EncoderLib/Rc360Uprop.h`
- Modify: `source/Lib/EncoderLib/Rc360Uprop.cpp`

- [ ] Add failing core tests proving mode 1 ignores edges and mode 2 removes direct `u0`.
- [ ] Run `rc360_uprop_core_test` and verify the new assertions fail.
- [ ] Add `ctuSignalMode` to `Rc360Uprop::Config` and select the raw signal before normalization.
- [ ] Rebuild and verify the core test passes.

### Task 2: Runtime configuration

**Files:**
- Modify: `source/App/EncoderApp/EncAppCfg.h`
- Modify: `source/App/EncoderApp/EncAppCfg.cpp`
- Modify: `source/App/EncoderApp/EncApp.cpp`
- Modify: `source/Lib/EncoderLib/EncCfg.h`
- Modify: `source/Lib/EncoderLib/EncLib.cpp`

- [ ] Add `RC360UpropCtuSignalMode` with default 0 and validation range 0..2.
- [ ] Forward the option from EncoderApp to EncLib and into `Rc360Uprop::Config`.
- [ ] Print the selected mode in Uprop statistics.
- [ ] Build EncoderApp and verify invalid mode 3 is rejected.

### Task 3: A0/A1/A3 experiment execution

**Files:**
- Create: `rc360_verify/route_b_uprop_20260615/run_server_a1_a3.sh`

- [ ] Complete and parse Linux same-binary A0.
- [ ] Gate on A0 parity before launching later cases.
- [ ] Run A1 with analysis enabled and both application switches disabled.
- [ ] Run A3-1 mode 1, A3-2 mode 2, and A3-3 mode 0, always with frame Uprop disabled.
- [ ] Compute all BD-rates relative to Linux A0 and report Y-WS, Y-S, Y-CPP, ordinary Y, target error, and diagnostic distributions.
