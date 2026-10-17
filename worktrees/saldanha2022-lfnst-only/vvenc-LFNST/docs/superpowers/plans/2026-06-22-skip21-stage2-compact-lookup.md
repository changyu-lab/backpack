# Skip21 Stage-2 Compact Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 13,440-row Stage-2 linear search with an O(1) compact theory table, add persistent NoLookup/NullLookup diagnostics, and validate their timing cost on the clean server.

**Architecture:** The offline generator collapses duplicate `modeGroup` and `qpBucket` rows into a dense `latBin x sizeId x setIdx x transpose` array and rejects inconsistent duplicates. `IntraSearch.cpp` indexes that array directly and branches early for the two debug modes; Stage1-only operation never enters the Stage-2 lookup path. The paired-repeat runner gains explicit D3 debug profiles so the same protocol measures entry overhead, lookup overhead, and real compact pruning separately.

**Tech Stack:** Python 3.8 `unittest`, NumPy table generation, C++17 VVenC encoder, CMake, Bash server orchestration.

---

## File Map

- Modify `tools/lard_lfnst/generate_skip21_theory_table.py`: collapse source entries, validate duplicate metrics, fill missing slots, and render the compact table.
- Modify `source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc`: regenerate the checked-in compact C++ table.
- Modify `tools/lard_lfnst/test_skip21_theory_table.py`: verify compact dimensions, duplicate consistency, invalid entries, packed indexing, and generated symbols.
- Modify `include/vvenc/vvencCfg.h`: expose the persistent Stage-2 debug integer.
- Modify `source/Lib/vvenc/vvencCfg.cpp`: initialize and validate the debug integer.
- Modify `source/Lib/apputils/VVEncAppCfg.h`: expose lowercase and canonical command-line options.
- Modify `tools/lard_lfnst/test_skip21_stage2_gate.py`: verify configuration and C++ debug semantics.
- Modify `source/Lib/EncoderLib/IntraSearch.cpp`: remove linear lookup, avoid unused key work, implement direct indexing, and enforce debug behavior.
- Modify `tools/lard_lfnst/run_skip21_stage2_validation.py`: add NoLookup, NullLookup, and compact D3 experiment profiles.
- Modify `tools/lard_lfnst/test_skip21_stage2_validation.py`: verify profile arguments and runner commands.
- Modify `tools/server_run_skip21_stage2_validation.sh`: default server validation to the three compact D3 profiles.

### Task 1: Generate the Compact Dense Table

**Files:**
- Modify: `tools/lard_lfnst/generate_skip21_theory_table.py`
- Modify: `tools/lard_lfnst/test_skip21_theory_table.py`
- Regenerate: `source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc`

- [ ] **Step 1: Write failing compact-table tests**

Add imports and tests that exercise the generator as Python data rather than only scanning text:

```python
from dataclasses import replace

from tools.lard_lfnst.generate_skip21_theory_table import (
    COMPACT_SET_COUNT,
    COMPACT_TRANSPOSE_COUNT,
    CompactTheoryEntry,
    TheoryEntry,
    compact_index,
    compact_entries,
    render,
)

def _entry(mode_group: int, qp_bucket: int) -> TheoryEntry:
    return TheoryEntry(
        lat_bin=1, size_id=2, mode_group=mode_group, set_idx=3,
        transpose=1, qp_bucket=qp_bucket, support_ratio_q=512,
        ox_q=10, diag_dominance_q=800, g1_cov_q=50,
        g2_cov_q=70, gmax_cov_q=70, diff_cov_q=20,
    )

def test_compact_entries_collapse_identical_mode_and_qp_rows(self) -> None:
    dense = compact_entries([_entry(0, 19), _entry(5, 34)], lat_count=2, size_count=3)
    idx = compact_index(1, 2, 3, 1, size_count=3)
    self.assertEqual(dense[idx], CompactTheoryEntry(1, 512, 10, 800, 50, 70, 70, 20))

def test_compact_entries_reject_inconsistent_duplicate_metrics(self) -> None:
    rows = [_entry(0, 19), replace(_entry(5, 34), ox_q=11)]
    with self.assertRaisesRegex(ValueError, "inconsistent compact theory metrics"):
        compact_entries(rows, lat_count=2, size_count=3)

def test_compact_entries_fill_missing_keys_with_invalid_rows(self) -> None:
    dense = compact_entries([_entry(0, 19)], lat_count=2, size_count=3)
    self.assertEqual(len(dense), 2 * 3 * COMPACT_SET_COUNT * COMPACT_TRANSPOSE_COUNT)
    self.assertEqual(dense[0].valid, 0)
    self.assertGreater(dense[0].ox_q, 1024)

def test_render_emits_compact_direct_index_contract(self) -> None:
    text = render(compact_entries([_entry(0, 19)], lat_count=2, size_count=3), 2, 3)
    self.assertIn("g_lardLfnstSkip21TheoryCompactTable", text)
    self.assertIn("LARD_LFNST_SKIP21_COMPACT_TABLE_SIZE", text)
    self.assertNotIn("modeGroup", text)
    self.assertNotIn("qpBucket", text)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip21_theory_table -v
```

