# LFNST Pre-J0 Shadow and Fitting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a strictly pre-J0, bitstream-neutral LFNST probe, collect deployable features with full-RDO labels, and fit/audit `B_pre0` on held-out data.

**Architecture:** A read-only `TrQuant` probe computes forced-DCT2 primary coefficients and both integer LFNST responses before the candidate loop. `IntraSearch` freezes residual, pseudo-quant, theory, and context features before `J0`, then appends candidate labels and arithmetic-parity results after full RDO. A dedicated Python module enforces a pre0 feature allowlist, fits Ridge/weighted-Ridge/Huber models with hierarchical bias, calibrates TU-level one-sided margins, and writes boundary-risk reports.

**Tech Stack:** C++17/VVenC, Python 3, NumPy, pandas, scikit-learn when available, `unittest`, CMake, remote Linux encoding runner.

---

## Scope boundary

This plan implements design phases 1--3: shadow probe, offline fitting, and remote collection. It intentionally stops before real `{0,1,2}->{0}` pruning. Real Safe/Main/Aggressive integration depends on the selected fitted model and generated tables, so it receives a separate implementation plan after this plan produces reviewed metrics and artifacts.

## File map

- `include/vvenc/vvencCfg.h`: public shadow-mode and log-path configuration fields.
- `source/Lib/vvenc/vvencCfg.cpp`: defaults and validation.
- `source/Lib/apputils/VVEncAppCfg.h`: CLI bindings.
- `source/Lib/CommonLib/TrQuant.h`: read-only pre0 probe result and API.
- `source/Lib/CommonLib/TrQuant.cpp`: forced-DCT2 primary transform, integer LFNST response, and probe identity.
- `source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc`: generated compact theory feature table.
- `source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc`: generated compact theory feature table.
- `source/Lib/EncoderLib/IntraSearch.h`: frozen pre0 sample/feature structures and logging methods.
- `source/Lib/EncoderLib/IntraSearch.cpp`: pre-loop feature capture, post-loop label/parity append, and timing counters.
- `tools/lard_lfnst/test_pre0_encoder_static.py`: source-order, config, schema, and leakage tests.
- `tools/lard_lfnst/generate_lfnst_pre0_theory_table.py`: deterministic theory table generator.
- `tools/lard_lfnst/test_generate_lfnst_pre0_theory_table.py`: theory table tests.
- `tools/lard_lfnst/generate_lfnst_pre0_theory_table.py`: deterministic theory table generator.
- `tools/lard_lfnst/test_generate_lfnst_pre0_theory_table.py`: theory table tests.
- `tools/lard_lfnst/fit_lfnst_pre0_rd_proxy.py`: strict loader, candidate frame, models, calibration, and reports.
- `tools/lard_lfnst/test_fit_lfnst_pre0_rd_proxy.py`: Python unit tests.
- `tools/lard_server_run_lfnst_pre0.py`: remote upload, build, smoke, collection, fitting, and fetch orchestration.
- `tools/lard_lfnst/test_lard_server_run_lfnst_pre0.py`: dry-run command construction tests.

### Task 1: Add an isolated shadow configuration surface

**Files:**
- Modify: `include/vvenc/vvencCfg.h`
- Modify: `source/Lib/vvenc/vvencCfg.cpp`
- Modify: `source/Lib/apputils/VVEncAppCfg.h`
- Create: `tools/lard_lfnst/test_pre0_encoder_static.py`

- [ ] **Step 1: Write failing config and timing-boundary tests**

Create `tools/lard_lfnst/test_pre0_encoder_static.py` with these tests:

```python
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="ignore")


class Pre0EncoderStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg_h = text("include/vvenc/vvencCfg.h")
        cls.cfg_cpp = text("source/Lib/vvenc/vvencCfg.cpp")
        cls.app_h = text("source/Lib/apputils/VVEncAppCfg.h")
        cls.tr_h = text("source/Lib/CommonLib/TrQuant.h")
        cls.intra_h = text("source/Lib/EncoderLib/IntraSearch.h")
        cls.intra_cpp = text("source/Lib/EncoderLib/IntraSearch.cpp")

    def test_pre0_shadow_options_are_initialized_and_cli_bound(self) -> None:
        for name in ("m_LardLfnstPre0Mode", "m_LardLfnstPre0Log", "m_LardLfnstPre0MaxRows"):
            self.assertIn(name, self.cfg_h)
            self.assertIn(name, self.cfg_cpp)
        self.assertIn("LardLfnstPre0Mode", self.app_h)
        self.assertIn("LardLfnstPre0Log", self.app_h)
        self.assertIn("LardLfnstPre0MaxRows", self.app_h)

    def test_pre0_capture_precedes_candidate_loop(self) -> None:
        start = self.intra_cpp.index("void IntraSearch::xIntraCodingLumaQT")
        capture = self.intra_cpp.index("xLardLfnstPre0Capture(", start)
        loop = self.intra_cpp.index(
            "for (int lfnstIdx = startLfnstIdx; lfnstIdx <= endLfnstIdx; lfnstIdx++)",
            start,
        )
        self.assertLess(capture, loop)

    def test_pre0_feature_struct_has_no_post_rdo_fields(self) -> None:
        match = re.search(r"struct LardLfnstPre0Features\s*\{(.*?)\n\s*\};", self.intra_h, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(1)
        for forbidden in ("J0", "J1", "J2", "actualDist", "actualFracBits", "actualOutput"):
            self.assertNotIn(forbidden, body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_pre0_encoder_static -v
```

