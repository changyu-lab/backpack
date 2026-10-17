# Skip21 Stage-1 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add separated Skip21 Stage-1 diagnostics and run the E5/E10 validation matrix without contaminating formal timing runs.

**Architecture:** Formal TS/BDBR runs continue through `tools/lard_lfnst/run_skip18_paired_repeats.py` with no per-decision CSV. A new Skip21 diagnostic config option writes Stage-1 decision rows only when explicitly enabled, and new Python tooling aggregates those rows into `diagnostic_stats`. A thin validation orchestrator combines existing timing summaries with separate diagnostic summaries.

**Tech Stack:** C++ vvenc encoder config and `IntraSearch.cpp`; Python 3 standard library; existing 360 metric runner; `unittest`; CMake build.

---

## File Structure

- Modify `include/vvenc/vvencCfg.h`: add `m_LardLfnst21StatFile`.
- Modify `source/Lib/vvenc/vvencCfg.cpp`: initialize, sanitize, and validate the new char array.
- Modify `source/Lib/apputils/VVEncAppCfg.h`: expose `LardLfnst21StatFile` and `lardlfnst21statfile`.
- Modify `source/Lib/EncoderLib/IntraSearch.cpp`: refactor Skip21 early decision into a struct and write diagnostic CSV rows only when `m_LardLfnst21StatFile` is set.
- Create `tools/lard_lfnst/summarize_skip21_stage1_stats.py`: aggregate Stage-1 diagnostic CSV and optional final trace CSV.
- Create `tools/lard_lfnst/run_skip21_stage1_validation.py`: run formal timing commands separately from diagnostic commands and write a combined validation report.
- Create `tools/lard_lfnst/test_skip21_stage1_stats.py`: unit tests for diagnostic aggregation.
- Modify `tools/lard_lfnst/test_skip18_paired_repeats.py`: add config plumbing assertions for the new Skip21 stat option.

---

### Task 1: Add Skip21 Diagnostic Config Plumbing

**Files:**
- Modify: `include/vvenc/vvencCfg.h`
- Modify: `source/Lib/vvenc/vvencCfg.cpp`
- Modify: `source/Lib/apputils/VVEncAppCfg.h`
- Modify: `tools/lard_lfnst/test_skip18_paired_repeats.py`

- [ ] **Step 1: Add failing config-plumbing assertions**

Append this test to `tools/lard_lfnst/test_skip18_paired_repeats.py`:

```python
    def test_skip21_stat_file_option_is_plumbed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        cfg_h = (root / "include" / "vvenc" / "vvencCfg.h").read_text(
            encoding="utf-8"
        )
        cfg_cpp = (root / "source" / "Lib" / "vvenc" / "vvencCfg.cpp").read_text(
            encoding="utf-8"
        )
        app_cfg = (root / "source" / "Lib" / "apputils" / "VVEncAppCfg.h").read_text(
            encoding="utf-8"
        )

        self.assertIn("m_LardLfnst21StatFile", cfg_h)
        self.assertIn("memset( c->m_LardLfnst21StatFile", cfg_cpp)
        self.assertIn("vvenc_checkCharArrayStr( c->m_LardLfnst21StatFile", cfg_cpp)
        self.assertIn('"lardlfnst21statfile"', app_cfg)
        self.assertIn('"LardLfnst21StatFile"', app_cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip18_paired_repeats.Skip18PairedRepeatTests.test_skip21_stat_file_option_is_plumbed -v
```

Expected: FAIL because `m_LardLfnst21StatFile` is not defined yet.

- [ ] **Step 3: Add the config field**

In `include/vvenc/vvencCfg.h`, add the new field directly after `m_LardLfnst18StatFile`:

```cpp
  char                m_LardLfnst21StatFile[VVENC_MAX_STRING_LEN];                       // Skip21 Stage-1 diagnostic CSV, not used for formal timing runs
```

- [ ] **Step 4: Initialize and sanitize the field**

In `source/Lib/vvenc/vvencCfg.cpp`, add this after the existing `m_LardLfnst18StatFile` memset:

