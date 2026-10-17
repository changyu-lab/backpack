# RC360 Uprop Full Lookahead Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide complete, cached GOP-level original-frame lookahead and legal-reference-only Uprop analysis without changing coding order.

**Architecture:** `EncApp` buffers encoded-domain originals and publishes a lookahead window before each frame is submitted. `Rc360Uprop` analyzes immutable frame views once per window using legal reference POC lists derived from `GOPEntry`, then `EncGOP` and `EncSlice` consume cached results.

**Tech Stack:** C++17, VTM EncoderApp/EncoderLib, CMake RC360 development tests.

---

### Task 1: Core Analysis Contract

**Files:**
- Modify: `source/Lib/EncoderLib/Rc360Uprop.h`
- Modify: `source/Lib/EncoderLib/Rc360Uprop.cpp`
- Modify: `tests/rc360_uprop_core_test.cpp`

- [x] Add failing tests for legal-reference filtering, window cache identity, and propagation into an anchor frame.
- [x] Run the RC360 core test and verify the new assertions fail.
- [x] Add immutable analysis frame/reference descriptors and cache-key state.
- [x] Rename `satdDiff` to `sadDiff`.
- [x] Run the core test and verify it passes.

### Task 2: Application Lookahead Queue

**Files:**
- Modify: `source/App/EncoderApp/EncApp.h`
- Modify: `source/App/EncoderApp/EncApp.cpp`
- Modify: `source/Lib/EncoderLib/EncLib.h`
- Modify: `source/Lib/EncoderLib/EncLib.cpp`

- [x] Extract encoded-domain input reading into a helper usable for queued buffers.
- [x] Add queue allocation, fill, front submission, and destruction.
- [x] Publish one complete GOP-sized read-only window to `EncLib`.
- [x] Preserve the existing frame count, EOS, flush, and coding order.

### Task 3: GOP Window and Legal References

**Files:**
- Modify: `source/Lib/EncoderLib/EncGOP.cpp`
- Modify: `source/Lib/EncoderLib/EncLib.cpp`

- [x] Remove the per-picture POC-modulo picture collection.
- [x] Derive legal reference POCs from configured RPL entries.
- [x] Trigger one cached analysis before submitting each GOP-boundary picture.
- [x] Add window and per-picture edge diagnostics.

### Task 4: Build and Behavioral Verification

**Files:**
- Modify only if required by build integration: `tests/CMakeLists.txt`

- [x] Configure and build `rc360_uprop_core_test`.
- [x] Run the core test.
- [x] Build `EncoderApp` with frozen 6A compile flags.
- [x] Run a short lookahead smoke that crosses POC 8.
- [x] Verify non-overlapping windows are analyzed once.
- [ ] Run B0 full-resolution parity.
- [ ] Run B1/B2/B3 full-resolution ablation only after B0 passes.
