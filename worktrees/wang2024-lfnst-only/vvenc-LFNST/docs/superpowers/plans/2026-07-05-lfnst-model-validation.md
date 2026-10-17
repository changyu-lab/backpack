# LFNST Residual Model Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Experiments 4.1 and 4.2 as a bitstream-neutral encoder trace plus strict offline validation of spatial residual correlation, raw/effective low-frequency covariance, and theoretical-response association with real LFNST RD gain.

**Architecture:** Extend the existing Skip15 shadow diagnostic path so one TU-level `sampleId` joins the no-LFNST low-frequency vector to `J0/J1/J2` and pre-transform residual statistics. Put parsing, statistical definitions, and integrity checks in a small Python core module; keep orchestration and IEEE TIP figures in a separate CLI while preserving the existing 4.2 entry point as a compatibility wrapper.

**Tech Stack:** C++17/VVenC, Python 3.8+, `unittest`, NumPy, pandas, SciPy, matplotlib, seaborn, CMake.

---

## File Structure

- Modify `source/Lib/EncoderLib/IntraSearch.h`: carry TU-level model-validation metadata through the existing covariance decision object.
- Modify `source/Lib/EncoderLib/IntraSearch.cpp`: compute pre-transform residual statistics, generate `sampleId`, hash the LFNST input coordinate order, and write matching trace schemas.
- Create `tools/lard_lfnst/test_model_validation_encoder_static.py`: source-level regression checks for schema and call placement.
- Modify `tools/lard_lfnst/run_lfnst_motivation_diagnostic.py`: write deterministic run manifests and preserve trace pairs.
- Modify `tools/lard_lfnst/test_run_lfnst_motivation_diagnostic.py`: verify manifests and deterministic smoke commands.
- Create `tools/lard_lfnst/model_validation_stats.py`: strict readers, pairing, spatial statistics, covariance metrics, effective-support operators, permutation tests, and RD-response metrics.
- Create `tools/lard_lfnst/test_model_validation_stats.py`: formula and integrity unit tests.
- Create `tools/lard_lfnst/run_lfnst_model_validation.py`: end-to-end analysis, tables, figures, and report generation.
- Create `tools/lard_lfnst/test_run_lfnst_model_validation.py`: synthetic end-to-end output tests.
- Modify `tools/lard_lfnst/run_lfnst_covariance_model_validation.py`: compatibility exports and legacy CLI forwarding.
- Modify `tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py`: ensure existing 4.2 callers continue to work.
- Modify `docs/lard_lfnst_covariance_model_validation_4_2.md`: document the corrected paired 4.1/4.2 workflow and interpretation limits.

### Task 1: Add TU-Level Paired Encoder Trace Metadata

**Files:**
- Modify: `source/Lib/EncoderLib/IntraSearch.h:278-405`
- Modify: `source/Lib/EncoderLib/IntraSearch.cpp:930-990,3720-3810,4732-4782,5946-6140,8680-9600`
- Create: `tools/lard_lfnst/test_model_validation_encoder_static.py`