```cpp
  memset( c->m_LardLfnst21StatFile, '\0', sizeof(c->m_LardLfnst21StatFile) );
```

Add this after the existing `vvenc_checkCharArrayStr( c->m_LardLfnst18StatFile, VVENC_MAX_STRING_LEN);` line:

```cpp
  vvenc_checkCharArrayStr( c->m_LardLfnst21StatFile, VVENC_MAX_STRING_LEN);
```

- [ ] **Step 5: Expose CLI/config options**

In `source/Lib/apputils/VVEncAppCfg.h`, add an `IStreamToArr` next to the `toLardLfnst18StatFile` binding:

```cpp
  IStreamToArr<char>                toLardLfnst21StatFile          ( &c->m_LardLfnst21StatFile[0], VVENC_MAX_STRING_LEN  );
```

In the lowercase option block, add:

```cpp
    ("lardlfnst21statfile",                            toLardLfnst21StatFile,                          "CSV Skip21 Stage-1 diagnostic decisions; not for formal timing runs")
```

In the uppercase option block, add:

```cpp
    ("LardLfnst21StatFile",                            toLardLfnst21StatFile,                          "CSV Skip21 Stage-1 diagnostic decisions; not for formal timing runs")
```

- [ ] **Step 6: Run config-plumbing test**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip18_paired_repeats.Skip18PairedRepeatTests.test_skip21_stat_file_option_is_plumbed -v
```

Expected: PASS.

- [ ] **Step 7: Commit config plumbing**

Run:

```powershell
git add include/vvenc/vvencCfg.h source/Lib/vvenc/vvencCfg.cpp source/Lib/apputils/VVEncAppCfg.h tools/lard_lfnst/test_skip18_paired_repeats.py
git -c gc.auto=0 commit -m "feat: add skip21 stage1 stat option"
```

---

### Task 2: Emit Stage-1 Diagnostic Rows Without Affecting Timing Runs

**Files:**
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`
- Modify: `tools/lard_lfnst/test_skip18_paired_repeats.py`

- [ ] **Step 1: Add failing source-structure assertions**

Append this test to `tools/lard_lfnst/test_skip18_paired_repeats.py`:

```python
    def test_skip21_diagnostic_rows_are_separate_from_timing_stats(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (
            root / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp"
        ).read_text(encoding="utf-8")

        self.assertIn("struct LardSkip21EarlyDecision", source)
        self.assertIn("xLardSkip21EarlyDecision", source)
        self.assertIn("xLardSkip21AppendStage1Stat", source)
        self.assertIn("m_LardLfnst21StatFile", source)
        self.assertNotIn("m_LardLfnst18StatFile, cu.qp, cu.lwidth(), cu.lheight(), lardSkip21", source)
```