Expected: FAIL because `CompactTheoryEntry`, `compact_index`, and `compact_entries` do not exist and the generated table still contains six key fields.

- [ ] **Step 3: Implement compact generation**

Add constants and a compact dataclass:

```python
COMPACT_SET_COUNT = 4
COMPACT_TRANSPOSE_COUNT = 2
INVALID_METRIC_Q = 32767

@dataclass(frozen=True)
class CompactTheoryEntry:
    valid: int
    support_ratio_q: int
    ox_q: int
    diag_dominance_q: int
    g1_cov_q: int
    g2_cov_q: int
    gmax_cov_q: int
    diff_cov_q: int
```

Add pure packing and collapse functions:

```python
def compact_index(lat_bin: int, size_id: int, set_idx: int, transpose: int, *, size_count: int) -> int:
    return (((lat_bin * size_count + size_id) * COMPACT_SET_COUNT + set_idx)
            * COMPACT_TRANSPOSE_COUNT + transpose)

def compact_entries(entries: list[TheoryEntry], *, lat_count: int, size_count: int) -> list[CompactTheoryEntry]:
    invalid = CompactTheoryEntry(0, 0, INVALID_METRIC_Q, 0, 0, 0, INVALID_METRIC_Q, 0)
    dense = [invalid] * (lat_count * size_count * COMPACT_SET_COUNT * COMPACT_TRANSPOSE_COUNT)
    for source in entries:
        value = CompactTheoryEntry(
            1, source.support_ratio_q, source.ox_q, source.diag_dominance_q,
            source.g1_cov_q, source.g2_cov_q, source.gmax_cov_q, source.diff_cov_q,
        )
        idx = compact_index(source.lat_bin, source.size_id, source.set_idx,
                            source.transpose, size_count=size_count)
        if dense[idx].valid and dense[idx] != value:
            raise ValueError(f"inconsistent compact theory metrics at index {idx}")
        dense[idx] = value
    return dense
```

Change `render()` to emit `LardLfnstSkip21TheoryCompactEntry`, the four dimension constants, and `g_lardLfnstSkip21TheoryCompactTable`. Change `main()` to collapse `generate_entries(...)` with `lat_count=len(LAT_BINS)` and `size_count=len(SIZES)` before rendering.