- [ ] **Step 1: Write the failing source-level schema test**

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ModelValidationEncoderStaticTests(unittest.TestCase):
    def test_trace_schema_has_paired_identity_and_residual_stats(self):
        text = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(
            encoding="utf-8", errors="ignore"
        )
        for token in (
            "sampleId", "rho_h_block", "rho_v_block", "sigma2_res",
            "rho_h_valid", "rho_v_valid", "inputVectorDim", "scanOrderId",
            "lfnstInputCoordListHash", "lfnstSetIdx",
        ):
            self.assertIn(token, text)
        self.assertLess(
            text.index("xLardModelValidationSample"),
            text.index("xIntraCodingTUBlock(tu, COMP_Y"),
        )

    def test_vec_and_cov_logs_share_sample_id(self):
        text = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(
            encoding="utf-8", errors="ignore"
        )
        self.assertGreaterEqual(text.count("sampleId"), 4)
        self.assertIn("std::atomic<uint64_t>", text)
        self.assertIn("xLardLfnstCoordListHash", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_encoder_static -v
```

Expected: FAIL because the new schema tokens and helpers are absent.

- [ ] **Step 3: Add validation fields to `LardLfnstCovDecision`**

Add in `IntraSearch.h`:

```cpp
uint64_t sampleId = 0;
int      intraMode = -1;
int      lfnstSetIdx = -1;
int      inputVectorDim = 0;
int      scanOrderId = -1;
uint64_t lfnstInputCoordListHash = 0;
double   rhoHBlock = 0.0;
double   rhoVBlock = 0.0;
double   sigma2Res = 0.0;
bool     rhoHValid = false;
bool     rhoVValid = false;
```

Change `xLardLfnst2ndTraceVector` to accept `const LardLfnstCovDecision& sample` in addition to its current arguments.
Declare `LardLfnstCovDecision xLardModelValidationSample(const CodingUnit&, const TransformUnit&, const CPelBuf&, const PelBuf&) const;` as a private `IntraSearch` member so it can legally construct the private nested decision type and derive the exact TU scan geometry.

- [ ] **Step 4: Implement exact pre-transform residual statistics**

Add `xLardModelValidationSample()` and call it before the first `xIntraCodingTUBlock()`:

```cpp
IntraSearch::LardLfnstCovDecision IntraSearch::xLardModelValidationSample(
  const CodingUnit& cu, const TransformUnit& tu,
  const CPelBuf& org, const PelBuf& pred ) const
{
  static std::atomic<uint64_t> nextId { 1 };
  IntraSearch::LardLfnstCovDecision d;
  d.sampleId = nextId.fetch_add( 1, std::memory_order_relaxed );
  const int w = cu.lwidth(), h = cu.lheight();
  double mean = 0.0;
  for( int y = 0; y < h; ++y )
    for( int x = 0; x < w; ++x )
      mean += double( org.at( x, y ) ) - double( pred.at( x, y ) );
  mean /= double( w * h );

  double var = 0.0, hxy = 0.0, hx2 = 0.0, hy2 = 0.0;
  double vxy = 0.0, vx2 = 0.0, vy2 = 0.0;
  for( int y = 0; y < h; ++y ) for( int x = 0; x < w; ++x )
  {
    const double c = double( org.at( x, y ) ) - double( pred.at( x, y ) ) - mean;
    var += c * c;
    if( x + 1 < w )
    {
      const double r = double( org.at( x + 1, y ) ) - double( pred.at( x + 1, y ) ) - mean;
      hxy += c * r; hx2 += c * c; hy2 += r * r;
    }
    if( y + 1 < h )
    {
      const double r = double( org.at( x, y + 1 ) ) - double( pred.at( x, y + 1 ) ) - mean;
      vxy += c * r; vx2 += c * c; vy2 += r * r;
    }
  }
  d.sigma2Res = var / double( w * h );
  d.rhoHValid = hx2 > 0.0 && hy2 > 0.0;
  d.rhoVValid = vx2 > 0.0 && vy2 > 0.0;
  d.rhoHBlock = d.rhoHValid ? hxy / ( std::sqrt( hx2 * hy2 ) + 1e-12 ) : 0.0;
  d.rhoVBlock = d.rhoVValid ? vxy / ( std::sqrt( vx2 * vy2 ) + 1e-12 ) : 0.0;
  return d;
}
```

Enable this helper only when both trace paths are non-empty, Skip15 covariance shadowing is active, `predBuf` exists, and the TU is LFNST-eligible.

- [ ] **Step 5: Implement scan identity and matching schemas**

Use the existing coordinate output of `xLard2ndCollectLfnstInput()` and versioned FNV-1a over ordered `(u,v)` pairs:

```cpp
d.inputVectorDim = sbSize == 8 ? 48 : 16;
d.scanOrderId = ( sbSize << 16 ) | ( d.inputVectorDim << 1 ) | int( transpose );
d.lfnstInputCoordListHash = xLardLfnstCoordListHash( uPos, vPos, d.inputVectorDim );
```

Derive `intraMode`, `lfnstSetIdx`, `sbSize`, and transpose from `cu` and `tu` exactly as `xLardLfnst2ndTraceVector()` does. To obtain coordinates before transform, pass a zero-initialized local `TCoeff` buffer with the TU stride to `xLard2ndCollectLfnstInput()`; the coordinate outputs depend only on geometry and transpose, not coefficient values.

Both CSVs receive:

```text
sampleId,intraMode,modeGroup,lfnstSetIdx,transpose,inputVectorDim,scanOrderId,lfnstInputCoordListHash
```

`motivation_cov.csv` additionally receives:

```text
rho_h_valid,rho_v_valid,rho_h_block,rho_v_block,sigma2_res
```

Pass the local sample to the vector logger, copy it into `lardCovDecision` after `xLardLfnstCovDecision()`, and emit the covariance row only after all candidate costs are collected.

- [ ] **Step 6: Verify GREEN and build**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_encoder_static -v
cmake --build build-lahtp --config Release --target vvencFFapp -j 4
```

Expected: tests PASS and the target builds.

- [ ] **Step 7: Commit**

```powershell
git add source/Lib/EncoderLib/IntraSearch.h source/Lib/EncoderLib/IntraSearch.cpp tools/lard_lfnst/test_model_validation_encoder_static.py
git commit -m "feat: trace paired LFNST model validation samples"
```

### Task 2: Add Run Identity and Deterministic Manifests

**Files:**
- Modify: `tools/lard_lfnst/run_lfnst_motivation_diagnostic.py`
- Modify: `tools/lard_lfnst/test_run_lfnst_motivation_diagnostic.py`

- [ ] **Step 1: Write failing manifest assertions**

```python
manifest = out_root / "model_validation_runs.csv"
self.assertTrue(manifest.exists())
rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
self.assertEqual(rows[0]["runId"], "AerialCity_qp22")
self.assertEqual(rows[0]["sequence"], "AerialCity")
self.assertEqual(rows[0]["configuredQp"], "22")
self.assertEqual(Path(rows[0]["covLog"]).name, "motivation_cov.csv")
self.assertEqual(Path(rows[0]["vecLog"]).name, "empirical_lfnst_vec.csv")
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_run_lfnst_motivation_diagnostic -v
```

Expected: FAIL because no run manifest exists.

- [ ] **Step 3: Write one manifest row per run**

Use:

```python
fieldnames = [
    "runId", "sequence", "configuredQp", "inputPath", "width", "height",
    "frames", "threads", "preset", "covLog", "vecLog", "encoder",
]
```

Set `runId = f"{spec.seq}_qp{qp}"`, reject duplicates before encoding, use paths relative to `out_root` when possible, and record the manifest path in the JSON summary.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m unittest tools.lard_lfnst.test_run_lfnst_motivation_diagnostic -v
git add tools/lard_lfnst/run_lfnst_motivation_diagnostic.py tools/lard_lfnst/test_run_lfnst_motivation_diagnostic.py
git commit -m "feat: record LFNST validation run manifests"
```

### Task 3: Implement Strict Pairing and Integrity Audits

**Files:**
- Create: `tools/lard_lfnst/model_validation_stats.py`
- Create: `tools/lard_lfnst/test_model_validation_stats.py`

- [ ] **Step 1: Write failing pairing tests**

```python
class ModelValidationStatsTests(unittest.TestCase):
    def test_pair_run_rejects_duplicate_ids(self):
        cov, vec = make_matching_frames()
        cov = pd.concat([cov, cov.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate sampleId"):
            pair_run_frames("seq_qp22", cov, vec)

    def test_pair_run_rejects_scan_hash_mismatch(self):
        cov, vec = make_matching_frames()
        vec.loc[0, "lfnstInputCoordListHash"] += 1
        with self.assertRaisesRegex(ValueError, "coordinate-list hash"):
            pair_run_frames("seq_qp22", cov, vec)
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats -v
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement strict schemas and one-to-one pairing**

```python
COV_REQUIRED = {
    "sampleId", "POC", "W", "H", "QP", "absLatDeg", "modeGroup",
    "intraMode", "lfnstSetIdx", "transpose", "inputVectorDim",
    "scanOrderId", "lfnstInputCoordListHash", "rho_h_valid", "rho_v_valid",
    "rho_h_block", "rho_v_block", "sigma2_res", "J0", "J1", "J2",
}
VEC_REQUIRED = {
    "sampleId", "w", "h", "qp", "absLatDeg", "modeGroup", "intraMode",
    "lfnstSetIdx", "transpose", "inputVectorDim", "scanOrderId",
    "lfnstInputCoordListHash", "x00",
}


def pair_run_frames(run_id, cov, vec):
    _require_columns(cov, COV_REQUIRED, "covariance log")
    _require_columns(vec, VEC_REQUIRED, "vector log")
    _reject_duplicate_ids(cov, run_id, "covariance log")
    _reject_duplicate_ids(vec, run_id, "vector log")
    if set(cov.sampleId) != set(vec.sampleId):
        raise ValueError(f"{run_id}: unmatched sampleId sets")
    paired = cov.merge(vec, on="sampleId", validate="one_to_one", suffixes=("", "_vec"))
    checks = (
        ("W", "w", "width"), ("H", "h", "height"),
        ("lfnstSetIdx", "lfnstSetIdx_vec", "LFNST set"),
        ("transpose", "transpose_vec", "transpose"),
        ("inputVectorDim", "inputVectorDim_vec", "input vector dimension"),
        ("scanOrderId", "scanOrderId_vec", "scan order"),
        ("lfnstInputCoordListHash", "lfnstInputCoordListHash_vec", "coordinate-list hash"),
    )
    for left, right, label in checks:
        if not np.array_equal(paired[left].to_numpy(), paired[right].to_numpy()):
            raise ValueError(f"{run_id}: mismatched {label}")
    paired.insert(0, "runId", run_id)
    return paired
```

Implement `read_run_manifest()`, `load_paired_runs()`, and `pairing_audit()`. Reject null/non-finite IDs and identity fields, `absLatDeg` outside `[0,90]`, and non-finite candidate costs before a row enters RD analysis. Build each `xVector` from exactly `inputVectorDim` columns; reject missing, non-finite, or nonzero padded entries.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats -v
git add tools/lard_lfnst/model_validation_stats.py tools/lard_lfnst/test_model_validation_stats.py
git commit -m "feat: validate and pair LFNST model traces"
```

### Task 4: Implement Experiment 4.1 Spatial Statistics

**Files:**
- Modify: `tools/lard_lfnst/model_validation_stats.py`
- Modify: `tools/lard_lfnst/test_model_validation_stats.py`

- [ ] **Step 1: Write failing formula and threshold tests**

```python
def test_centered_adjacent_correlation_matches_definition(self):
    block = np.array([[1.0, 2.0, 4.0], [0.0, 3.0, 5.0]])
    got = centered_adjacent_correlations(block)
    c = block - block.mean()
    expected_h = np.sum(c[:, :-1] * c[:, 1:]) / (
        np.sqrt(np.sum(c[:, :-1] ** 2) * np.sum(c[:, 1:] ** 2)) + EPS
    )
    expected_v = np.sum(c[:-1, :] * c[1:, :]) / (
        np.sqrt(np.sum(c[:-1, :] ** 2) * np.sum(c[1:, :] ** 2)) + EPS
    )
    self.assertAlmostEqual(got.rho_h, expected_h)
    self.assertAlmostEqual(got.rho_v, expected_v)

def test_latitude_bins_and_gate(self):
    self.assertEqual(latitude_bin(0.0), "0-15")
    self.assertEqual(latitude_bin(15.0), "15-30")
    self.assertEqual(latitude_bin(90.0), "75-90")
    self.assertFalse(spatial_group_admitted(199))
    self.assertTrue(spatial_group_admitted(200))
```

Also test that zero directional energy returns `valid=False`, not correlation zero.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats.ModelValidationStatsTests.test_centered_adjacent_correlation_matches_definition -v
```

Expected: FAIL because the APIs are missing.

- [ ] **Step 3: Implement group summaries**

Use exact latitude bins and:

```python
SPATIAL_KEYS = ["sequence", "QP", "W", "H", "latitudeBin"]

def summarize_spatial_groups(samples, min_samples=200, seed=20260705, bootstrap=2000):
    """Return count, admitted, mean, median, and percentile-bootstrap 95% CI."""
```

Resample deterministically within groups. Compute primary `deltaRho = rho_h_block-rho_v_block`; compute `rhoRatio` only when `abs(rho_v_block)>EPS`.

- [ ] **Step 4: Implement model fitting**

For each `sequence/QP/W/H` slice, use the `[0,15)` median only when `0<rho0<1`:

```python
rho_model = rho0 ** np.cos(np.deg2rad(abs_latitude))
```

Report Spearman-H, Spearman-V, their difference, MAE, primary `rho0`, fit validity, and constrained weighted least-squares `rho0Wls`. Do not clip the primary estimate.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats -v
git add tools/lard_lfnst/model_validation_stats.py tools/lard_lfnst/test_model_validation_stats.py
git commit -m "feat: analyze latitude-conditioned residual correlation"
```

### Task 5: Implement Raw and Effective Covariance Validation

**Files:**
- Modify: `tools/lard_lfnst/model_validation_stats.py`
- Modify: `tools/lard_lfnst/test_model_validation_stats.py`
- Modify: `tools/lard_lfnst/run_lfnst_covariance_model_validation.py`
- Modify: `tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py`

- [ ] **Step 1: Write failing covariance tests**

```python
def test_mle_covariance_uses_one_over_n(self):
    x = np.array([[1.0, 2.0], [3.0, 6.0], [5.0, 10.0]])
    centered = x - x.mean(axis=0)
    np.testing.assert_allclose(empirical_covariance_mle(x), centered.T @ centered / 3.0)

def test_effective_operator_masks_horizontal_coordinates(self):
    coords = [(0, 0), (1, 0), (2, 0), (0, 1)]
    d = effective_support_operator(coords, effective_cols=2)
    np.testing.assert_array_equal(np.diag(d), [1.0, 1.0, 0.0, 1.0])

def test_covariance_gate_depends_on_dimension(self):
    self.assertTrue(covariance_group_admitted(200, 16))
    self.assertFalse(covariance_group_admitted(239, 48))
    self.assertTrue(covariance_group_admitted(240, 48))
```

Also test `O_x` against the ordered `i != j` formula and test that non-monotonic theoretical `O_x` across latitude is valid.

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats.ModelValidationStatsTests.test_mle_covariance_uses_one_over_n -v
```

Expected: FAIL because covariance APIs are missing.

- [ ] **Step 3: Extract reusable theory functions without breaking legacy callers**

Move the existing DCT-II, LFNST-coordinate, `theory_matrices_for`, `frobenius_cosine`, `offdiag_abs_mean_corr`, and `diag_dominance` implementations into `model_validation_stats.py`. Re-export them from the old script:

```python
from tools.lard_lfnst.model_validation_stats import (
    TheoryMatrices, diag_dominance, frobenius_cosine,
    offdiag_abs_mean_corr, theory_matrices_for,
)
```

Keep `run_theory_propagation()` and the old CLI arguments operational.

- [ ] **Step 4: Compute raw and effective group comparisons**

Use:

```python
COV_KEYS = [
    "sequence", "QP", "W", "H", "modeGroup",
    "lfnstSetIdx", "transpose", "latitudeBin",
]
```

For admitted groups, compute `SigmaEmpRaw`, theory at group mean `absLatDeg`, `D_K`, `SigmaEmpEffective`, and `SigmaTheoryEffective`. Return one row per `covarianceKind in {raw,effective}` containing `simF`, empirical/theory `O_x`, empirical/theory diagonal dominance, `samples`, `K`, and `meanAbsLatDeg`.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats tools.lard_lfnst.test_run_lfnst_covariance_model_validation -v
git add tools/lard_lfnst/model_validation_stats.py tools/lard_lfnst/test_model_validation_stats.py tools/lard_lfnst/run_lfnst_covariance_model_validation.py tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py
git commit -m "feat: validate raw and effective LFNST covariance"
```

### Task 6: Add Latitude Permutations and Response-vs-RD Metrics

**Files:**
- Modify: `tools/lard_lfnst/model_validation_stats.py`
- Modify: `tools/lard_lfnst/test_model_validation_stats.py`

- [ ] **Step 1: Write failing permutation and RD tests**

```python
def test_shuffle_changes_only_theory_latitude(self):
    groups = synthetic_covariance_groups()
    shuffled = stratified_latitude_permutations(groups, repeats=20, seed=20260705)
    self.assertTrue((shuffled["empiricalGroupId"] == shuffled["sourceGroupId"]).all())
    self.assertTrue((shuffled["W"] == shuffled["WTheory"]).all())
    self.assertTrue((shuffled["permutedLatitude"] != shuffled["meanAbsLatDeg"]).any())

def test_rd_metrics_include_auc_and_top1(self):
    frame = pd.DataFrame({
        "J0": [10, 10, 10, 10], "J1": [8, 12, 9, 11],
        "J2": [11, 9, 12, 8], "S1Resp": [3, 1, 4, 0],
        "S2Resp": [1, 4, 0, 5],
    })
    out = response_rd_metrics(frame)
    self.assertIn("aucPositiveGain", out)
    self.assertIn("candidateTop1Accuracy", out)
    self.assertEqual(out["top1Ties"], 0)
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats.ModelValidationStatsTests.test_rd_metrics_include_auc_and_top1 -v
```

Expected: FAIL because response APIs are absent.

- [ ] **Step 3: Implement stratified theory-latitude permutations**

Hold empirical covariance groups fixed. Within `sequence/QP/W/H/modeGroup/lfnstSetIdx/transpose`, permute only latitude passed to theory and `D_K`. Use seed `20260705`, default 1000 repeats, and one-sided p-value:

```python
p_value = (1 + np.count_nonzero(null_scores >= observed)) / (repeats + 1)
```

Report observed weighted effective `simF`, null mean/standard deviation, paired difference, and p-value.

- [ ] **Step 4: Implement response metrics**

```python
delta1 = J0 - J1
delta2 = J0 - J2
deltaJmax = np.maximum(delta1, delta2)
normalizedGain = deltaJmax / (np.abs(J0) + EPS)
positiveGain = deltaJmax > 0
rdoTop1 = np.where(delta1 > delta2, 1, np.where(delta2 > delta1, 2, 0))
theoryTop1 = np.where(S1Resp > S2Resp, 1, np.where(S2Resp > S1Resp, 2, 0))
```

Report Spearman correlations, ROC AUC with deterministic 2000-resample bootstrap CI, top-1 accuracy excluding ties, tie counts, and empirical majority-candidate baseline. Return AUC `NaN` for one-class slices.

Generate candidate-specific theoretical columns `S1Resp` and `S2Resp` from the same response calculation used to form `GmaxResp`; define `GmaxResp = max(S1Resp,S2Resp)`. Keep `UmaxOffPlus` as the maximum candidate off-diagonal response metric. The top-1 test always uses `S1Resp/S2Resp`, not the maxima.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
python -m unittest tools.lard_lfnst.test_model_validation_stats -v
git add tools/lard_lfnst/model_validation_stats.py tools/lard_lfnst/test_model_validation_stats.py
git commit -m "feat: compare covariance and response against controls"
```

### Task 7: Build the End-to-End CLI and TIP Figures

**Files:**
- Create: `tools/lard_lfnst/run_lfnst_model_validation.py`
- Create: `tools/lard_lfnst/test_run_lfnst_model_validation.py`
- Modify: `docs/lard_lfnst_covariance_model_validation_4_2.md`

- [ ] **Step 1: Write a failing synthetic end-to-end test**

Build paired synthetic logs with 200 rows in each of two latitude bins so the production covariance gate is satisfied, then call:

```python
result = run_model_validation(
    manifest=manifest,
    out_dir=out,
    spatial_min_samples=2,
    covariance_min_factor=1,
    permutation_repeats=20,
    bootstrap_repeats=50,
)
```

Assert:

```python
expected = [
    "sample_pairing_audit.csv", "spatial_correlation_coverage.csv",
    "spatial_correlation_by_group.csv", "spatial_model_fit_summary.csv",
    "covariance_similarity_by_group.csv", "covariance_shuffle_summary.csv",
    "response_rd_summary.csv", "response_auc_top1_summary.csv",
    "theory_covariance_matrices.npz", "empirical_theory_covariance_matrices.npz",
    "fig_4_1_model_validation_overview.png",
    "fig_4_1_model_validation_overview.pdf",
    "fig_4_2_covariance_response_validation.png",
    "fig_4_2_covariance_response_validation.pdf",
    "model_validation_summary.md",
]
for name in expected:
    self.assertTrue((out / name).exists(), name)
```

- [ ] **Step 2: Verify RED**

```powershell
python -m unittest tools.lard_lfnst.test_run_lfnst_model_validation -v
```

Expected: FAIL because the CLI module is absent.

- [ ] **Step 3: Implement orchestration and metadata**

```python
def run_model_validation(
    manifest: Path,
    out_dir: Path,
    spatial_min_samples: int = 200,
    covariance_min_factor: int = 5,
    permutation_repeats: int = 1000,
    bootstrap_repeats: int = 2000,
    seed: int = 20260705,
) -> dict[str, object]:
```

Require `--manifest` and `--out-dir`. Reject stale incompatible output metadata. Write `analysis_metadata.json` with input hashes, seed, thresholds, revision, and command line.

- [ ] **Step 4: Implement the two selected composite figures**

Use 7.16-inch IEEE double-column width, minimum 8-pt final text, vector PDF, and 600-DPI PNG.

Figure 4.1 contains residual-correlation trends with 95% CI, a `deltaRho` latitude-by-size heat table, and compact Spearman-H/Spearman-V results. Figure 4.2 contains 8x8 theoretical propagation, 0/60-degree empirical/theory effective matrices, correct/shuffled effective similarity, and response-quantile/normalized-gain heat tables.

Use `viridis`/`cividis` for sequential values and zero-centered `RdBu_r` for signed matrices. Share color limits by matrix type. Render underfilled cells gray with `n<gate` text.

- [ ] **Step 5: Write non-post-hoc conclusions**

Generate `model_validation_summary.md` with independent sections for spatial trend, covariance-vs-shuffle, and response-vs-RD. Label each `supported`, `weak/content-dependent`, or `not supported` from predeclared comparisons only.

- [ ] **Step 6: Verify GREEN and commit**

```powershell
python -m unittest tools.lard_lfnst.test_run_lfnst_model_validation tools.lard_lfnst.test_model_validation_stats -v
git add tools/lard_lfnst/run_lfnst_model_validation.py tools/lard_lfnst/test_run_lfnst_model_validation.py docs/lard_lfnst_covariance_model_validation_4_2.md
git commit -m "feat: generate LFNST model validation report"
```

### Task 8: Verify Build, Bitstream Neutrality, and Figures

**Files:**
- Modify if defects are found: files changed in Tasks 1-7
- Generate locally: `lahtp_runs/model_validation_smoke/`

- [ ] **Step 1: Run the complete feature test suite**

```powershell
python -m unittest `
  tools.lard_lfnst.test_model_validation_encoder_static `
  tools.lard_lfnst.test_model_validation_stats `
  tools.lard_lfnst.test_run_lfnst_model_validation `
  tools.lard_lfnst.test_run_lfnst_covariance_model_validation `
  tools.lard_lfnst.test_run_lfnst_motivation_diagnostic -v
```

Expected: all tests PASS without warnings or skipped integrity checks.

- [ ] **Step 2: Build the encoder**

```powershell
cmake --build build-lahtp --config Release --target vvencFFapp -j 4
```

Expected: build succeeds; use `build-lahtp/bin/Release/vvencFFapp.exe` for smoke.

- [ ] **Step 3: Run deterministic single-thread anchor and traced encodes**

Use `test/data/RTn23_80x44p15_f15.yuv`, `80x44`, one frame, QP 32, All-Intra, preset medium, and one thread. The traced run adds:

```text
LFNST=1 LardLfnstSkip=15
LardLfnstCovLog=<smoke>/motivation_cov.csv
LardLfnst2ndVecFile=<smoke>/empirical_lfnst_vec.csv
LardLfnstCovMaxRows=100000
```

Compare:

```powershell
Get-FileHash lahtp_runs/model_validation_smoke/anchor.vvc -Algorithm SHA256
Get-FileHash lahtp_runs/model_validation_smoke/traced.vvc -Algorithm SHA256
```

Expected: hashes are identical, traces are non-empty, and rows pair one-to-one.

- [ ] **Step 4: Run multi-thread reconstruction validation**

Repeat with four threads while writing encoder reconstruction files with `-o`. Compare them directly:

```powershell
Get-FileHash lahtp_runs/model_validation_smoke/anchor_mt_rec.yuv -Algorithm MD5
Get-FileHash lahtp_runs/model_validation_smoke/traced_mt_rec.yuv -Algorithm MD5
```

For the formal Linux run, decode both streams with the decoder path already used by `tools/lard_lfnst_patch_decision_spectrum_validation.py`:

```bash
/root/VTM-23.0-rc360-server/bin/DecoderAppStatic -b anchor_mt.vvc -o anchor_mt_dec.yuv
/root/VTM-23.0-rc360-server/bin/DecoderAppStatic -b traced_mt.vvc -o traced_mt_dec.yuv
md5sum anchor_mt_dec.yuv traced_mt_dec.yuv
```

Require matching encoder reconstruction MD5 locally and matching decoded MD5 in the formal server run. Parse the same PSNR/bit-count summary lines from both encoder logs and require equality. Record compressed-byte identity but require it only for the deterministic single-thread run.

- [ ] **Step 5: Run smoke analysis**

```powershell
python tools/lard_lfnst/run_lfnst_model_validation.py `
  --manifest lahtp_runs/model_validation_smoke/model_validation_runs.csv `
  --out-dir lahtp_runs/model_validation_smoke/analysis `
  --spatial-min-samples 2 `
  --covariance-min-factor 1 `
  --permutation-repeats 20 `
  --bootstrap-repeats 50
```

- [ ] **Step 6: Perform visual QA**

Open both PNGs with the image inspection tool. Check glyphs, clipping, overlap, shared matrix scales, gray underfilled cells, and grayscale distinguishability. Correct defects and rerun until both pass.

- [ ] **Step 7: Run final regression checks**

```powershell
git diff --check
git status --short
```

Confirm unrelated dirty-worktree files remain untouched. Re-run Step 1 after any smoke or visual fix.

- [ ] **Step 8: Commit verification fixes**

```powershell
git add source/Lib/EncoderLib/IntraSearch.h source/Lib/EncoderLib/IntraSearch.cpp tools/lard_lfnst/model_validation_stats.py tools/lard_lfnst/run_lfnst_model_validation.py tools/lard_lfnst/test_model_validation_encoder_static.py tools/lard_lfnst/test_model_validation_stats.py tools/lard_lfnst/test_run_lfnst_model_validation.py tools/lard_lfnst/run_lfnst_motivation_diagnostic.py tools/lard_lfnst/test_run_lfnst_motivation_diagnostic.py tools/lard_lfnst/run_lfnst_covariance_model_validation.py tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py docs/lard_lfnst_covariance_model_validation_4_2.md
git commit -m "test: verify LFNST model validation workflow"
```

Do not add `lahtp_runs/model_validation_smoke/`; it is reproducible run output.
