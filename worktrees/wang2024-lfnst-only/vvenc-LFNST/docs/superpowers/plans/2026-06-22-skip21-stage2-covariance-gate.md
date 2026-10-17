# Skip21 Stage 2 Covariance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate Skip21 Stage 2 as an independent pre-candidate early `{0}` gate based on low-frequency covariance weak coupling.

**Architecture:** Stage 1 remains the support-degeneration gate, with `E15-noLat` retained as the current main profile. Stage 2 must run at the same early location before nonzero LFNST candidate setup, using only an offline theory table keyed by geometry and LFNST metadata. Online code performs table lookup and threshold comparison only; it must not compute covariance matrices or use RD-trained masks.

**Tech Stack:** VVenC C++ encoder options in `include/vvenc/vvencCfg.h`, `source/Lib/vvenc/vvencCfg.cpp`, `source/Lib/apputils/VVEncAppCfg.h`, early LFNST logic in `source/Lib/EncoderLib/IntraSearch.cpp`, generated theory data in `source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc`, and Python diagnostics under `tools/lard_lfnst/`.

---

## File Structure

- Modify `include/vvenc/vvencCfg.h`: add Stage 2 profile config and comments for Stage 2 mode semantics.
- Modify `source/Lib/vvenc/vvencCfg.cpp`: initialize and range-check Stage 2 profile and updated stage mode.
- Modify `source/Lib/apputils/VVEncAppCfg.h`: expose CLI options for Stage 2-only and combined Stage1+Stage2 runs.
- Modify `source/Lib/EncoderLib/IntraSearch.cpp`: add independent Stage 2 weak-coupling decision before nonzero LFNST candidate setup.
- Modify `source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc`: extend entries to carry `oxQ` and `diagDominanceQ`.
- Modify `tools/lard_lfnst/generate_skip21_theory_table.py`: generate the extended theory table from analytical covariance metrics.
- Modify `tools/lard_lfnst/run_skip21_stage1_diagnostic_summary.py`: generalize summary fields from Stage 1-only to Stage 1/Stage 2 overlap diagnostics.
- Create `tools/lard_lfnst/run_skip21_stage2_validation.py`: run Stage2-only and Stage1+Stage2 profiles with paired repeats.
- Create `tools/lard_lfnst/test_skip21_stage2_config.py`: verify CLI/config semantics.
- Create `tools/lard_lfnst/test_skip21_stage2_decision.py`: verify C++ source contains the early Stage 2 lookup path and no late-only dependence.
- Create `tools/lard_lfnst/test_skip21_stage2_diagnostics.py`: verify summary bins and overlap fields.

## Stage Mode Semantics

Use explicit mode values so Stage2-only can be tested without Stage 1:

- `LardLfnst21Stages=1`: Stage 1 support gate only.
- `LardLfnst21Stages=2`: Stage 2 covariance weak-coupling gate only.
- `LardLfnst21Stages=3`: Stage 1 OR Stage 2 combined early gate.

Add a separate Stage 2 profile option instead of overloading the Stage 1 profile list:

- `LardLfnst21Profile=6`: current Stage 1 main profile, `E15-noLat`.
- `LardLfnst21Stage2Profile=0`: `D1`, conservative weak-coupling gate.
- `LardLfnst21Stage2Profile=1`: `D2`, main weak-coupling gate.
- `LardLfnst21Stage2Profile=2`: `D3`, aggressive weak-coupling gate with a guard.

## Task 1: Stage 2 Config Surface

**Files:**
- Modify: `include/vvenc/vvencCfg.h`
- Modify: `source/Lib/vvenc/vvencCfg.cpp`
- Modify: `source/Lib/apputils/VVEncAppCfg.h`
- Test: `tools/lard_lfnst/test_skip21_stage2_config.py`

- [ ] **Step 1: Write the failing config test**