- [ ] **Step 2: Run source-structure test to verify it fails**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip18_paired_repeats.Skip18PairedRepeatTests.test_skip21_diagnostic_rows_are_separate_from_timing_stats -v
```

Expected: FAIL because the diagnostic helper is not present.

- [ ] **Step 3: Add the Skip21 decision struct**

In `source/Lib/EncoderLib/IntraSearch.cpp`, near `LardSkip21ProfileParams`, add:

```cpp
struct LardSkip21EarlyDecision
{
  bool eligible = false;
  bool earlyZero = false;
  int latBin = -1;
  int sizeId = -1;
  int modeGroup = -1;
  int setIdx = -1;
  int transpose = -1;
  int supportRatioQ = 0;
  int candidateBefore = 0;
  int candidateAfter = 0;
};
```

- [ ] **Step 4: Refactor the bool helper into a decision helper**

Replace `xLardSkip21EarlyNoNonzero` with this shape, preserving the existing Stage-1 behavior:

```cpp
static LardSkip21EarlyDecision xLardSkip21EarlyDecision( const VVEncCfg* cfg, const CodingUnit& cu )
{
  LardSkip21EarlyDecision d;
  if( !cfg || cfg->m_LardLfnstSkip != 21 || cu.ispMode || cu.mipFlag || cu.bdpcmM[CH_L] )
  {
    return d;
  }

  d.eligible = true;
  d.candidateBefore = 2;
  d.candidateAfter = 2;
  d.supportRatioQ = xLardSkip21SupportRatioQ( cu );
  d.sizeId = xLardSkip21SizeId( cu.lwidth(), cu.lheight() );

  int picH = cu.Y().y + cu.lheight();
  if( cu.cs && cu.cs->pcv )
  {
    picH = cu.cs->pcv->lumaHeight;
  }
  d.latBin = xLardSkip18LatBinCached( picH, cu.Y().y + ( cu.lheight() >> 1 ) );

  uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
  if( CU::isMIP( cu, CH_L ) )
  {
    intraMode = PLANAR_IDX;
  }
  if( intraMode < NUM_INTRA_MODE - 1 )
  {
    const uint32_t mappedMode = xLard2ndGetIntraMode( cu.Y(), intraMode );
    d.setIdx = (int)g_lfnstLut[mappedMode];
    d.transpose = xLard2ndTransposeFlag( mappedMode ) ? 1 : 0;
    d.modeGroup = xLahtpModeGroupId( cu.intraDir[CH_L] );
  }

  const LardSkip21ProfileParams params = xLardSkip21ProfileParams( cfg->m_LardLfnst21Profile );
  d.earlyZero = d.supportRatioQ <= params.supportQ;
  if( !d.earlyZero && cfg->m_LardLfnst21Stages >= 2 && xLardSkip21CovWeakResponse( cu, d.supportRatioQ, params ) )
  {
    d.earlyZero = true;
  }
  if( d.earlyZero )
  {
    d.candidateAfter = 0;
  }
  return d;
}

static bool xLardSkip21EarlyNoNonzero( const VVEncCfg* cfg, const CodingUnit& cu )
{
  return xLardSkip21EarlyDecision( cfg, cu ).earlyZero;
}
```

- [ ] **Step 5: Add a thread-safe diagnostic append helper**

Near the Skip21 helper functions, add:

```cpp
static void xLardSkip21AppendStage1Stat( const char* fileName, const CodingUnit& cu, const LardSkip21EarlyDecision& d )
{
  if( !fileName || fileName[0] == '\0' || !d.eligible )
  {
    return;
  }

  static std::mutex s_mutex;
  std::lock_guard<std::mutex> lock( s_mutex );
  const bool newFile = !std::ifstream( fileName ).good();
  FILE* fp = std::fopen( fileName, "a" );
  if( !fp )
  {
    return;
  }
  if( newFile )
  {
    std::fprintf( fp, "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n" );
  }
  std::fprintf( fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
                cu.qp, cu.lx(), cu.ly(), cu.lwidth(), cu.lheight(),
                d.latBin, d.sizeId, d.modeGroup, d.setIdx, d.transpose,
                d.supportRatioQ, d.earlyZero ? 1 : 0, d.earlyZero ? 1 : 0,
                d.candidateBefore, d.candidateAfter );
  std::fclose( fp );
}
```

- [ ] **Step 6: Call the diagnostic helper at the existing early-gate site**

Replace the current bool-only Skip21 block with:

```cpp
  LardSkip21EarlyDecision lardSkip21Decision;
  if( lardLfnstSkip21 && endLfnstIdx > 0 )
  {
    lardSkip21Decision = xLardSkip21EarlyDecision( m_pcEncCfg, cu );
    xLardSkip21AppendStage1Stat( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst21StatFile : nullptr, cu, lardSkip21Decision );
  }
  const bool lardLfnst21EarlySkip = lardSkip21Decision.earlyZero;
```

Keep the existing `if( lardLfnst21EarlySkip ) { endLfnstIdx = 0; }` block unchanged.

- [ ] **Step 7: Run source-structure test**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip18_paired_repeats.Skip18PairedRepeatTests.test_skip21_diagnostic_rows_are_separate_from_timing_stats -v
```