Expected: config-name assertions fail because the pre0 fields do not exist.

- [ ] **Step 3: Add config fields and CLI options**

Add to `VVEncCfg`:

```cpp
int  m_LardLfnstPre0Mode;                         // 0 off, 1 shadow collection
char m_LardLfnstPre0Log[VVENC_MAX_STRING_LEN];   // frozen pre0 features plus post-loop labels
int  m_LardLfnstPre0MaxRows;                     // 0 unlimited
```

Initialize in `vvenc_config_default`:

```cpp
c->m_LardLfnstPre0Mode = 0;
memset(c->m_LardLfnstPre0Log, '\0', sizeof(c->m_LardLfnstPre0Log));
c->m_LardLfnstPre0MaxRows = 0;
```

Validate:

```cpp
vvenc_checkCharArrayStr(c->m_LardLfnstPre0Log, VVENC_MAX_STRING_LEN);
vvenc_confirmParameter(c, c->m_LardLfnstPre0Mode < 0 || c->m_LardLfnstPre0Mode > 1,
                       "LardLfnstPre0Mode out of range [0..1]");
vvenc_confirmParameter(c, c->m_LardLfnstPre0MaxRows < 0,
                       "LardLfnstPre0MaxRows must be non-negative");
```

Bind long and lowercase aliases in `VVEncAppCfg.h` using `IStreamToArr<char>` for the path, matching the existing covariance-log pattern.

- [ ] **Step 4: Re-run the focused test**

Run the same unittest. Expected: config test passes; capture/struct tests still fail because Tasks 2--4 have not implemented them.

- [ ] **Step 5: Commit Task 1**

```powershell
git add include/vvenc/vvencCfg.h source/Lib/vvenc/vvencCfg.cpp source/Lib/apputils/VVEncAppCfg.h tools/lard_lfnst/test_pre0_encoder_static.py
git commit -m "feat: add LFNST pre0 shadow configuration"
```

### Task 2: Implement the read-only matrix-exact pre0 transform probe

**Files:**
- Modify: `source/Lib/CommonLib/TrQuant.h`
- Modify: `source/Lib/CommonLib/TrQuant.cpp`
- Modify: `tools/lard_lfnst/test_pre0_encoder_static.py`

- [ ] **Step 1: Add failing API and arithmetic-source tests**

Add tests that require:

```python
def test_trquant_exposes_read_only_pre0_probe(self) -> None:
    self.assertIn("struct LardLfnstPre0Probe", self.tr_h)
    self.assertIn("buildLardLfnstPre0Probe", self.tr_h)
    self.assertIn("const CPelBuf& residual", self.tr_h)

def test_probe_uses_forced_dct2_and_integer_lfnst_matrices(self) -> None:
    tr_cpp = text("source/Lib/CommonLib/TrQuant.cpp")
    start = tr_cpp.index("bool TrQuant::buildLardLfnstPre0Probe")
    body = tr_cpp[start:start + 12000]
    self.assertIn("DCT2", body)
    self.assertIn("g_lfnstFwd4x4", body)
    self.assertIn("g_lfnstFwd8x8", body)
    self.assertNotIn("transformNxN(", body)
    self.assertNotIn("xQuant(", body)
```

- [ ] **Step 2: Verify RED**

Run the focused static test. Expected: missing struct/API assertions fail.

- [ ] **Step 3: Define the probe result and API**

Under `VVENC_LARD_LFNST_2ND_RESP_ENABLE`, add:

```cpp
struct LardLfnstPre0Probe
{
  bool valid = false;
  int width = 0;
  int height = 0;
  int inputSize = 0;
  int outputSize = 0;
  int lfnstSet = -1;
  bool transpose = false;
  int scanOrderId = 0;
  uint64_t coordHash = 0;
  TCoeff input[48] = {};
  TCoeff response[2][16] = {};
};

bool buildLardLfnstPre0Probe(const TransformUnit& tu, const CPelBuf& residual,
                             int lfnstSet, bool transpose,
                             LardLfnstPre0Probe& out);
```

- [ ] **Step 4: Implement a forced-DCT2 primary transform without mutating TU state**

Factor the DCT2 portion of `xT` into a private helper that takes explicit transform types and explicit zero-out dimensions. Use local `std::vector<TCoeff>` scratch arrays sized `width*height`; do not write `m_plTempCoeff`, `m_tempInMatrix`, TU coefficients, or `cu.lfnstIdx`.