- [ ] **Step 4: Run focused tests and regenerate the table**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_theory_table -v
python -m tools.lard_lfnst.generate_skip21_theory_table
python -m unittest tools.lard_lfnst.test_skip21_theory_table -v
```

Expected: all compact-table tests PASS; generator reports 560 compact entries (`7 x 10 x 4 x 2`); the include contains no `modeGroup`, `qpBucket`, or 13,440-row size macro.

- [ ] **Step 5: Commit the compact generator and table**

```powershell
git add tools/lard_lfnst/generate_skip21_theory_table.py tools/lard_lfnst/test_skip21_theory_table.py source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc
git commit -m "perf: generate compact skip21 theory table"
```

### Task 2: Add the Persistent Stage2Debug Configuration

**Files:**
- Modify: `tools/lard_lfnst/test_skip21_stage2_gate.py`
- Modify: `include/vvenc/vvencCfg.h`
- Modify: `source/Lib/vvenc/vvencCfg.cpp`
- Modify: `source/Lib/apputils/VVEncAppCfg.h`

- [ ] **Step 1: Write the failing configuration test**

Extend `test_cpp_exposes_independent_stage2_mode` with:

```python
self.assertIn("m_LardLfnst21Stage2Debug", cfg_h)
self.assertIn("LardLfnst21Stage2Debug", app_cfg)
self.assertIn("0 normal, 1 NoLookup, 2 NullLookup", app_cfg)
self.assertIn("LardLfnst21Stage2Debug out of range [0..2]", vvenc_cfg)
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage2_gate.Skip21Stage2GateTests.test_cpp_exposes_independent_stage2_mode -v
```

Expected: FAIL because the debug configuration is absent.

- [ ] **Step 3: Add the configuration field and CLI aliases**

Add after `m_LardLfnst21Stage2Profile`:

```cpp
int m_LardLfnst21Stage2Debug; // 0 normal, 1 NoLookup, 2 NullLookup
```

Initialize it to zero in `vvenc_set_default()` and validate it in `vvenc_check_config()`:

```cpp
c->m_LardLfnst21Stage2Debug = 0;
vvenc_confirmParameter( c, c->m_LardLfnst21Stage2Debug < 0 || c->m_LardLfnst21Stage2Debug > 2,
                        "LardLfnst21Stage2Debug out of range [0..2]" );
```

Add lowercase and canonical app options with the exact description `Skip21 Stage2 debug: 0 normal, 1 NoLookup, 2 NullLookup`.

- [ ] **Step 4: Run the focused test**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage2_gate -v
```

Expected: all Stage-2 gate tests PASS.

- [ ] **Step 5: Commit the debug configuration**

```powershell
git add tools/lard_lfnst/test_skip21_stage2_gate.py include/vvenc/vvencCfg.h source/Lib/vvenc/vvencCfg.cpp source/Lib/apputils/VVEncAppCfg.h
git commit -m "feat: add skip21 stage2 debug modes"
```

### Task 3: Replace Linear Search with Direct Runtime Indexing

**Files:**
- Modify: `tools/lard_lfnst/test_skip21_stage2_gate.py`
- Modify: `tools/lard_lfnst/test_skip21_theory_table.py`
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`

- [ ] **Step 1: Write failing runtime-structure tests**

Add assertions that state the runtime contract:

```python
self.assertIn("xLardSkip21CompactTheoryEntry", source)
self.assertIn("LARD_LFNST_SKIP21_COMPACT_SIZE_COUNT", source)
self.assertIn("g_lardLfnstSkip21TheoryCompactTable[idx]", source)
self.assertNotIn("xLardSkip21FindTheoryEntry", source)
self.assertNotIn("for( int idx = 0; idx < LARD_LFNST_SKIP21_THEORY_TABLE_SIZE", source)
self.assertIn("if( stage2Debug == 1 )", source)
self.assertIn("if( stage2Debug == 2 )", source)
self.assertIn("stage2Enabled && !d.stage1EarlyZero", source)
```

Also assert that `xLardSkip21QpBucket` and Stage-2 assignment to `d.modeGroup` are absent from the compact runtime path.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage2_gate tools.lard_lfnst.test_skip21_theory_table -v
```

Expected: FAIL because the linear finder and six-dimensional key calculation still exist.

- [ ] **Step 3: Implement direct compact access**

Replace the finder with:

```cpp
static const LardLfnstSkip21TheoryCompactEntry* xLardSkip21CompactTheoryEntry(
  const int latBin, const int sizeId, const int setIdx, const int transpose )
{
  if( latBin < 0 || latBin >= LARD_LFNST_SKIP21_COMPACT_LAT_COUNT
      || sizeId < 0 || sizeId >= LARD_LFNST_SKIP21_COMPACT_SIZE_COUNT
      || setIdx < 0 || setIdx >= LARD_LFNST_SKIP21_COMPACT_SET_COUNT
      || transpose < 0 || transpose >= LARD_LFNST_SKIP21_COMPACT_TRANSPOSE_COUNT )
  {
    return nullptr;
  }
  const int idx = (((latBin * LARD_LFNST_SKIP21_COMPACT_SIZE_COUNT + sizeId)
                    * LARD_LFNST_SKIP21_COMPACT_SET_COUNT + setIdx)
                   * LARD_LFNST_SKIP21_COMPACT_TRANSPOSE_COUNT + transpose);
  const auto& entry = g_lardLfnstSkip21TheoryCompactTable[idx];
  return entry.valid ? &entry : nullptr;
}
```

Change `xLardSkip21Stage2WeakCoupling` to accept the compact entry type. Restructure `xLardSkip21EarlyDecision` so support is computed only for enabled Stage 1 or active tracing. Compute `setIdx`/`transpose` and access the compact table only when Stage 2 is enabled, Stage 1 did not trigger, and debug mode is not NoLookup.

For debug mode 1, skip all Stage-2 key work. For debug mode 2, execute direct lookup and gate comparison, populate diagnostic metrics, but leave `d.stage2EarlyZero` false. For mode 0, assign the gate result. Remove `xLardSkip21QpBucket` and do not calculate `modeGroup` for Stage-2 decisions; retain diagnostic `-1` when it is not required.

- [ ] **Step 4: Run focused tests**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_theory_table tools.lard_lfnst.test_skip21_stage2_gate -v
```

Expected: all tests PASS and source scans find no linear Stage-2 lookup.

- [ ] **Step 5: Build the encoder**

```powershell
cmake -S . -B build-lfnst2nd -DCMAKE_BUILD_TYPE=Release
cmake --build build-lfnst2nd --config Release --target vvencFFapp -j 20
```

Expected: `vvencFFapp` builds successfully with no missing compact symbols.

- [ ] **Step 6: Commit the runtime optimization**

```powershell
git add source/Lib/EncoderLib/IntraSearch.cpp tools/lard_lfnst/test_skip21_stage2_gate.py tools/lard_lfnst/test_skip21_theory_table.py
git commit -m "perf: use direct skip21 stage2 lookup"
```

### Task 4: Add Explicit Compact Validation Profiles

**Files:**
- Modify: `tools/lard_lfnst/test_skip21_stage2_validation.py`
- Modify: `tools/lard_lfnst/run_skip21_stage2_validation.py`
- Modify: `tools/server_run_skip21_stage2_validation.sh`

- [ ] **Step 1: Write failing runner-profile tests**

Add:

```python
def test_compact_debug_profiles_are_explicit(self) -> None:
    self.assertIn("LardLfnst21Stage2Debug=1", runner.PROFILES["S2_D3_NoLookup"])
    self.assertIn("LardLfnst21Stage2Debug=2", runner.PROFILES["S2_D3_NullLookup"])
    self.assertIn("LardLfnst21Stage2Debug=0", runner.PROFILES["S2_D3_compact"])
    self.assertEqual(
        runner.DEFAULT_PROFILES,
        "S2_D3_NoLookup,S2_D3_NullLookup,S2_D3_compact",
    )
```

Extend the command test to assert the proposed additional string contains Stage2 profile 2 and the requested debug mode.

- [ ] **Step 2: Run the runner tests and verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage2_validation -v
```

Expected: FAIL because the three compact profiles are absent.

- [ ] **Step 3: Add profiles and server default**

```python
"S2_D3_NoLookup": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Debug=1",
"S2_D3_NullLookup": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Debug=2",
"S2_D3_compact": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Debug=0",
```

Set Python and Bash defaults to `S2_D3_NoLookup,S2_D3_NullLookup,S2_D3_compact`. Keep existing profiles for reproducibility.