Expected: PASS.

- [ ] **Step 8: Build the encoder**

Run the existing build command used for this workspace:

```powershell
cmake --build build-lahtp --config Release --parallel 20
```

Expected: build exits 0.

- [ ] **Step 9: Commit diagnostic emission**

Run:

```powershell
git add source/Lib/EncoderLib/IntraSearch.cpp tools/lard_lfnst/test_skip18_paired_repeats.py
git -c gc.auto=0 commit -m "feat: emit skip21 stage1 diagnostics"
```

---

### Task 3: Add Python Diagnostic Aggregation

**Files:**
- Create: `tools/lard_lfnst/summarize_skip21_stage1_stats.py`
- Create: `tools/lard_lfnst/test_skip21_stage1_stats.py`

- [ ] **Step 1: Write failing aggregation tests**

Create `tools/lard_lfnst/test_skip21_stage1_stats.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.lard_lfnst.summarize_skip21_stage1_stats import summarize_stage1_stats


class Skip21Stage1StatsTests(unittest.TestCase):
    def test_aggregates_candidate_reduction_and_ratios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n"
                "22,64,0,32,32,0,4,1,0,0,800,0,0,2,2\n"
                "27,0,512,16,16,3,2,2,1,1,240,1,1,2,0\n",
                encoding="utf-8",
            )

            summary = summarize_stage1_stats(stat)

            self.assertEqual(summary["eligible_count"], 3)
            self.assertEqual(summary["early_zero_count"], 2)
            self.assertAlmostEqual(summary["early_zero_ratio"], 2 / 3)
            self.assertEqual(summary["candidate_before_total"], 6)
            self.assertEqual(summary["candidate_after_total"], 2)
            self.assertAlmostEqual(summary["nonzero_candidate_reduction"], 4 / 6)
            self.assertEqual(summary["by_qp"]["22"]["eligible_count"], 2)
            self.assertAlmostEqual(summary["by_qp"]["22"]["candidate_reduction"], 2 / 4)
            self.assertEqual(summary["by_lat_bin"]["3"]["early_zero_count"], 1)
            self.assertEqual(summary["early_zero_by_support_ratio_bin"]["[0,0.25)"]["early_zero_count"], 2)
            self.assertEqual(summary["early_zero_by_support_ratio_bin"]["[0.75,1.0]"]["early_zero_count"], 0)

    def test_reads_final_lfnst_distribution_without_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            final = Path(tmp) / "trace.final.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"
                "0,0,0,32,32,22,0,0,0,0,0,1\n"
                "0,64,0,32,32,22,0,0,1,0,0,1\n"
                "0,96,0,32,32,22,0,0,2,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_stage1_stats(stat, final)

            self.assertEqual(summary["final_lfnst_idx_distribution"], {"0": 1, "1": 1, "2": 1})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage1_stats -v
```

Expected: FAIL because `summarize_skip21_stage1_stats.py` does not exist.

- [ ] **Step 3: Implement the aggregation module**