For non-zero LFNST semantics set:

```cpp
const int skipWidth = (width == 4 && height > 4) ? width - 4
                    : (width >= 8 && height >= 8) ? width - 8
                    : std::max(0, width - JVET_C0024_ZERO_OUT_TH);
const int skipHeight = (height == 4 && width > 4) ? height - 4
                     : (width >= 8 && height >= 8) ? height - 8
                     : std::max(0, height - JVET_C0024_ZERO_OUT_TH);
```

Collect the 16/48 LFNST input with the same coordinate order as `xLard2ndCollectLfnstInput`, then apply the ROM matrix with the encoder rounding rule:

```cpp
const int64_t value = (sum + 64) >> 7;
```

Set `outputSize=8` for 4x4/8x8 and `16` otherwise. Compute scan identity and FNV-1a coordinate hash using the same versioned definition as Experiment 4.2.

- [ ] **Step 5: Run static tests and compile CommonLib**

```powershell
python -m unittest tools.lard_lfnst.test_pre0_encoder_static -v
cmake --build build --config Release --target CommonLib
```

Expected: probe tests pass and CommonLib builds without warnings promoted to errors.

- [ ] **Step 6: Commit Task 2**

```powershell
git add source/Lib/CommonLib/TrQuant.h source/Lib/CommonLib/TrQuant.cpp tools/lard_lfnst/test_pre0_encoder_static.py
git commit -m "feat: add read-only LFNST pre0 transform probe"
```

### Task 3: Generate a compact deployable theory feature table

**Files:**
- Create: `tools/lard_lfnst/generate_lfnst_pre0_theory_table.py`
- Create: `tools/lard_lfnst/test_generate_lfnst_pre0_theory_table.py`
- Create: `source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc`
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`

- [ ] **Step 1: Write failing deterministic table and lookup-key tests**

Create tests that import the existing Experiment 4.2 covariance/response functions and assert that generated rows cover every supported `(latBin,W,H,setIdx,transpose)` key; contain finite `O_x`, `chi_diag`, `G1`, `G2`, `U1`, `U2`, `deltaG1`, and `deltaG2`; are invariant to overall covariance scale; serialize in stable sorted order; and do not use exact QP in the lookup key. Compare two generated byte strings for equality.

```python
from __future__ import annotations

import math
import unittest

from tools.lard_lfnst import generate_lfnst_pre0_theory_table as gen


class Pre0TheoryTableTests(unittest.TestCase):
    def test_rows_are_complete_finite_and_qp_independent(self) -> None:
        rows = gen.build_rows()
        keys = {(r.lat_bin, r.width, r.height, r.set_idx, r.transpose) for r in rows}
        self.assertEqual(keys, set(gen.expected_keys()))
        for row in rows:
            self.assertTrue(all(math.isfinite(v) for v in row[5:]))
            self.assertFalse(hasattr(row, "qp"))

    def test_rendering_is_deterministic(self) -> None:
        self.assertEqual(gen.render_inc(gen.build_rows()), gen.render_inc(gen.build_rows()))

    def test_structure_features_ignore_covariance_scale(self) -> None:
        base = gen.compute_key(1, 8, 8, 0, 0, covariance_scale=1.0)
        scaled = gen.compute_key(1, 8, 8, 0, 0, covariance_scale=17.0)
        for left, right in zip(base[5:], scaled[5:]):
            self.assertAlmostEqual(left, right, places=10)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_generate_lfnst_pre0_theory_table -v
```

Expected: import fails because the generator does not exist.

- [ ] **Step 3: Implement the generator from the formal covariance path**

Import the existing theory covariance, mask, LFNST matrix, and response-metric helpers rather than duplicating formulas. Normalize theoretical covariance to correlation form before calculating structure features. Enumerate the formal supported shapes and latitude-bin centers, then emit:

```python
TheoryRow = NamedTuple("TheoryRow", [
    ("lat_bin", int), ("width", int), ("height", int),
    ("set_idx", int), ("transpose", int),
    ("o_x", float), ("chi_diag", float),
    ("g1", float), ("g2", float), ("u1", float), ("u2", float),
    ("delta_g1", float), ("delta_g2", float),
])
```

The command below must be deterministic and include a generated-file header with the script path and schema version:

```powershell
python -m tools.lard_lfnst.generate_lfnst_pre0_theory_table --output source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc
```

- [ ] **Step 4: Add the C++ table type and exact-key lookup**

In `IntraSearch.cpp`, define:

```cpp
struct LardLfnstPre0TheoryEntry
{
  int latBin, width, height, setIdx, transpose;
  double ox, chiDiag, g[2], u[2], deltaG[2];
};