```python
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Skip21Stage2ConfigTest(unittest.TestCase):
    def test_stage2_profile_and_mode_are_exposed(self) -> None:
        cfg_h = (ROOT / "include/vvenc/vvencCfg.h").read_text(encoding="utf-8")
        app_cfg = (ROOT / "source/Lib/apputils/VVEncAppCfg.h").read_text(encoding="utf-8")
        vvenc_cfg = (ROOT / "source/Lib/vvenc/vvencCfg.cpp").read_text(encoding="utf-8")

        self.assertIn("m_LardLfnst21Stage2Profile", cfg_h)
        self.assertIn("LardLfnst21Stage2Profile", app_cfg)
        self.assertIn("LardLfnst21Stage2Profile out of range [0..2]", vvenc_cfg)
        self.assertIn("LardLfnst21Stages out of range [1..3]", vvenc_cfg)
        self.assertIn("1: Stage1 only, 2: Stage2 only, 3: Stage1+Stage2", app_cfg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_config`

Expected: FAIL because `m_LardLfnst21Stage2Profile` is not present.

- [ ] **Step 3: Add config storage and CLI option**

In `include/vvenc/vvencCfg.h`, add:

```cpp
int                 m_LardLfnst21Stage2Profile;                                          // Skip21 Stage2 weak-coupling profile: 0 D1, 1 D2, 2 D3
```

In `source/Lib/vvenc/vvencCfg.cpp`, initialize it to `1` near other LFNST defaults:

```cpp
m_LardLfnst21Stage2Profile = 1;
```

Add range validation:

```cpp
CHECK_RANGE( m_LardLfnst21Stage2Profile, 0, 2, "LardLfnst21Stage2Profile out of range [0..2]" );
```

In `source/Lib/apputils/VVEncAppCfg.h`, expose:

```cpp
( "LardLfnst21Stage2Profile", m_cEncCfg.m_LardLfnst21Stage2Profile, 1, "Skip21 Stage2 weak-coupling profile: 0 D1, 1 D2, 2 D3" )
```

Update the existing `LardLfnst21Stages` help text to:

```cpp
"Skip21 stage mode: 1: Stage1 only, 2: Stage2 only, 3: Stage1+Stage2"
```

- [ ] **Step 4: Run the config test to verify it passes**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_config`

Expected: OK.

## Task 2: Extended Theory Table Schema

**Files:**
- Modify: `source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc`
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`
- Create: `tools/lard_lfnst/generate_skip21_theory_table.py`
- Test: `tools/lard_lfnst/test_skip21_stage2_decision.py`

- [ ] **Step 1: Write the failing schema test**

```python
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Skip21Stage2DecisionTest(unittest.TestCase):
    def test_theory_entry_carries_covariance_weak_coupling_metrics(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        table = (ROOT / "source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc").read_text(encoding="utf-8")

        self.assertIn("oxQ", source)
        self.assertIn("diagDominanceQ", source)
        self.assertIn("gmaxCovQ", source)
        self.assertIn("xLardSkip21Stage2WeakCoupling", source)
        self.assertIn("stage2EarlyZero", source)
        self.assertIn("oxQ", table)
        self.assertIn("diagDominanceQ", table)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the schema test to verify it fails**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_decision`

Expected: FAIL because `oxQ` and `diagDominanceQ` are absent or unused.

- [ ] **Step 3: Extend the C++ theory entry**

In `source/Lib/EncoderLib/IntraSearch.cpp`, update the Skip21 table entry struct to this shape:

```cpp
struct LardSkip21TheoryEntry
{
  uint8_t latBin;
  uint8_t sizeId;
  uint8_t modeGroup;
  uint8_t setIdx;
  uint8_t transpose;
  int16_t supportRatioQ;
  int16_t oxQ;
  int16_t diagDominanceQ;
  int16_t g1CovQ;
  int16_t g2CovQ;
  int16_t gmaxCovQ;
  int16_t diffCovQ;
};
```

- [ ] **Step 4: Generate table entries with covariance fields**

Create `tools/lard_lfnst/generate_skip21_theory_table.py` with a deterministic generator that writes entries in the C++ initializer format:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OUT = Path("source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc")


@dataclass(frozen=True)
class Entry:
    lat_bin: int
    size_id: int
    mode_group: int
    set_idx: int
    transpose: int
    support_ratio_q: int
    ox_q: int
    diag_dominance_q: int
    g1_cov_q: int
    g2_cov_q: int
    gmax_cov_q: int
    diff_cov_q: int