Create `tools/lard_lfnst/summarize_skip21_stage1_stats.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SUPPORT_BINS = (
    ("[0,0.25)", 0, 250),
    ("[0.25,0.5)", 250, 500),
    ("[0.5,0.75)", 500, 750),
    ("[0.75,1.0]", 750, 1001),
)


def _empty_group() -> dict[str, int]:
    return {
        "eligible_count": 0,
        "early_zero_count": 0,
        "candidate_before": 0,
        "candidate_after": 0,
    }


def _finalize_group(group: dict[str, int]) -> dict[str, float | int]:
    eligible = group["eligible_count"]
    before = group["candidate_before"]
    after = group["candidate_after"]
    return {
        **group,
        "early_zero_ratio": (group["early_zero_count"] / eligible) if eligible else 0.0,
        "candidate_reduction": ((before - after) / before) if before else 0.0,
    }


def _support_bin(support_ratio_q: int) -> str:
    for name, lo, hi in SUPPORT_BINS:
        if lo <= support_ratio_q < hi:
            return name
    return "[0.75,1.0]"


def _read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _count_final_lfnst(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    counts: Counter[str] = Counter()
    for row in _read_rows(path):
        value = row.get("lfnstIdx")
        if value in {"0", "1", "2"}:
            counts[value] += 1
    return dict(sorted(counts.items()))


def summarize_stage1_stats(stage1_csv: Path, final_trace_csv: Path | None = None) -> dict[str, Any]:
    overall = _empty_group()
    groups: dict[str, defaultdict[str, dict[str, int]]] = {
        "by_qp": defaultdict(_empty_group),
        "by_size": defaultdict(_empty_group),
        "by_lat_bin": defaultdict(_empty_group),
        "early_zero_by_support_ratio_bin": defaultdict(_empty_group),
    }

    for row in _read_rows(stage1_csv):
        before = int(row["candidateBefore"])
        after = int(row["candidateAfter"])
        if before <= 0:
            continue
        early_zero = int(row["earlyZero"]) != 0
        targets = [
            overall,
            groups["by_qp"][row["QP"]],
            groups["by_size"][f'{row["w"]}x{row["h"]}'],
            groups["by_lat_bin"][row["latBin"]],
            groups["early_zero_by_support_ratio_bin"][_support_bin(int(row["supportRatioQ"]))],
        ]
        for target in targets:
            target["eligible_count"] += 1
            target["early_zero_count"] += 1 if early_zero else 0
            target["candidate_before"] += before
            target["candidate_after"] += after

    result = {
        "eligible_count": overall["eligible_count"],
        "early_zero_count": overall["early_zero_count"],
        "early_zero_ratio": _finalize_group(overall)["early_zero_ratio"],
        "candidate_before_total": overall["candidate_before"],
        "candidate_after_total": overall["candidate_after"],
        "nonzero_candidate_reduction": _finalize_group(overall)["candidate_reduction"],
        "by_qp": {key: _finalize_group(value) for key, value in sorted(groups["by_qp"].items())},
        "by_size": {key: _finalize_group(value) for key, value in sorted(groups["by_size"].items())},
        "by_lat_bin": {key: _finalize_group(value) for key, value in sorted(groups["by_lat_bin"].items())},
        "early_zero_by_support_ratio_bin": {
            name: _finalize_group(groups["early_zero_by_support_ratio_bin"][name])
            for name, _, _ in SUPPORT_BINS
        },
        "final_lfnst_idx_distribution": _count_final_lfnst(final_trace_csv),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-csv", type=Path, required=True)
    parser.add_argument("--final-trace-csv", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    result = summarize_stage1_stats(args.stage1_csv, args.final_trace_csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run aggregation tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage1_stats -v
```

Expected: PASS.

- [ ] **Step 5: Commit aggregation module**

Run:

```powershell
git add tools/lard_lfnst/summarize_skip21_stage1_stats.py tools/lard_lfnst/test_skip21_stage1_stats.py
git -c gc.auto=0 commit -m "feat: summarize skip21 stage1 diagnostics"
```

---

### Task 4: Add Validation Orchestrator With Timing/Diagnostic Separation

**Files:**
- Create: `tools/lard_lfnst/run_skip21_stage1_validation.py`
- Modify: `tools/lard_lfnst/test_skip21_stage1_stats.py`

- [ ] **Step 1: Add failing orchestrator tests**

Append to `tools/lard_lfnst/test_skip21_stage1_stats.py`:

```python
from tools.lard_lfnst.run_skip21_stage1_validation import (
    e10_needs_8f_fallback,
    skip21_additional,
)
```

Add these methods to `Skip21Stage1StatsTests`:

```python
    def test_skip21_additional_does_not_include_diagnostic_file_by_default(self) -> None:
        self.assertEqual(
            skip21_additional(0),
            "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile=0",
        )
        self.assertIn("LardLfnst21Profile=2", skip21_additional(2))
        self.assertNotIn("LardLfnst21StatFile", skip21_additional(2))

    def test_e10_fallback_rule(self) -> None:
        self.assertFalse(e10_needs_8f_fallback(mean_ts=9.0, median_ts=10.0, positive_repeats=7))
        self.assertTrue(e10_needs_8f_fallback(mean_ts=5.0, median_ts=10.0, positive_repeats=7))
        self.assertTrue(e10_needs_8f_fallback(mean_ts=9.0, median_ts=10.0, positive_repeats=6))
```

- [ ] **Step 2: Run orchestrator tests to verify they fail**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage1_stats -v
```

Expected: FAIL because `run_skip21_stage1_validation.py` does not exist.

- [ ] **Step 3: Implement the orchestrator helpers**

Create `tools/lard_lfnst/run_skip21_stage1_validation.py` with helper functions first:

```python
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from tools.lard_lfnst.summarize_skip21_stage1_stats import summarize_stage1_stats


def skip21_additional(profile: int) -> str:
    return f"LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile={profile}"


def e10_needs_8f_fallback(mean_ts: float, median_ts: float, positive_repeats: int) -> bool:
    return abs(mean_ts - median_ts) > 3.0 or positive_repeats < 7


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Add timing command construction**

Add this function:

```python
def timing_command(
    encoder: Path,
    orig: Path,
    sphere_file: Path,
    out_root: Path,
    profile: int,
    frames: int,
    repeats: int,
    qps: str,
    threads: int,
    preset: str,
) -> list[str]:
    return [
        "python",
        "-m",
        "tools.lard_lfnst.run_skip18_paired_repeats",
        "--encoder",
        str(encoder),
        "--orig",
        str(orig),
        "--sphere-file",
        str(sphere_file),
        "--out-root",
        str(out_root),
        "--qps",
        qps,
        "--repeats",
        str(repeats),
        "--frames",
        str(frames),
        "--threads",
        str(threads),
        "--preset",
        preset,
        "--anchor-additional",
        "LFNST=1 LardLfnstSkip=0",
        "--proposed-additional",
        skip21_additional(profile),
    ]
```

This command intentionally does not include `LardLfnst21StatFile`.

- [ ] **Step 5: Add diagnostic command construction**

Add this function:

```python
def diagnostic_command(
    encoder: Path,
    orig: Path,
    out_dir: Path,
    profile: int,
    qp: int,
    frames: int,
    threads: int,
    preset: str,
) -> tuple[list[str], Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bitstream = out_dir / f"diag_qp{qp}.vvc"
    rec = out_dir / f"diag_qp{qp}_rec.yuv"
    stage1_csv = out_dir / f"diag_qp{qp}_stage1.csv"
    trace_base = out_dir / f"diag_qp{qp}_final"
    additional = (
        f"{skip21_additional(profile)} "
        f"LardLfnst21StatFile={stage1_csv} "
        f"LardLfnstTraceFile={trace_base}"
    )
    cmd = [
        str(encoder),
        "--preset",
        preset,
        "-i",
        str(orig),
        "-s",
        "3840x1920",
        "-r",
        "30",
        "--InputChromaFormat",
        "420",
        "-q",
        str(qp),
        "--qpa",
        "0",
        "-f",
        str(frames),
        "-ip",
        "1",
        "--mtprofile",
        "0",
        "--threads",
        str(threads),
        "--additional",
        additional,
        "-b",
        str(bitstream),
        "-o",
        str(rec),
    ]
    return cmd, stage1_csv, Path(str(trace_base) + ".final.csv")
```

- [ ] **Step 6: Add CSV merge helpers**

Add:

```python
def _concat_csvs(inputs: list[Path], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    wrote_header = False
    with output.open("w", encoding="utf-8", newline="") as dst:
        for path in inputs:
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            if not wrote_header:
                dst.write(lines[0] + "\n")
                wrote_header = True
            for line in lines[1:]:
                dst.write(line + "\n")
    return output


def _summarize_diagnostics(stage1_paths: list[Path], final_paths: list[Path], out_dir: Path) -> dict[str, Any]:
    merged_stage1 = _concat_csvs(stage1_paths, out_dir / "stage1_all.csv")
    merged_final = _concat_csvs([path for path in final_paths if path.exists()], out_dir / "final_all.csv")
    summary = summarize_stage1_stats(merged_stage1, merged_final if merged_final.exists() else None)
    (out_dir / "diagnostic_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
```