static const LardLfnstPre0TheoryEntry g_lardLfnstPre0TheoryTable[] =
{
#include "LardLfnstPre0TheoryTable.inc"
};
```

Implement an exact-key binary search over the generator's sorted order. Return `nullptr` for missing keys; never select a nearest geometry or latitude bin.

- [ ] **Step 5: Run tests and verify deterministic regeneration**

```powershell
python -m unittest tools.lard_lfnst.test_generate_lfnst_pre0_theory_table -v
python -m tools.lard_lfnst.generate_lfnst_pre0_theory_table --output source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc
git diff --exit-code -- source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc
```

Expected: tests pass and the second generation produces no diff.

- [ ] **Step 6: Commit Task 3**

```powershell
git add tools/lard_lfnst/generate_lfnst_pre0_theory_table.py tools/lard_lfnst/test_generate_lfnst_pre0_theory_table.py source/Lib/EncoderLib/LardLfnstPre0TheoryTable.inc source/Lib/EncoderLib/IntraSearch.cpp
git commit -m "feat: generate LFNST pre0 theory features"
```

### Task 4: Freeze pre0 features before the candidate loop and append labels after it

**Files:**
- Modify: `source/Lib/EncoderLib/IntraSearch.h`
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp`
- Modify: `tools/lard_lfnst/test_pre0_encoder_static.py`

- [ ] **Step 1: Add failing schema, source-order, and parity tests**

Extend the static test with assertions for:

```python
def test_pre0_log_declares_timing_and_parity_columns(self) -> None:
    for col in (
        "featureTiming", "probeValid", "probeInputMatch1", "probeInputMatch2",
        "probeResponseMatch1", "probeResponseMatch2", "J0", "J1", "J2",
        "rdoValid0", "rdoValid1", "rdoValid2",
    ):
        self.assertIn(col, self.intra_cpp)

def test_labels_are_only_passed_to_post_loop_append(self) -> None:
    capture = self.intra_cpp.index("xLardLfnstPre0Capture(")
    loop = self.intra_cpp.index("for (int lfnstIdx = startLfnstIdx", capture)
    append = self.intra_cpp.index("xLardLfnstPre0AppendLog(", loop)
    self.assertLess(capture, loop)
    self.assertLess(loop, append)
```

- [ ] **Step 2: Verify RED**

Run the static test. Expected: missing pre0 feature/log methods fail.

- [ ] **Step 3: Add frozen feature and label structures**

Define `LardLfnstPre0Features` with only deployable fields:

```cpp
struct LardLfnstPre0Features
{
  bool eligible = false;
  bool probeValid = false;
  uint64_t sampleId = 0;
  int poc = -1, x = 0, y = 0, width = 0, height = 0, qp = 0;
  int modeGroup = -1, latBin = -1, setIdx = -1, candidateCount = 2;
  bool transpose = false;
  int inputSize = 0, outputSize = 0, scanOrderId = 0;
  uint64_t coordHash = 0;
  double absLatDeg = 0.0, lambda = 0.0, qStep = 0.0;
  double sigma2Res = 0.0, rhoH = 0.0, rhoV = 0.0;
  double inputEnergy = 0.0;
  double baseNnz = 0.0, baseLast = -1.0, baseLogLevel = 0.0;
  double deltaDhat[2] = {};
  double deltaNnz[2] = {}, deltaLast[2] = {}, deltaNcg[2] = {};
  double deltaLogLevel[2] = {}, deltaNgt1[2] = {}, deltaNgt2[2] = {};
  double theoryOx = 0.0, theoryChiDiag = 0.0;
  double theoryG[2] = {}, theoryU[2] = {}, theoryDeltaG[2] = {};
  LardLfnstPre0Probe probe;
};
```

Keep full-RDO costs, validity, and actual candidate arrays in a separate local `LardLfnstPre0Labels` object created after the loop.

- [ ] **Step 4: Implement capture using only pre-loop inputs**

`xLardLfnstPre0Capture` must:

1. check mode 1, log path, `predBuf`, standard luma eligibility, and `endLfnstIdx==2`;
2. construct a local residual from reshaped org when LMCS is active, otherwise ordinary org, minus `predBuf->Y()`;
3. compute centered residual variance/correlations;
4. call `buildLardLfnstPre0Probe`;
5. compute scalar levels with `floor(abs(value)/qStep+0.5)` for baseline and two responses;
6. compute quantization error, nnz, last, coefficient groups, log level, gt1, and gt2 differences;
7. obtain theory values from the existing theory lookup with explicit missing-entry fallback;
8. record separated nanosecond counters for transform/projection, pseudo quant, and theory lookup.

Do not call `transformNxN`, `xIntraCodingTUBlock`, CABAC methods, inverse transform, or distortion functions.

- [ ] **Step 5: Place capture before the loop and append after full RDO**

Immediately before the first luma candidate loop:

```cpp
LardLfnstPre0Features pre0;
if (m_pcEncCfg && m_pcEncCfg->m_LardLfnstPre0Mode == 1)
{
  pre0 = xLardLfnstPre0Capture(cu, tu, predBuf, startLfnstIdx, endLfnstIdx);
}
```