def render(entries: list[Entry]) -> str:
    lines = [
        "static const LardSkip21TheoryEntry g_lardSkip21TheoryTable[] =",
        "{",
    ]
    for e in entries:
        lines.append(
            f"  {{ {e.lat_bin}, {e.size_id}, {e.mode_group}, {e.set_idx}, {e.transpose}, "
            f"{e.support_ratio_q}, {e.ox_q}, {e.diag_dominance_q}, "
            f"{e.g1_cov_q}, {e.g2_cov_q}, {e.gmax_cov_q}, {e.diff_cov_q} }},"
        )
    lines.extend(["};", ""])
    return "\n".join(lines)
```

Replace the toy entries with the current analytical table values when implementing the generator.

- [ ] **Step 5: Run schema test and existing Stage 1 tests**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_decision tools.lard_lfnst.test_skip21_profile_profiles tools.lard_lfnst.test_skip21_diagnostic_summary`

Expected: OK.

## Task 3: Independent Stage 2 Early Decision

**Files:**
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`
- Test: `tools/lard_lfnst/test_skip21_stage2_decision.py`

- [ ] **Step 1: Extend the failing decision test**

Add this assertion to `test_skip21_stage2_decision.py`:

```python
    def test_stage2_can_run_without_stage1(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")

        self.assertIn("const bool stage1Enabled = cfg->m_LardLfnst21Stages == 1 || cfg->m_LardLfnst21Stages == 3", source)
        self.assertIn("const bool stage2Enabled = cfg->m_LardLfnst21Stages == 2 || cfg->m_LardLfnst21Stages == 3", source)
        self.assertIn("if( stage2Enabled && !d.stage1EarlyZero", source)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_decision`

Expected: FAIL because current code treats Stage 2 as `stages >= 2` after Stage 1.

- [ ] **Step 3: Implement profile thresholds**

Add a Stage 2 profile table in `IntraSearch.cpp`:

```cpp
struct LardSkip21Stage2ProfileParams
{
  int16_t oxMaxQ;
  int16_t diagMinQ;
  int16_t gmaxMaxQ;
  bool useDiagOr;
};

static LardSkip21Stage2ProfileParams xLardSkip21Stage2ProfileParams( const int profile )
{
  static const LardSkip21Stage2ProfileParams params[3] =
  {
    { 200, 820, 240, false }, // D1 conservative
    { 350, 760, 360, false }, // D2 main
    { 500, 720, 420, true  }, // D3 aggressive with diagonal OR
  };
  return params[Clip3( 0, 2, profile )];
}
```

Replace numeric values with offline-theory quantile thresholds after table generation; keep these constants named and reviewed.

- [ ] **Step 4: Implement independent weak-coupling decision**

Add this function:

```cpp
static bool xLardSkip21Stage2WeakCoupling( const LardSkip21TheoryEntry& e, const LardSkip21Stage2ProfileParams& p )
{
  const bool oxWeak = e.oxQ <= p.oxMaxQ;
  const bool gmaxWeak = e.gmaxCovQ <= p.gmaxMaxQ;
  const bool diagDominant = e.diagDominanceQ >= p.diagMinQ;
  return p.useDiagOr ? ( ( oxWeak || diagDominant ) && gmaxWeak ) : ( oxWeak && gmaxWeak );
}
```

Update `xLardSkip21EarlyDecision`:

```cpp
const bool stage1Enabled = cfg->m_LardLfnst21Stages == 1 || cfg->m_LardLfnst21Stages == 3;
const bool stage2Enabled = cfg->m_LardLfnst21Stages == 2 || cfg->m_LardLfnst21Stages == 3;

d.stage1EarlyZero = stage1Enabled && d.supportRatioQ <= params.supportQ && d.latBin >= params.minLatBin;
d.stage2EarlyZero = false;
if( stage2Enabled && !d.stage1EarlyZero && entry )
{
  const LardSkip21Stage2ProfileParams s2 = xLardSkip21Stage2ProfileParams( cfg->m_LardLfnst21Stage2Profile );
  d.stage2EarlyZero = xLardSkip21Stage2WeakCoupling( *entry, s2 );
}
d.earlyZero = d.stage1EarlyZero || d.stage2EarlyZero;
```

- [ ] **Step 5: Run the decision tests**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_decision`

Expected: OK.

## Task 4: Stage 2 Diagnostics and Overlap

**Files:**
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`
- Modify: `tools/lard_lfnst/run_skip21_stage1_diagnostic_summary.py`
- Test: `tools/lard_lfnst/test_skip21_stage2_diagnostics.py`

- [ ] **Step 1: Write the failing diagnostic summary test**

```python
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Skip21Stage2DiagnosticsTest(unittest.TestCase):
    def test_summary_reports_stage2_bins_and_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = tmp / "stage.csv"
            out = tmp / "summary.json"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "qp", "x", "y", "w", "h", "eligible", "stage1EarlyZero",
                        "stage2EarlyZero", "earlyZero", "supportRatioQ", "oxQ",
                        "diagDominanceQ", "gmaxCovQ", "latBin", "modeGroup",
                        "setIdx", "transpose",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "qp": "22", "x": "0", "y": "0", "w": "16", "h": "16",
                    "eligible": "1", "stage1EarlyZero": "0", "stage2EarlyZero": "1",
                    "earlyZero": "1", "supportRatioQ": "700", "oxQ": "180",
                    "diagDominanceQ": "840", "gmaxCovQ": "200", "latBin": "2",
                    "modeGroup": "1", "setIdx": "0", "transpose": "0",
                })
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.lard_lfnst.run_skip21_stage1_diagnostic_summary",
                    "--stage1-csv",
                    str(csv_path),
                    "--out",
                    str(out),
                ],
                cwd=ROOT,
                check=True,
            )
            data = json.loads(out.read_text(encoding="utf-8"))
            profile = next(iter(data["profiles"].values()))
            self.assertEqual(profile["stage2_early_zero_count"], 1)
            self.assertEqual(profile["overlap"]["s2_only"], 1)
            self.assertIn("by_ox_bin", profile)
            self.assertIn("by_diag_dominance_bin", profile)
            self.assertIn("by_gmax_cov_bin", profile)