- [ ] **Step 7: Add CLI main**

Add a `main()` that:

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--orig", type=Path, required=True)
    parser.add_argument("--sphere-file", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--run-diagnostics", action="store_true")
    args = parser.parse_args()

    args.out_root.mkdir(parents=True, exist_ok=True)
    jobs = {
        "E5_8f5": {"profile": 0, "frames": 8, "repeats": 5},
        "E10_4f10": {"profile": 2, "frames": 4, "repeats": 10},
    }
    timing_result: dict[str, Any] = {}
    for name, job in jobs.items():
        out = args.out_root / name / "timing"
        _run(
            timing_command(
                args.encoder,
                args.orig,
                args.sphere_file,
                out,
                job["profile"],
                job["frames"],
                job["repeats"],
                args.qps,
                args.threads,
                args.preset,
            ),
            Path.cwd(),
        )
        timing_result[name] = _load_json(out / "summary.json")

    e10 = timing_result["E10_4f10"]["paired_timing"]["overall"]
    if e10_needs_8f_fallback(e10["mean_TS_pct"], e10["median_TS_pct"], e10["positive_repeats"]):
        out = args.out_root / "E10_8f5" / "timing"
        _run(
            timing_command(
                args.encoder,
                args.orig,
                args.sphere_file,
                out,
                2,
                8,
                5,
                args.qps,
                args.threads,
                args.preset,
            ),
            Path.cwd(),
        )
        timing_result["E10_8f5"] = _load_json(out / "summary.json")

    diagnostic_stats: dict[str, Any] = {}
    if args.run_diagnostics:
        for label, profile in {"E5": 0, "E10": 2}.items():
            diag_dir = args.out_root / label / "diagnostic"
            stage1_paths: list[Path] = []
            final_paths: list[Path] = []
            for qp in [int(value) for value in args.qps.split(",") if value]:
                cmd, stage1_csv, final_csv = diagnostic_command(
                    args.encoder,
                    args.orig,
                    diag_dir,
                    profile,
                    qp,
                    4,
                    args.threads,
                    args.preset,
                )
                _run(cmd, Path.cwd())
                stage1_paths.append(stage1_csv)
                final_paths.append(final_csv)
            diagnostic_stats[label] = _summarize_diagnostics(stage1_paths, final_paths, diag_dir)

    report = {"timing_result": timing_result, "diagnostic_stats": diagnostic_stats}
    (args.out_root / "validation_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run orchestrator tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_skip21_stage1_stats -v
```

Expected: PASS.

- [ ] **Step 9: Commit orchestrator**

Run:

```powershell
git add tools/lard_lfnst/run_skip21_stage1_validation.py tools/lard_lfnst/test_skip21_stage1_stats.py
git -c gc.auto=0 commit -m "feat: orchestrate skip21 stage1 validation"
```

---

### Task 5: Execute Validation Runs

**Files:**
- Read: `tools/lard_lfnst/run_skip21_stage1_validation.py`
- Outputs: `tools/lard_lfnst/skip21_stage1_validation_20260616/`

- [ ] **Step 1: Resolve encoder and input paths**

Run:

```powershell
$encoder = Get-ChildItem -Path build-lahtp -Recurse -Filter vvencapp.exe | Select-Object -First 1 -ExpandProperty FullName
$orig = Get-ChildItem -Path I:\Sequences360 -Recurse -Filter 'AerialCity*.yuv' | Select-Object -First 1 -ExpandProperty FullName
$sphere = Get-ChildItem -Path I:\vvenc-LFNST -Recurse -Filter 'sphere_655362.txt' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $sphere) { $sphere = Get-ChildItem -Path I:\ -Recurse -Filter 'sphere_655362.txt' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName }
"encoder=$encoder"
"orig=$orig"
"sphere=$sphere"
```

Expected: each command prints one path. If the sphere file search is slow, reuse the path already used by previous `skip21_stage1_20260616` runs.

- [ ] **Step 2: Run E5/E10 formal timing without diagnostics**

Run with the resolved paths:

```powershell
python -m tools.lard_lfnst.run_skip21_stage1_validation `
  --encoder $encoder `
  --orig $orig `
  --sphere-file $sphere `
  --out-root tools/lard_lfnst/skip21_stage1_validation_20260616 `
  --qps 22,27,32,37 `
  --threads 20 `
  --preset medium
```

Expected:

- `E5_8f5/timing/summary.json` exists.
- `E10_4f10/timing/summary.json` exists.
- `E10_8f5/timing/summary.json` exists only if the fallback rule triggers.
- No `LardLfnst21StatFile` appears in formal timing command strings or timing summaries.

- [ ] **Step 3: Check rec-YUV cleanup**

Run:

```powershell
Get-ChildItem -Recurse -File tools/lard_lfnst/skip21_stage1_validation_20260616 -Include *.yuv | Measure-Object | Select-Object -ExpandProperty Count
```

Expected: `0`.

- [ ] **Step 4: Run diagnostic-only pass**

Run:

```powershell
python -m tools.lard_lfnst.run_skip21_stage1_validation `
  --encoder $encoder `
  --orig $orig `
  --sphere-file $sphere `
  --out-root tools/lard_lfnst/skip21_stage1_validation_diag_20260616 `
  --qps 22,27,32,37 `
  --threads 20 `
  --preset medium `
  --run-diagnostics
```

Expected: diagnostic Stage-1 CSVs exist under `E5/diagnostic` and `E10/diagnostic`. These diagnostic run times are not reported as final TS.

- [ ] **Step 5: Summarize acceptance**

Run a small Python check:

```powershell
@'
import json
from pathlib import Path
root = Path("tools/lard_lfnst/skip21_stage1_validation_20260616")
for name in ["E5_8f5", "E10_4f10", "E10_8f5"]:
    p = root / name / "timing" / "summary.json"
    if not p.exists():
        continue
    s = json.loads(p.read_text())
    t = s["paired_timing"]["overall"]
    m = s["metrics"]
    max_y = max(m[k] for k in ["ORD_Y_BDBR_pct", "WS_Y_BDBR_pct", "S_Y_BDBR_pct", "CPP_Y_BDBR_pct"])
    print(name, "median", t["median_TS_pct"], "mean", t["mean_TS_pct"], "pos", f'{t["positive_repeats"]}/{t["repeats"]}', "maxY", max_y, "TS/maxY", t["median_TS_pct"] / max_y if max_y else None)
'@ | python -
```

Expected: print one line per completed formal timing run.

- [ ] **Step 6: Commit tooling and report artifacts**

Do not commit large bitstreams or raw diagnostic CSVs unless the user explicitly asks. Commit code and compact summaries only:

```powershell
git add tools/lard_lfnst/*.py tools/lard_lfnst/skip21_stage1_validation_20260616/*/timing/summary.json tools/lard_lfnst/skip21_stage1_validation_20260616/validation_summary.json
git -c gc.auto=0 commit -m "test: validate skip21 stage1 profiles"
```

---

## Self-Review Checklist

- Spec coverage: timing and diagnostics are separated; E5 8f×5 and E10 4f×10 are formal timing runs; E10 fallback rule is explicit; diagnostics include QP, size, latitude, support-ratio bins, candidate reduction, and final LFNST aggregate distribution.
- Placeholder scan: the plan avoids open-ended implementation placeholders. Machine-specific encoder, sequence, and sphere paths are resolved into PowerShell variables before the run commands.
- Type consistency: Python functions use `Path`, `dict[str, Any]`, and the CSV column names from the C++ diagnostic header. C++ config name is consistently `m_LardLfnst21StatFile`.