During candidates, copy only the already-produced actual LFNST input/output into a parity accumulator. After the loop, create labels from the stored RDO arrays and append one CSV row per TU. `featureTiming` must be the literal `pre0`.

- [ ] **Step 6: Implement parity and max-row behavior**

Compare dimensions, set, transpose, scan identity, every input element, and every retained response element. Emit separate candidate match flags plus maximum absolute difference. Rows with invalid candidates retain explicit validity flags; they are not converted to zero-gain labels.

Protect file creation and row counting with the existing mutex pattern. Stop after `m_LardLfnstPre0MaxRows` without changing encoding decisions.

- [ ] **Step 7: Run source tests and build EncoderApp**

```powershell
python -m unittest tools.lard_lfnst.test_pre0_encoder_static -v
cmake --build build --config Release --target EncoderApp
```

Expected: all static tests pass; EncoderApp builds.

- [ ] **Step 8: Run baseline-versus-shadow smoke**

Encode the same short input twice, once with mode 0 and once with mode 1 plus a log path. Compare bitstreams with `Get-FileHash` and verify that the shadow log contains only `featureTiming=pre0` and nonzero row count.

- [ ] **Step 9: Commit Task 4**

```powershell
git add source/Lib/EncoderLib/IntraSearch.h source/Lib/EncoderLib/IntraSearch.cpp tools/lard_lfnst/test_pre0_encoder_static.py
git commit -m "feat: collect strict pre0 LFNST shadow features"
```

### Task 5: Build the strict pre0 dataset loader and feature allowlist

**Files:**
- Create: `tools/lard_lfnst/fit_lfnst_pre0_rd_proxy.py`
- Create: `tools/lard_lfnst/test_fit_lfnst_pre0_rd_proxy.py`

- [ ] **Step 1: Write failing loader, leakage, parity, and candidate-frame tests**

Tests must construct a two-candidate TU and assert:

```python
def _tu_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sequence": "SeqA", "POC": 0, "x": 0, "y": 0, "W": 8, "H": 8,
        "QP": 24, "modeGroup": 2, "latBin": 1, "setIdx": 1, "transpose": 0,
        "featureTiming": "pre0", "probeValid": 1,
        "probeInputMatch1": 1, "probeInputMatch2": 1,
        "probeResponseMatch1": 1, "probeResponseMatch2": 1,
        "rdoValid0": 1, "rdoValid1": 1, "rdoValid2": 1,
        "J0": 100.0, "J1": 95.0, "J2": 104.0,
    }
    for name in proxy.PRE0_TU_COLUMNS:
        row.setdefault(name, 0.0)
    row.update(overrides)
    return row

def test_loader_rejects_non_pre0_timing(self) -> None:
    with self.assertRaisesRegex(ValueError, "featureTiming"):
        proxy.filter_deployable_tus(pd.DataFrame([_tu_row(featureTiming="post0")]))

def test_feature_allowlist_excludes_post_rdo_columns(self) -> None:
    proxy.assert_deployable_features(proxy.PRE0_FEATURES)
    with self.assertRaisesRegex(ValueError, "post-RDO"):
        proxy.assert_deployable_features([*proxy.PRE0_FEATURES, "actualFracBits1"])

def test_rows_with_failed_probe_parity_are_excluded(self) -> None:
    frame = pd.DataFrame([_tu_row(x=0), _tu_row(x=8, probeResponseMatch2=0)])
    filtered = proxy.filter_deployable_tus(frame)
    self.assertEqual(filtered["x"].tolist(), [0])

def test_candidate_frame_uses_j_only_as_label(self) -> None:
    samples = proxy.build_candidate_frame(pd.DataFrame([_tu_row()]))
    self.assertEqual(samples["candidate"].tolist(), [1, 2])
    self.assertEqual(samples["deltaJ_true"].tolist(), [5.0, -4.0])
    self.assertTrue({"J0", "J1", "J2"}.isdisjoint(proxy.PRE0_FEATURES))
```

The expected feature constants are:

```python
PRE0_FEATURES = [
    "deltaDhat", "lamDeltaNnz", "lamDeltaLast", "lamDeltaNcg",
    "lamDeltaLogLevel", "lamDeltaNgt1", "lamDeltaNgt2",
    "sigma2Res", "rhoH", "rhoV", "rhoDiff", "inputEnergy",
    "baseNnz", "baseLast", "baseLogLevel", "theoryOx", "theoryChiDiag",
    "theoryG", "theoryU", "theoryDeltaG", "QP", "log2W", "log2H",
    "modeGroup", "setIdx", "transpose", "latBin", "candidate",
]
CANDIDATE_STEMS = [
    "deltaDhat", "lamDeltaNnz", "lamDeltaLast", "lamDeltaNcg",
    "lamDeltaLogLevel", "lamDeltaNgt1", "lamDeltaNgt2",
    "theoryG", "theoryU", "theoryDeltaG",
]
PRE0_COMMON_COLUMNS = [
    "sigma2Res", "rhoH", "rhoV", "rhoDiff", "inputEnergy",
    "baseNnz", "baseLast", "baseLogLevel", "theoryOx", "theoryChiDiag",
    "QP", "W", "H", "modeGroup", "setIdx", "transpose", "latBin",
]
PRE0_TU_COLUMNS = [
    *PRE0_COMMON_COLUMNS,
    *(f"{stem}{candidate}" for stem in CANDIDATE_STEMS for candidate in (1, 2)),
]
FORBIDDEN_FEATURE_TOKENS = (
    "J0", "J1", "J2", "actual", "distCost", "fracBits", "rateCost", "rdoTime",
)
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_fit_lfnst_pre0_rd_proxy -v
```