- [ ] **Step 4: Run runner and regression tests**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage2_validation tools.lard_lfnst.test_skip21_stage2_gate tools.lard_lfnst.test_skip21_theory_table -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit validation profiles**

```powershell
git add tools/lard_lfnst/run_skip21_stage2_validation.py tools/lard_lfnst/test_skip21_stage2_validation.py tools/server_run_skip21_stage2_validation.sh
git commit -m "test: add skip21 stage2 overhead profiles"
```

### Task 5: Full Verification and Clean-Server Experiment

**Files:**
- Verify: all Task 1-4 files
- Server output: `/root/vvenc_lard_exp/runs/skip21_stage2_compact_validation_<timestamp>`

- [ ] **Step 1: Run the relevant Python suite**

```powershell
python -m unittest tools.lard_lfnst.test_skip21_theory_table tools.lard_lfnst.test_skip21_theory_sanity tools.lard_lfnst.test_skip21_stage2_gate tools.lard_lfnst.test_skip21_stage2_validation tools.lard_lfnst.test_skip21_stage1_diagnostic_summary -v
```

Expected: all tests PASS with zero failures and errors.

- [ ] **Step 2: Prove generated output is deterministic**

```powershell
git diff --exit-code -- source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc
python -m tools.lard_lfnst.generate_skip21_theory_table
git diff --exit-code -- source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc
```

Expected: both diff commands exit 0.

- [ ] **Step 3: Rebuild Release**

```powershell
cmake --build build-lfnst2nd --config Release --target vvencFFapp -j 20
```

Expected: build exits 0.

- [ ] **Step 4: Upload only changed files**

Upload Task 1-4 source, generated table, runners, and tests to their matching paths under `/root/vvenc_lard_exp/vvenc-1.12.0-lard-src` and `/root/vvenc_lard_exp/tools`. Do not overwrite or delete the source YUV.

- [ ] **Step 5: Run a one-frame server smoke test**

```bash
PROFILES=S2_D3_NoLookup,S2_D3_NullLookup,S2_D3_compact FRAMES=1 REPEATS=1 QPS=32 THREADS=20 OUT=/root/vvenc_lard_exp/runs/skip21_stage2_compact_smoke_<timestamp> /root/vvenc_lard_exp/server_run_skip21_stage2_validation.sh
```

Expected: three summaries are generated; NoLookup and NullLookup report zero BDBR/byte delta and stable hashes; cleanup leaves no reconstructed YUV or `.vvc` files.

- [ ] **Step 6: Run the full paired validation**

```bash
PROFILES=S2_D3_NoLookup,S2_D3_NullLookup,S2_D3_compact FRAMES=8 REPEATS=5 QPS=22,27,32,37 THREADS=20 PRESET=medium OUT=/root/vvenc_lard_exp/runs/skip21_stage2_compact_validation_<timestamp> /root/vvenc_lard_exp/server_run_skip21_stage2_validation.sh
```

Expected: all profile summaries and aggregate JSON are generated; server process exits 0; cleanup leaves no reconstructed YUV or `.vvc` files.

- [ ] **Step 7: Report the decision table**

Extract `median_TS_pct`, `mean_TS_pct`, `positive_repeats`, `std_TS_pct`, four Y-BDBR metrics, `ByteDelta_pct`, and hash stability for each profile.

Interpret in order:

- NoLookup negative: investigate insertion-point/call overhead.
- NoLookup near zero and NullLookup negative: investigate key/lookup cost.
- Both debug modes near zero and compact D3 negative: coverage does not save enough time.
- Compact D3 near zero or positive with RD near +0.083% max Y-BDBR: proceed to a separate Stage1 E15-noLat + Stage2 D3 validation.

- [ ] **Step 8: Handle a runner defect only through RED/GREEN**

If smoke testing exposes a reproducible runner defect, add a failing test, verify RED, apply the minimal fix, rerun the focused suite, and commit only affected runner/test files:

```powershell
git commit -m "fix: correct skip21 compact validation runner"
```

Do not alter D3 thresholds or gate semantics to make timing results pass.