```

- [ ] **Step 2: Run the diagnostic test to verify it fails**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_diagnostics`

Expected: FAIL because Stage 2 columns and overlap are not summarized.

- [ ] **Step 3: Extend CSV stat output**

Add these columns to `xLardSkip21AppendStage1Stat`:

```text
stage2EarlyZero, oxQ, diagDominanceQ, gmaxCovQ
```

Populate them from the matched theory entry. Use empty or `-1` values for non-table cases.

- [ ] **Step 4: Extend Python summary**

In `run_skip21_stage1_diagnostic_summary.py`, count:

```python
stage1_early_zero_count
stage2_early_zero_count
overlap = {
    "s1_and_s2": count_s1_and_s2,
    "s1_only": count_s1_only,
    "s2_only": count_s2_only,
    "neither": count_neither,
}
```

Add bins:

```python
by_ox_bin
by_diag_dominance_bin
by_gmax_cov_bin
```

- [ ] **Step 5: Run diagnostic tests**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_diagnostics tools.lard_lfnst.test_skip21_diagnostic_summary`

Expected: OK.

## Task 5: Stage 2 Validation Runner

**Files:**
- Create: `tools/lard_lfnst/run_skip21_stage2_validation.py`
- Test: `tools/lard_lfnst/test_skip21_stage2_validation.py`

- [ ] **Step 1: Write the failing runner test**

```python
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Skip21Stage2ValidationRunnerTest(unittest.TestCase):
    def test_runner_defines_stage2_only_and_joint_profiles(self) -> None:
        source = (ROOT / "tools/lard_lfnst/run_skip21_stage2_validation.py").read_text(encoding="utf-8")

        self.assertIn("S2_D1_only", source)
        self.assertIn("S2_D2_only", source)
        self.assertIn("S2_D3_only", source)
        self.assertIn("S12_E15_noLat_D1", source)
        self.assertIn("S12_E15_noLat_D2", source)
        self.assertIn("LardLfnst21Stages=2", source)
        self.assertIn("LardLfnst21Stages=3", source)
        self.assertIn("LardLfnst21Stage2Profile", source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the runner test to verify it fails**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_validation`

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement validation profile matrix**

Create the profile definitions:

```python
PROFILES = {
    "S2_D1_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=0",
    "S2_D2_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=1",
    "S2_D3_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2",
    "S12_E15_noLat_D1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=3 LardLfnst21Profile=6 LardLfnst21Stage2Profile=0",
    "S12_E15_noLat_D2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=3 LardLfnst21Profile=6 LardLfnst21Stage2Profile=1",
}
```

Reuse the paired-repeat orchestration style from `tools/lard_lfnst/run_skip21_stage1_validation.py`.

- [ ] **Step 4: Run runner tests**

Run: `python -m unittest tools.lard_lfnst.test_skip21_stage2_validation`

Expected: OK.

## Task 6: Server Experiment Protocol

**Files:**
- Create: `tools/server_run_skip21_stage2_validation.sh`
- Modify: `tools/lard_server_exec.py` only if the existing upload/exec wrapper cannot run the new shell script.

- [ ] **Step 1: Add server script with explicit clean outputs**

The script must run:

```bash
python -m tools.lard_lfnst.run_skip21_stage2_validation \
  --sequence AerialCity \
  --orig /data/sequences/AerialCity_3840x1920_30fps_8bit_420_erp.yuv \
  --qps 22,27,32,37 \
  --frames 8 \
  --threads 20 \
  --preset medium \
  --repeats 5 \
  --profiles S2_D1_only,S2_D2_only,S2_D3_only
```

Then run the combined profiles:

```bash
python -m tools.lard_lfnst.run_skip21_stage2_validation \
  --sequence AerialCity \
  --orig /data/sequences/AerialCity_3840x1920_30fps_8bit_420_erp.yuv \
  --qps 22,27,32,37 \
  --frames 8 \
  --threads 20 \
  --preset medium \
  --repeats 5 \
  --profiles S12_E15_noLat_D1,S12_E15_noLat_D2
```

- [ ] **Step 2: Add cleanup guard**

At the end of the server script, delete temporary reconstructed YUV and bitstream files:

```bash
find "$RUN_ROOT" -type f \( -name '*_rec.yuv' -o -name '*.vvc' \) -delete
```

- [ ] **Step 3: Verify no large files remain**

Run on the server:

```bash
find "$RUN_ROOT" -type f \( -name '*_rec.yuv' -o -name '*.vvc' \) -print
du -sh "$RUN_ROOT"
```

Expected: no rec/bitstream files printed; result directory is small enough to fetch.

## Validation Checklist

- [ ] `python -m unittest tools.lard_lfnst.test_skip21_stage2_config`
- [ ] `python -m unittest tools.lard_lfnst.test_skip21_stage2_decision`
- [ ] `python -m unittest tools.lard_lfnst.test_skip21_stage2_diagnostics`
- [ ] `python -m unittest tools.lard_lfnst.test_skip21_stage2_validation`
- [ ] `python -m unittest tools.lard_lfnst.test_skip21_diagnostic_summary tools.lard_lfnst.test_skip21_profile_profiles tools.lard_lfnst.test_skip21_stage1_stats`
- [ ] Build encoder: `cmake --build build-lahtp --target vvencFFapp --config Release -j 20`
- [ ] Stage2-only diagnostic run: `LardLfnst21Stages=2` with D1/D2/D3.
- [ ] Stage1+Stage2 diagnostic run: `LardLfnst21Stages=3` with `E15-noLat + D1/D2`.

## Stage 2 Experiment Acceptance Criteria

- Stage2-only target: median TS greater than 3%, max Y-BDBR less than 0.5%, and TS/maxY greater than 10.
- Stage1+Stage2 target: median TS greater than 6% or 7%, max Y-BDBR less than or equal to 0.5%, and TS/maxY greater than 10.
- Required diagnostics: `S1 ∩ S2`, `S1 only`, `S2 only`, `neither`, `by_ox_bin`, `by_diag_dominance_bin`, `by_gmax_cov_bin`, `by_qp`, `by_size`, `by_lat_bin`, `by_mode_group`, `by_setIdx`, `by_transpose`, and anchor final `lfnstIdx` distribution for Stage2 early regions.
- Stop condition: if Stage2-only mostly overlaps Stage1 and contributes little `S2 only` coverage, treat Stage 2 as a supplement rather than a peer main accelerator.