Expected: import fails because the fitter does not exist.

- [ ] **Step 3: Implement strict loading and candidate expansion**

Implement:

```python
def assert_deployable_features(names: Sequence[str]) -> None:
    unknown = sorted(set(names) - set(PRE0_FEATURES))
    leaked = [name for name in names if any(token.lower() in name.lower() for token in FORBIDDEN_FEATURE_TOKENS)]
    if unknown or leaked:
        raise ValueError(f"post-RDO or unknown features: unknown={unknown}, leaked={leaked}")

def filter_deployable_tus(frame: pd.DataFrame) -> pd.DataFrame:
    if not frame["featureTiming"].eq("pre0").all():
        raise ValueError("featureTiming must be pre0 for every input row")
    parity = ["probeValid", "probeInputMatch1", "probeInputMatch2",
              "probeResponseMatch1", "probeResponseMatch2"]
    valid = frame[parity].eq(1).all(axis=1)
    valid &= frame[["rdoValid0", "rdoValid1", "rdoValid2"]].eq(1).all(axis=1)
    valid &= np.isfinite(frame[["J0", "J1", "J2"]]).all(axis=1)
    return frame.loc[valid].copy()

def load_pre0_logs(paths: Sequence[Path]) -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in paths]
    if not frames:
        raise ValueError("no pre0 logs matched")
    return filter_deployable_tus(pd.concat(frames, ignore_index=True, sort=False))

def build_candidate_frame(tu: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for candidate in (1, 2):
        cand = tu.copy()
        cand["candidate"] = candidate
        cand["deltaJ_true"] = cand["J0"] - cand[f"J{candidate}"]
        for stem in CANDIDATE_STEMS:
            cand[stem] = cand[f"{stem}{candidate}"]
        rows.append(cand)
    return pd.concat(rows, ignore_index=True, sort=False)
```

Loader requirements:

- `featureTiming == "pre0"`;
- valid finite `J0/J1/J2` and `rdoValid0/1/2`;
- `probeValid==1` and all four parity flags equal 1;
- exact feature allowlist;
- unique TU ID from sequence, QP, POC, position, size, and row ordinal;
- `deltaJ_true=J0-Jl` used only as target.

- [ ] **Step 4: Run tests GREEN**

Run the focused unittest. Expected: loader and candidate-frame tests pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add tools/lard_lfnst/fit_lfnst_pre0_rd_proxy.py tools/lard_lfnst/test_fit_lfnst_pre0_rd_proxy.py
git commit -m "feat: add strict pre0 LFNST dataset loader"
```

### Task 6: Fit transparent models with hierarchical bias and strict calibration

**Files:**
- Modify: `tools/lard_lfnst/fit_lfnst_pre0_rd_proxy.py`
- Modify: `tools/lard_lfnst/test_fit_lfnst_pre0_rd_proxy.py`

- [ ] **Step 1: Write failing model and split-isolation tests**

Cover:

- Ridge recovers a synthetic linear target;
- weighted Ridge assigns `1/(abs(y)+tau)` with an explicit maximum cap;
- Huber produces finite predictions with outliers;
- exact-QP is absent from the bias key;
- hierarchical bias falls back `full -> no_lat -> no_mode -> global`;
- calibration IDs and test IDs are disjoint;
- margins use `u_b=max_l(true-pred)`;
- 1%, 3%, and 5% profiles are reported without enforcing coverage/QP gates.

Add concrete tests including:

```python
def test_boundary_weights_focus_on_zero_gain_and_are_capped(self) -> None:
    y = np.array([0.0, 1.0, 100.0])
    w = proxy.boundary_weights(y, tau=1.0, max_weight=0.75)
    self.assertGreater(w[0], w[1])
    self.assertGreater(w[1], w[2])
    self.assertLessEqual(float(w.max()), 0.75)

def test_bias_hierarchy_contains_no_exact_qp(self) -> None:
    self.assertTrue(all("QP" not in level for level in proxy.BIAS_LEVELS))

def test_tu_margin_uses_max_candidate_underprediction(self) -> None:
    rows = pd.DataFrame({
        "tu_id": ["a", "a", "b", "b"], "candidate": [1, 2, 1, 2],
        "deltaJ_true": [2.0, 8.0, -3.0, 1.0], "pred_deltaJ": [1.0, 3.0, -2.0, 0.0],
    })
    tu = proxy.to_tu_margin_frame(rows)
    self.assertEqual(dict(zip(tu["tu_id"], tu["under_error"])), {"a": 5.0, "b": 1.0})

def test_three_way_split_has_no_tu_overlap(self) -> None:
    frame = synthetic_candidate_frame(sequences=3, pocs=4)
    fit, calibration, test = proxy.make_outer_split(frame, "leave_one_sequence", "SeqC")
    self.assertTrue(set(fit.tu_id).isdisjoint(calibration.tu_id))
    self.assertTrue(set(fit.tu_id).isdisjoint(test.tu_id))
    self.assertTrue(set(calibration.tu_id).isdisjoint(test.tu_id))
```

- [ ] **Step 2: Verify RED**

Run the focused unittest. Expected: missing model/calibration functions fail.

- [ ] **Step 3: Implement model families**

Implement standardized Ridge using the existing stable solver pattern. Implement weighted Ridge by multiplying design rows and targets by `sqrt(weight)`. Use `sklearn.linear_model.HuberRegressor` when installed; otherwise emit a clear `huber_available=0` row and continue Ridge models rather than aborting the run.

Bias hierarchy:

```python
BIAS_LEVELS = [
    ["W", "H", "modeGroup", "setIdx", "transpose", "latBin", "candidate"],
    ["W", "H", "modeGroup", "setIdx", "transpose", "candidate"],
    ["W", "H", "setIdx", "transpose", "candidate"],
    ["candidate"],
]
```

Record the selected fallback level for every prediction.

- [ ] **Step 4: Implement three-way outer validation**

For each leave-one-sequence and leave-one-QP test split, divide the remaining groups deterministically into fit and calibration partitions by stable hash of sequence/POC. Assert no TU IDs overlap. Add held-out-frame splits where at least three POCs exist.

- [ ] **Step 5: Implement TU-level one-sided margins**

Pivot candidate rows to TU rows, compute `pred_max`, `true_max`, and `u=max(true_l-pred_l)`. Calibrate hierarchical empirical quantiles with finite-sample index:

```python
k = min(n - 1, math.ceil((n + 1) * (1.0 - risk_limit)) - 1)
margin = np.sort(u)[max(0, k)]
```

Apply the same hierarchy as bias, with independent minimum sample counts. Skip when `pred_max + margin <= 0`.

- [ ] **Step 6: Implement metrics and boundary tables**

Write:

- `pre0_split_metrics.csv`;
- `pre0_model_summary.csv`;
- `boundary_error_by_qp.csv`;
- `boundary_error_by_size.csv`;
- `boundary_error_by_latbin.csv`;
- `boundary_error_by_set_transpose.csv`;
- `pre0_feature_timing_manifest.json`;
- serialized model/margin JSON for each family and profile.

Boundary rows include count, mean error, P95, P99, selected count, coverage, false-skip count, risk, and fallback level. Do not filter QP34 or zero-coverage groups.

- [ ] **Step 7: Run tests GREEN and a synthetic CLI smoke**

```powershell
python -m unittest tools.lard_lfnst.test_fit_lfnst_pre0_rd_proxy -v
python -m tools.lard_lfnst.fit_lfnst_pre0_rd_proxy --help
```

Expected: all tests pass and CLI lists `--pre0-log`, `--out-dir`, `--ridge`, `--boundary-tau`, `--min-bias-samples`, and `--min-margin-samples`.

- [ ] **Step 8: Commit Task 6**

```powershell
git add tools/lard_lfnst/fit_lfnst_pre0_rd_proxy.py tools/lard_lfnst/test_fit_lfnst_pre0_rd_proxy.py
git commit -m "feat: fit and audit pre0 LFNST RD proxies"
```

### Task 7: Add remote smoke, collection, fitting, and artifact fetch

**Files:**
- Create: `tools/lard_server_run_lfnst_pre0.py`
- Create: `tools/lard_lfnst/test_lard_server_run_lfnst_pre0.py`

- [ ] **Step 1: Write a failing runner-command test**

Refactor command construction into `build_remote_commands(remote_src: str, remote_run: str, frames: int) -> list[str]` and test that it contains:

- three sequences: AerialCity, DrivingInCity, Harbor;
- QP 19, 24, 29, 34;
- shadow mode and per-run pre0 log path;
- unit tests before build;
- a one-frame smoke before multi-frame collection;
- fitter invocation only after all encoder jobs succeed;
- fetch list for metrics, boundary tables, manifests, and models.

```python
from __future__ import annotations

import unittest

import tools.lard_server_run_lfnst_pre0 as runner


class Pre0RemoteRunnerTests(unittest.TestCase):
    def test_commands_cover_smoke_tests_and_all_collection_jobs(self) -> None:
        commands = runner.build_remote_commands("/remote/src", "/remote/run", 8)
        joined = "\n".join(commands)
        for sequence in ("AerialCity", "DrivingInCity", "Harbor"):
            self.assertIn(sequence, joined)
        for qp in (19, 24, 29, 34):
            self.assertIn(f"QP{qp}", joined)
        self.assertIn("LardLfnstPre0Mode=1", joined)
        self.assertIn("unittest", joined)
        self.assertIn("fit_lfnst_pre0_rd_proxy", joined)
        self.assertLess(joined.index("smoke"), joined.index("--frames 8"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify RED**

Run the runner-command test. Expected: import or missing-function failure.

- [ ] **Step 3: Implement the remote runner**

Follow the existing Paramiko runner pattern. Use environment variables for host/key/password, remote source/run roots, frame count, and local output. Never embed credentials. Use unique output directories and one log per sequence/QP.

Remote phases:

1. upload only changed source, tests, fitter, and runner support files;
2. run Python tests;
3. configure/build Release;
4. run one-frame baseline and shadow smoke and compare bitstream hashes;
5. inspect parity summary and require zero mismatches before full collection;
6. collect multiple frames for all 12 sequence/QP jobs;
7. fit all model families;
8. fetch compact reports and model artifacts.

- [ ] **Step 4: Run runner tests GREEN**

```powershell
python -m unittest tools.lard_lfnst.test_lard_server_run_lfnst_pre0 -v
python tools/lard_server_run_lfnst_pre0.py --dry-run
```

Expected: tests pass; dry-run prints 12 collection jobs and no network connection is made.

- [ ] **Step 5: Commit Task 7**

```powershell
git add tools/lard_server_run_lfnst_pre0.py tools/lard_lfnst/test_lard_server_run_lfnst_pre0.py
git commit -m "feat: orchestrate remote LFNST pre0 study"
```

### Task 8: Execute the shadow study and produce the real-gate handoff

**Files:**
- Create: `lahtp_runs/lfnst_pre0_<date>/` artifacts from the runner
- Modify: `docs/lard_lfnst_covariance_model_validation_4_2.md`

- [ ] **Step 1: Run local verification before upload**

```powershell
python -m unittest tools.lard_lfnst.test_pre0_encoder_static tools.lard_lfnst.test_fit_lfnst_pre0_rd_proxy -v
cmake --build build --config Release --target EncoderApp
```

Expected: all tests pass and EncoderApp builds.

- [ ] **Step 2: Run the remote study**

Execute `tools/lard_server_run_lfnst_pre0.py` with the approved server credentials supplied through environment variables. Preserve console output as `run.log` in the local result directory.

- [ ] **Step 3: Verify collected evidence**

Check:

- baseline/shadow bitstream hashes match in smoke;
- feature timing manifest contains only allowlisted pre0 fields;
- parity mismatch count is zero for accepted rows;
- all 12 sequence/QP jobs have nonzero accepted samples;
- split metrics contain sequence, QP, and frame holdouts;
- Safe/Main/Aggressive rows exist even when coverage is zero;
- QP34 and every observed size appear in boundary outputs.

- [ ] **Step 4: Document results without imposing a go/no-go threshold**

Add a concise Experiment 4.2 subsection containing the model comparison, Main coverage, aggregate/per-QP risk, QP34 behavior, parity rate, probe overhead, and boundary findings. State explicitly that these are monitored values, not current constraints.

- [ ] **Step 5: Run final verification**

```powershell
git diff --check
python -m unittest tools.lard_lfnst.test_pre0_encoder_static tools.lard_lfnst.test_fit_lfnst_pre0_rd_proxy -v
```

Expected: clean diff check and all focused tests pass.

- [ ] **Step 6: Commit the evidence summary**

```powershell
git add docs/lard_lfnst_covariance_model_validation_4_2.md
git commit -m "docs: report LFNST pre0 shadow study"
```

- [ ] **Step 7: Create the next design checkpoint**

Select the model family and model artifact from observed held-out and overhead results. The next design/plan will specify compact table export, Safe/Main/Aggressive runtime selection, actual candidate-loop truncation, TS/BDBR jobs, and transform-cache optimization. Do not add real pruning inside this plan.

## Plan self-review

- Spec coverage: strict timing, isolated forced-DCT2 probe, pseudo quantization, residual/candidate/theory features, parity, leakage prevention, three model families, hierarchical bias/margins, train/calibration/test separation, boundary tables, three monitored profiles, remote collection, and overhead reporting are covered.
- Deferred by dependency: real pruning and transform-cache reuse require the model selected by Task 8 and are intentionally assigned to the follow-up plan.
- Naming consistency: encoder uses `LardLfnstPre0Features`/`LardLfnstPre0Probe`; Python uses `PRE0_FEATURES`; all logs identify `featureTiming=pre0`.
