# LFNST Covariance 4.2 Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the formal Experiment 4.2 offline analysis that compares theoretical LFNST low-frequency covariance against empirical LFNST input vectors and real RDO gains.

**Architecture:** Keep encoder logging unchanged and add a focused Python metrics module consumed by the existing `run_lfnst_covariance_model_validation.py` runner. The module normalizes vector/RDO logs into canonical group records, computes empirical/theoretical correlation matrices, formal NCE/Spearman/response/top-1/reliability metrics, and writes group-level CSVs plus figures. Existing legacy outputs stay available.

**Tech Stack:** Python 3.8+, NumPy, pandas, matplotlib, unittest, existing VVenC LFNST theory helpers.

---

## File Structure

- Create `tools/lard_lfnst/experiment_4_2_metrics.py`: canonical schema, covariance accumulation, correlation/NCE/Spearman, response metrics, RDO gain aggregation, output writers.
- Create `tools/lard_lfnst/test_experiment_4_2_metrics.py`: unit tests for the new pure functions and synthetic end-to-end group metrics.
- Modify `tools/lard_lfnst/run_lfnst_covariance_model_validation.py`: add formal 4.2 mode that calls the new module and writes the new outputs.
- Modify `tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py`: CLI/output contract tests for the formal mode.
- Modify `docs/lard_lfnst_covariance_model_validation_4_2.md`: document the formal metrics and command line after implementation.

## Task 1: Canonical Log Schema and Covariance Core

**Files:**
- Create: `tools/lard_lfnst/experiment_4_2_metrics.py`
- Create: `tools/lard_lfnst/test_experiment_4_2_metrics.py`

- [ ] **Step 1: Write failing schema/covariance tests**

Add this test content to `tools/lard_lfnst/test_experiment_4_2_metrics.py`:

```python
from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from tools.lard_lfnst import experiment_4_2_metrics as m


class Experiment42MetricsTests(unittest.TestCase):
    def test_canonical_vector_row_accepts_legacy_names(self) -> None:
        row = {
            "poc": 3,
            "x": 4,
            "y": 8,
            "w": 8,
            "h": 8,
            "qp": 32,
            "latBucket": 2,
            "lfnstSetIdx": 1,
            "transposeFlag": 1,
            "trSize": 48,
            "zeroOutSize": 8,
            "x00": 1.0,
            "x01": -2.0,
        }
        vec = m.canonical_vector_row(row, theta_values=[0.0, 30.0, 60.0, 75.0])
        self.assertEqual(vec.group_key, m.GroupKey(qp=32, w=8, h=8, lat_bin=2, set_idx=1, transpose=1, k=48))
        self.assertEqual(vec.kz, 8)
        self.assertEqual(vec.values.shape, (48,))
        self.assertEqual(vec.values[0], 1.0)
        self.assertEqual(vec.values[1], -2.0)

    def test_canonical_rdo_row_accepts_cov_log_names(self) -> None:
        row = {
            "POC": 3,
            "x": 4,
            "y": 8,
            "W": 16,
            "H": 16,
            "QP": 32,
            "latBin": 3,
            "setIdx": 2,
            "transpose": 0,
            "kIn": 48,
            "J0": 100.0,
            "J1": 90.0,
            "J2": 130.0,
            "bestIdx": 1,
            "sigma2_res": 7.5,
        }
        rdo = m.canonical_rdo_row(row)
        self.assertEqual(rdo.group_key, m.GroupKey(qp=32, w=16, h=16, lat_bin=3, set_idx=2, transpose=0, k=48))
        self.assertEqual(rdo.delta_j1, 10.0)
        self.assertEqual(rdo.delta_j2, -30.0)
        self.assertEqual(rdo.delta_jmax, 10.0)

    def test_cov_accumulator_uses_mean_centered_unbiased_covariance(self) -> None:
        acc = m.CovAccumulator(dim=2)
        acc.add(np.array([1.0, 2.0]))
        acc.add(np.array([3.0, 4.0]))
        cov = acc.covariance()
        expected = np.array([[2.0, 2.0], [2.0, 2.0]])
        self.assertTrue(np.allclose(cov, expected))

    def test_corr_and_nce_mask_zero_variance_dimensions(self) -> None:
        sigma_emp = np.array([[4.0, 2.0, 0.0], [2.0, 9.0, 0.0], [0.0, 0.0, 0.0]])
        sigma_th = np.array([[4.0, 1.0, 0.0], [1.0, 9.0, 0.0], [0.0, 0.0, 0.0]])
        r_emp, active = m.correlation_matrix(sigma_emp)
        r_th, _ = m.correlation_matrix(sigma_th)
        self.assertEqual(active.tolist(), [True, True, False])
        full = m.normalized_covariance_error(r_emp, r_th, active, offdiag_only=False)
        off = m.normalized_covariance_error(r_emp, r_th, active, offdiag_only=True)
        self.assertGreater(full, 0.0)
        self.assertGreater(off, 0.0)
        self.assertLess(off, 1.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: FAIL with `ImportError` because `experiment_4_2_metrics.py` does not exist.

- [ ] **Step 3: Implement canonical dataclasses and covariance core**

Create `tools/lard_lfnst/experiment_4_2_metrics.py` with these public definitions:

```python
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

EPS = 1.0e-12
DEFAULT_THETA_VALUES = [0.0, 30.0, 60.0, 75.0]


@dataclass(frozen=True, order=True)
class GroupKey:
    qp: int
    w: int
    h: int
    lat_bin: int
    set_idx: int
    transpose: int
    k: int


@dataclass(frozen=True)
class VectorSample:
    group_key: GroupKey
    kz: int
    values: np.ndarray
    sigma2_res: float | None = None


@dataclass(frozen=True)
class RdoSample:
    group_key: GroupKey
    j0: float
    j1: float
    j2: float
    best_idx: int
    sigma2_res: float | None

    @property
    def delta_j1(self) -> float:
        return self.j0 - self.j1

    @property
    def delta_j2(self) -> float:
        return self.j0 - self.j2

    @property
    def delta_jmax(self) -> float:
        return self.j0 - min(self.j1, self.j2)


def _value(row: dict[str, object], *names: str, default: object | None = None) -> object | None:
    for name in names:
        if name in row and row[name] != "":
            return row[name]
    return default


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: object, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def zero_out_retained_count(w: int, h: int) -> int:
    return 8 if (w == 4 and h == 4) or (w == 8 and h == 8) else 16


def lat_bin_from_row(row: dict[str, object], theta_values: list[float]) -> int:
    direct = _value(row, "latBin", "lat_bin", default=None)
    if direct is not None:
        return _to_int(direct)
    bucket = _value(row, "latBucket", default=None)
    if bucket is not None:
        return min(max(_to_int(bucket), 0), len(theta_values) - 1)
    abs_lat = _to_float(_value(row, "absLatDeg", default=0.0), 0.0)
    values = np.asarray(theta_values, dtype=np.float64)
    return int(np.argmin(np.abs(values - abs_lat)))


def canonical_vector_row(row: dict[str, object], theta_values: list[float] | None = None) -> VectorSample:
    theta_values = theta_values or DEFAULT_THETA_VALUES
    w = _to_int(_value(row, "w", "W"))
    h = _to_int(_value(row, "h", "H"))
    qp = _to_int(_value(row, "qp", "QP"))
    lat_bin = lat_bin_from_row(row, theta_values)
    set_idx = _to_int(_value(row, "lfnstSetIdx", "setIdx", "lfnstSet", default=0))
    transpose = _to_int(_value(row, "transposeFlag", "transpose", default=0))
    k = _to_int(_value(row, "trSize", "inputVectorDim", "kIn", default=48))
    values = np.zeros(k, dtype=np.float64)
    for idx in range(k):
        values[idx] = _to_float(_value(row, f"x{idx:02d}", default=0.0), 0.0)
    sigma2_res = _to_float(_value(row, "sigma2_res", default=math.nan))
    return VectorSample(
        group_key=GroupKey(qp=qp, w=w, h=h, lat_bin=lat_bin, set_idx=set_idx, transpose=transpose, k=k),
        kz=zero_out_retained_count(w, h),
        values=np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0),
        sigma2_res=sigma2_res if math.isfinite(sigma2_res) else None,
    )


def canonical_rdo_row(row: dict[str, object]) -> RdoSample | None:
    j0 = _to_float(_value(row, "J0", default=math.nan))
    j1 = _to_float(_value(row, "J1", default=math.nan))
    j2 = _to_float(_value(row, "J2", default=math.nan))
    if not all(math.isfinite(v) and abs(v) < 1.0e300 for v in (j0, j1, j2)):
        return None
    w = _to_int(_value(row, "w", "W"))
    h = _to_int(_value(row, "h", "H"))
    qp = _to_int(_value(row, "qp", "QP"))
    k = _to_int(_value(row, "kIn", "trSize", "inputVectorDim", default=48))
    sigma2_res = _to_float(_value(row, "sigma2_res", default=math.nan))
    return RdoSample(
        group_key=GroupKey(
            qp=qp,
            w=w,
            h=h,
            lat_bin=_to_int(_value(row, "latBin", "lat_bin", default=0)),
            set_idx=_to_int(_value(row, "setIdx", "lfnstSetIdx", "lfnstSet", default=0)),
            transpose=_to_int(_value(row, "transpose", "transposeFlag", default=0)),
            k=k,
        ),
        j0=j0,
        j1=j1,
        j2=j2,
        best_idx=_to_int(_value(row, "bestIdx", default=0)),
        sigma2_res=sigma2_res if math.isfinite(sigma2_res) else None,
    )


class CovAccumulator:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.n = 0
        self.sum_x = np.zeros(dim, dtype=np.float64)
        self.sum_xx = np.zeros((dim, dim), dtype=np.float64)
        self.sigma2_values: list[float] = []

    def add(self, values: np.ndarray, sigma2_res: float | None = None) -> None:
        vec = np.asarray(values[: self.dim], dtype=np.float64)
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
        self.n += 1
        self.sum_x += vec
        self.sum_xx += np.outer(vec, vec)
        if sigma2_res is not None and math.isfinite(sigma2_res):
            self.sigma2_values.append(float(sigma2_res))

    def add_many(self, values: np.ndarray) -> None:
        vals = np.asarray(values[:, : self.dim], dtype=np.float64)
        vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
        self.n += int(vals.shape[0])
        self.sum_x += vals.sum(axis=0)
        self.sum_xx += vals.T @ vals

    def covariance(self) -> np.ndarray:
        if self.n <= 1:
            return np.zeros((self.dim, self.dim), dtype=np.float64)
        mean = self.sum_x / float(self.n)
        cov = (self.sum_xx - float(self.n) * np.outer(mean, mean)) / float(self.n - 1)
        return (cov + cov.T) * 0.5

    def sigma2_mean(self) -> float:
        return float(np.mean(self.sigma2_values)) if self.sigma2_values else 1.0


def correlation_matrix(sigma: np.ndarray, eps: float = EPS) -> tuple[np.ndarray, np.ndarray]:
    diag = np.asarray(np.diag(sigma), dtype=np.float64)
    active = np.isfinite(diag) & (diag > eps)
    scale = np.sqrt(np.maximum(diag, eps))
    corr = sigma / (scale[:, None] * scale[None, :] + eps)
    corr[~np.isfinite(corr)] = 0.0
    return corr, active


def normalized_covariance_error(r_emp: np.ndarray, r_th: np.ndarray, active: np.ndarray, offdiag_only: bool) -> float:
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return math.nan
    emp = r_emp[np.ix_(idx, idx)]
    th = r_th[np.ix_(idx, idx)]
    if offdiag_only:
        mask = ~np.eye(emp.shape[0], dtype=bool)
        emp_vec = emp[mask]
        th_vec = th[mask]
    else:
        emp_vec = emp.ravel()
        th_vec = th.ravel()
    denom = float(np.linalg.norm(emp_vec)) + EPS
    return float(np.linalg.norm(emp_vec - th_vec) / denom)
```

- [ ] **Step 4: Run schema/covariance tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: PASS for the four tests from Step 1.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add tools/lard_lfnst/experiment_4_2_metrics.py tools/lard_lfnst/test_experiment_4_2_metrics.py
git commit -m "feat: add experiment 4.2 covariance metric core"
```

## Task 2: Spearman, Response Metrics, and Top-1 Candidate Match

**Files:**
- Modify: `tools/lard_lfnst/experiment_4_2_metrics.py`
- Modify: `tools/lard_lfnst/test_experiment_4_2_metrics.py`

- [ ] **Step 1: Add failing metric tests**

Append these tests to `Experiment42MetricsTests`:

```python
    def test_spearman_handles_order_and_constant_vectors(self) -> None:
        self.assertAlmostEqual(m.spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]), 1.0)
        self.assertAlmostEqual(m.spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]), -1.0)
        self.assertTrue(math.isnan(m.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])))

    def test_covariance_rank_correlation_uses_upper_offdiag(self) -> None:
        r_emp = np.array([[1.0, 0.9, 0.2], [0.9, 1.0, 0.4], [0.2, 0.4, 1.0]])
        r_th = np.array([[1.0, 0.8, 0.1], [0.8, 1.0, 0.3], [0.1, 0.3, 1.0]])
        rho, valid = m.covariance_rank_correlation(r_emp, r_th, np.array([True, True, True]))
        self.assertEqual(valid, 1)
        self.assertAlmostEqual(rho, 1.0)

    def test_response_metrics_and_top1_match(self) -> None:
        sigma = np.eye(4)
        lfnst = np.array(
            [
                [[2.0, 0.0, 0.0, 0.0], [0.0, 0.5, 0.0, 0.0]],
                [[0.0, 2.0, 0.0, 0.0], [0.0, 0.0, 0.5, 0.0]],
            ],
            dtype=np.float64,
        )
        metrics = m.response_metrics(sigma, lfnst)
        self.assertGreater(metrics["G1_resp"], metrics["G2_resp"])
        self.assertEqual(m.theory_top1_candidate(metrics), 1)
        rdo = m.rdo_group_metrics(
            [
                m.RdoSample(m.GroupKey(32, 4, 4, 0, 0, 0, 4), 100.0, 80.0, 110.0, 1, None),
                m.RdoSample(m.GroupKey(32, 4, 4, 0, 0, 0, 4), 120.0, 100.0, 130.0, 1, None),
            ]
        )
        self.assertEqual(rdo["rdo_top1"], 1)
        self.assertEqual(rdo["top1_rdo_valid"], 1)
        self.assertAlmostEqual(rdo["P_positive_gain"], 1.0)
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: FAIL because `spearman`, `covariance_rank_correlation`, `response_metrics`, `theory_top1_candidate`, and `rdo_group_metrics` are absent.

- [ ] **Step 3: Implement rank and response helpers**

Append these functions to `experiment_4_2_metrics.py`:

```python
def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and sorted_values[end] == sorted_values[start]:
            end += 1
        rank = 0.5 * (start + end - 1) + 1.0
        ranks[order[start:end]] = rank
        start = end
    return ranks


def spearman(x: Iterable[float], y: Iterable[float]) -> float:
    xa = np.asarray(list(x), dtype=np.float64)
    ya = np.asarray(list(y), dtype=np.float64)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa = xa[mask]
    ya = ya[mask]
    if xa.size < 2:
        return math.nan
    rx = _rankdata(xa)
    ry = _rankdata(ya)
    if np.std(rx) <= EPS or np.std(ry) <= EPS:
        return math.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def upper_offdiag_values(mat: np.ndarray, active: np.ndarray) -> np.ndarray:
    idx = np.flatnonzero(active)
    if idx.size < 2:
        return np.asarray([], dtype=np.float64)
    sub = mat[np.ix_(idx, idx)]
    rows, cols = np.triu_indices(sub.shape[0], k=1)
    return sub[rows, cols].astype(np.float64, copy=False)


def covariance_rank_correlation(r_emp: np.ndarray, r_th: np.ndarray, active: np.ndarray) -> tuple[float, int]:
    emp = upper_offdiag_values(r_emp, active)
    th = upper_offdiag_values(r_th, active)
    rho = spearman(emp, th)
    return rho, int(math.isfinite(rho))


def offdiag_abs_mean_corr_from_corr(r: np.ndarray, active: np.ndarray) -> float:
    vals = upper_offdiag_values(np.abs(r), active)
    return float(np.mean(vals)) if vals.size else math.nan


def diag_dominance(sigma: np.ndarray, active: np.ndarray | None = None) -> float:
    if active is None:
        active = np.ones(sigma.shape[0], dtype=bool)
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return math.nan
    sub = sigma[np.ix_(idx, idx)]
    return float(np.sum(np.abs(np.diag(sub))) / (np.sum(np.abs(sub)) + EPS))


def response_metrics(sigma: np.ndarray, lfnst: np.ndarray) -> dict[str, float]:
    rows = []
    for cand in range(2):
        mat = np.asarray(lfnst[cand], dtype=np.float64)
        cov_y = mat @ sigma @ mat.T
        diag_energy = float(np.trace(cov_y))
        off = cov_y.copy()
        np.fill_diagonal(off, 0.0)
        off_plus = float(np.sum(np.maximum(off, 0.0)))
        rows.append((diag_energy, off_plus))
    return {
        "G1_resp": rows[0][0],
        "G2_resp": rows[1][0],
        "G_max_resp": max(rows[0][0], rows[1][0]),
        "U1_offplus": rows[0][1],
        "U2_offplus": rows[1][1],
        "U_max_offplus": max(rows[0][1], rows[1][1]),
    }


def theory_top1_candidate(metrics: dict[str, float], lambda_u: float = 0.0) -> int:
    s1 = float(metrics["G1_resp"]) + lambda_u * float(metrics["U1_offplus"])
    s2 = float(metrics["G2_resp"]) + lambda_u * float(metrics["U2_offplus"])
    return 1 if s1 >= s2 else 2


def rdo_group_metrics(samples: list[RdoSample]) -> dict[str, float | int]:
    if not samples:
        return {
            "rdo_count": 0,
            "deltaJ1_mean": math.nan,
            "deltaJ2_mean": math.nan,
            "deltaJmax_mean": math.nan,
            "P_positive_gain": math.nan,
            "P_no_gain": math.nan,
            "rdo_top1": 0,
            "top1_rdo_valid": 0,
        }
    d1 = np.asarray([s.delta_j1 for s in samples], dtype=np.float64)
    d2 = np.asarray([s.delta_j2 for s in samples], dtype=np.float64)
    dm = np.asarray([s.delta_jmax for s in samples], dtype=np.float64)
    mean1 = float(np.mean(d1))
    mean2 = float(np.mean(d2))
    max_gain = max(mean1, mean2)
    return {
        "rdo_count": len(samples),
        "deltaJ1_mean": mean1,
        "deltaJ2_mean": mean2,
        "deltaJmax_mean": float(np.mean(dm)),
        "P_positive_gain": float(np.mean(dm > 0.0)),
        "P_no_gain": float(np.mean(dm <= 0.0)),
        "rdo_top1": 1 if mean1 >= mean2 else 2,
        "top1_rdo_valid": int(max_gain > 0.0),
    }
```

- [ ] **Step 4: Run metric tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: PASS for Task 1 and Task 2 tests.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add tools/lard_lfnst/experiment_4_2_metrics.py tools/lard_lfnst/test_experiment_4_2_metrics.py
git commit -m "feat: compute experiment 4.2 rank and response metrics"
```

## Task 3: Group-Level Formal Analysis

**Files:**
- Modify: `tools/lard_lfnst/experiment_4_2_metrics.py`
- Modify: `tools/lard_lfnst/test_experiment_4_2_metrics.py`

- [ ] **Step 1: Add failing synthetic group analysis test**

Append this test:

```python
    def test_analyze_groups_writes_formal_metric_tables(self) -> None:
        key = m.GroupKey(qp=32, w=4, h=4, lat_bin=0, set_idx=0, transpose=0, k=4)
        acc = m.CovAccumulator(dim=4)
        for vec in (
            np.array([1.0, 0.0, 0.0, 0.0]),
            np.array([2.0, 0.0, 0.0, 0.0]),
            np.array([3.0, 0.0, 0.0, 0.0]),
        ):
            acc.add(vec)
        rdos = {
            key: [
                m.RdoSample(key, 100.0, 80.0, 120.0, 1, 1.0),
                m.RdoSample(key, 120.0, 100.0, 140.0, 1, 1.0),
            ]
        }
        lfnst_by_key = {
            key: np.array(
                [
                    [[2.0, 0.0, 0.0, 0.0], [0.0, 0.5, 0.0, 0.0]],
                    [[0.0, 2.0, 0.0, 0.0], [0.0, 0.0, 0.5, 0.0]],
                ],
                dtype=np.float64,
            )
        }
        theory_by_key = {key: acc.covariance()}
        with tempfile.TemporaryDirectory() as tmp:
            result = m.write_formal_analysis_outputs(
                out_dir=Path(tmp),
                empirical_accs={key: acc},
                theory_cov_by_key=theory_by_key,
                lfnst_by_key=lfnst_by_key,
                rdo_by_key=rdos,
                min_samples=2,
            )
            self.assertEqual(result["groups"], 1)
            cov = pd.read_csv(Path(tmp) / "covariance_group_metrics.csv")
            top = pd.read_csv(Path(tmp) / "top1_candidate_match.csv")
            rel = pd.read_csv(Path(tmp) / "low_gain_reliability_curve.csv")
            self.assertIn("NCE_full", cov.columns)
            self.assertIn("NCE_off", cov.columns)
            self.assertEqual(int(top["match"].iloc[0]), 1)
            self.assertIn("P_no_gain", rel.columns)
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: FAIL because `write_formal_analysis_outputs` is absent.

- [ ] **Step 3: Implement group analysis and output writer**

Append these functions to `experiment_4_2_metrics.py`:

```python
def _row_from_key(key: GroupKey) -> dict[str, int]:
    return {
        "QP": key.qp,
        "W": key.w,
        "H": key.h,
        "latBin": key.lat_bin,
        "setIdx": key.set_idx,
        "transpose": key.transpose,
        "K": key.k,
        "Kz": zero_out_retained_count(key.w, key.h),
    }


def zscore(values: np.ndarray) -> np.ndarray:
    vals = np.asarray(values, dtype=np.float64)
    mu = np.nanmean(vals)
    sd = np.nanstd(vals)
    if not math.isfinite(sd) or sd <= EPS:
        return np.zeros_like(vals)
    return (vals - mu) / sd


def reliability_curve(group_df: pd.DataFrame, bins: int = 6) -> pd.DataFrame:
    if group_df.empty:
        return pd.DataFrame(columns=["bin", "groups", "S_low_min", "S_low_max", "P_no_gain"])
    frame = group_df.copy()
    components = [
        -frame["O_x_th"].to_numpy(dtype=np.float64),
        frame["chi_diag_th"].to_numpy(dtype=np.float64),
        -frame["G_max_resp_th"].to_numpy(dtype=np.float64),
        -frame["U_max_offplus_th"].to_numpy(dtype=np.float64),
    ]
    frame["S_low"] = sum(zscore(v) for v in components)
    frame = frame[np.isfinite(frame["S_low"]) & np.isfinite(frame["P_no_gain"])].copy()
    if frame.empty:
        return pd.DataFrame(columns=["bin", "groups", "S_low_min", "S_low_max", "P_no_gain"])
    q = min(max(1, bins), len(frame))
    frame["bin"] = pd.qcut(frame["S_low"].rank(method="first"), q=q, labels=[f"Q{i + 1}" for i in range(q)])
    return (
        frame.groupby("bin", observed=True)
        .agg(groups=("S_low", "size"), S_low_min=("S_low", "min"), S_low_max=("S_low", "max"), P_no_gain=("P_no_gain", "mean"))
        .reset_index()
    )


def write_formal_analysis_outputs(
    out_dir: Path,
    empirical_accs: dict[GroupKey, CovAccumulator],
    theory_cov_by_key: dict[GroupKey, np.ndarray],
    lfnst_by_key: dict[GroupKey, np.ndarray],
    rdo_by_key: dict[GroupKey, list[RdoSample]],
    min_samples: int,
    lambda_u: float = 0.0,
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cov_rows: list[dict[str, float | int]] = []
    resp_rows: list[dict[str, float | int]] = []
    rdo_rows: list[dict[str, float | int]] = []
    top_rows: list[dict[str, float | int]] = []
    matrices: dict[str, np.ndarray] = {}
    for key, acc in sorted(empirical_accs.items()):
        coverage = {**_row_from_key(key), "samples": acc.n, "admitted": int(acc.n >= min_samples)}
        if acc.n < min_samples or key not in theory_cov_by_key:
            cov_rows.append({**coverage, "NCE_full": math.nan, "NCE_off": math.nan, "rho_rank_cov": math.nan, "rank_valid": 0})
            continue
        sigma_emp = acc.covariance()
        sigma_th = np.asarray(theory_cov_by_key[key], dtype=np.float64)[: key.k, : key.k]
        r_emp, active_emp = correlation_matrix(sigma_emp)
        r_th, active_th = correlation_matrix(sigma_th)
        active = active_emp & active_th
        rho_rank, rank_valid = covariance_rank_correlation(r_emp, r_th, active)
        row_base = _row_from_key(key)
        cov_rows.append(
            {
                **row_base,
                "samples": acc.n,
                "admitted": 1,
                "NCE_full": normalized_covariance_error(r_emp, r_th, active, offdiag_only=False),
                "NCE_off": normalized_covariance_error(r_emp, r_th, active, offdiag_only=True),
                "rho_rank_cov": rho_rank,
                "rank_valid": rank_valid,
                "O_x_emp": offdiag_abs_mean_corr_from_corr(r_emp, active),
                "O_x_th": offdiag_abs_mean_corr_from_corr(r_th, active),
                "chi_diag_emp": diag_dominance(sigma_emp, active),
                "chi_diag_th": diag_dominance(sigma_th, active),
            }
        )
        matrices[f"emp_qp{key.qp}_{key.w}x{key.h}_lat{key.lat_bin}_set{key.set_idx}_tr{key.transpose}_k{key.k}"] = sigma_emp.astype(np.float32)
        matrices[f"th_qp{key.qp}_{key.w}x{key.h}_lat{key.lat_bin}_set{key.set_idx}_tr{key.transpose}_k{key.k}"] = sigma_th.astype(np.float32)
        if key in lfnst_by_key:
            emp_resp = response_metrics(sigma_emp, lfnst_by_key[key])
            th_resp = response_metrics(sigma_th, lfnst_by_key[key])
            resp_row = {
                **row_base,
                "G1_resp_emp": emp_resp["G1_resp"],
                "G2_resp_emp": emp_resp["G2_resp"],
                "G_max_resp_emp": emp_resp["G_max_resp"],
                "U1_offplus_emp": emp_resp["U1_offplus"],
                "U2_offplus_emp": emp_resp["U2_offplus"],
                "U_max_offplus_emp": emp_resp["U_max_offplus"],
                "G1_resp_th": th_resp["G1_resp"],
                "G2_resp_th": th_resp["G2_resp"],
                "G_max_resp_th": th_resp["G_max_resp"],
                "U1_offplus_th": th_resp["U1_offplus"],
                "U2_offplus_th": th_resp["U2_offplus"],
                "U_max_offplus_th": th_resp["U_max_offplus"],
                "theory_top1": theory_top1_candidate(th_resp, lambda_u=lambda_u),
            }
            resp_rows.append(resp_row)
            rdo = rdo_group_metrics(rdo_by_key.get(key, []))
            rdo_rows.append({**row_base, **rdo})
            if int(rdo["top1_rdo_valid"]):
                top_rows.append(
                    {
                        **row_base,
                        "theory_top1": resp_row["theory_top1"],
                        "rdo_top1": rdo["rdo_top1"],
                        "match": int(resp_row["theory_top1"] == rdo["rdo_top1"]),
                        "deltaJ1_mean": rdo["deltaJ1_mean"],
                        "deltaJ2_mean": rdo["deltaJ2_mean"],
                    }
                )
    cov_df = pd.DataFrame(cov_rows)
    resp_df = pd.DataFrame(resp_rows)
    rdo_df = pd.DataFrame(rdo_rows)
    top_df = pd.DataFrame(top_rows)
    cov_df.to_csv(out_dir / "covariance_group_metrics.csv", index=False)
    resp_df.to_csv(out_dir / "response_group_metrics.csv", index=False)
    rdo_df.to_csv(out_dir / "rdo_gain_group_metrics.csv", index=False)
    top_df.to_csv(out_dir / "top1_candidate_match.csv", index=False)
    if matrices:
        np.savez_compressed(out_dir / "empirical_theory_covariance_matrices.npz", **matrices)
    merged = cov_df.merge(resp_df, on=["QP", "W", "H", "latBin", "setIdx", "transpose", "K", "Kz"], how="inner")
    merged = merged.merge(rdo_df, on=["QP", "W", "H", "latBin", "setIdx", "transpose", "K", "Kz"], how="inner")
    rank_rows = [
        {"metric": "O_x", "spearman_emp_th": spearman(merged["O_x_th"], merged["O_x_emp"]) if not merged.empty else math.nan},
        {"metric": "chi_diag", "spearman_emp_th": spearman(merged["chi_diag_th"], merged["chi_diag_emp"]) if not merged.empty else math.nan},
        {"metric": "G_max_resp", "spearman_emp_th": spearman(merged["G_max_resp_th"], merged["G_max_resp_emp"]) if not merged.empty else math.nan},
        {"metric": "U_max_offplus", "spearman_emp_th": spearman(merged["U_max_offplus_th"], merged["U_max_offplus_emp"]) if not merged.empty else math.nan},
        {"metric": "G_vs_P_positive", "spearman_emp_th": spearman(merged["G_max_resp_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
        {"metric": "U_vs_P_positive", "spearman_emp_th": spearman(merged["U_max_offplus_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
        {"metric": "O_vs_P_positive", "spearman_emp_th": spearman(merged["O_x_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
        {"metric": "chi_vs_P_positive", "spearman_emp_th": spearman(merged["chi_diag_th"], merged["P_positive_gain"]) if not merged.empty else math.nan},
    ]
    pd.DataFrame(rank_rows).to_csv(out_dir / "metric_rank_correlations.csv", index=False)
    reliability_curve(merged).to_csv(out_dir / "low_gain_reliability_curve.csv", index=False)
    pd.DataFrame(
        [
            {
                "groups": int(len(cov_df)),
                "admitted_groups": int(cov_df["admitted"].sum()) if "admitted" in cov_df else 0,
                "top1_groups": int(len(top_df)),
                "Top1Match": float(top_df["match"].mean()) if not top_df.empty else math.nan,
                "median_NCE_full": float(cov_df["NCE_full"].median()) if "NCE_full" in cov_df else math.nan,
                "median_NCE_off": float(cov_df["NCE_off"].median()) if "NCE_off" in cov_df else math.nan,
            }
        ]
    ).to_csv(out_dir / "covariance_validation_summary.csv", index=False)
    return {"groups": int(len(cov_df)), "top1_groups": int(len(top_df))}
```

- [ ] **Step 4: Run group analysis tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: PASS for Tasks 1--3.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add tools/lard_lfnst/experiment_4_2_metrics.py tools/lard_lfnst/test_experiment_4_2_metrics.py
git commit -m "feat: write experiment 4.2 formal group metrics"
```

## Task 4: Integrate Formal Mode into Existing Runner

**Files:**
- Modify: `tools/lard_lfnst/run_lfnst_covariance_model_validation.py`
- Modify: `tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py`

- [ ] **Step 1: Add failing CLI formal-mode test**

Add this test to `CovarianceModelValidationTests` in `tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py`:

```python
    def test_formal_mode_writes_experiment_4_2_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            vec = out / "vec.csv"
            cov = out / "cov.csv"
            _write_vec_log(vec)
            cov.write_text(
                "POC,x,y,W,H,QP,latBin,setIdx,transpose,kIn,J0,J1,J2,bestIdx,sigma2_res\n"
                "0,0,0,4,4,32,0,0,0,16,100,80,120,1,1.0\n"
                "0,4,0,4,4,32,0,0,0,16,120,100,140,1,1.0\n",
                encoding="utf-8",
            )
            result = cov42.run_formal_experiment_4_2(
                vec_logs=[vec],
                cov_logs=[cov],
                out_dir=out / "formal",
                sizes=[(4, 4)],
                theta_values=[0.0, 60.0],
                min_samples=2,
                write_figures=False,
            )
            self.assertGreaterEqual(result["groups"], 1)
            self.assertTrue((out / "formal" / "covariance_group_metrics.csv").exists())
            self.assertTrue((out / "formal" / "metric_rank_correlations.csv").exists())
            self.assertTrue((out / "formal" / "top1_candidate_match.csv").exists())
            self.assertTrue((out / "formal" / "low_gain_reliability_curve.csv").exists())
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_run_lfnst_covariance_model_validation -v
```

Expected: FAIL because `run_formal_experiment_4_2` does not exist.

- [ ] **Step 3: Implement `run_formal_experiment_4_2`**

In `run_lfnst_covariance_model_validation.py`, import the new module:

```python
from tools.lard_lfnst import experiment_4_2_metrics as exp42
from tools.compute_lfnst_theory_stats import parse_rom_lfnst
```

Add a helper that streams logs into accumulators:

```python
def _read_formal_vectors(vec_logs: list[Path], theta_values: list[float]) -> dict[exp42.GroupKey, exp42.CovAccumulator]:
    accs: dict[exp42.GroupKey, exp42.CovAccumulator] = {}
    for path in vec_logs:
        for chunk in pd.read_csv(path, chunksize=200000):
            for _, row in chunk.iterrows():
                sample = exp42.canonical_vector_row(row.to_dict(), theta_values=theta_values)
                acc = accs.setdefault(sample.group_key, exp42.CovAccumulator(sample.group_key.k))
                acc.add(sample.values, sample.sigma2_res)
    return accs


def _read_formal_rdo(cov_logs: list[Path]) -> dict[exp42.GroupKey, list[exp42.RdoSample]]:
    out: dict[exp42.GroupKey, list[exp42.RdoSample]] = {}
    for path in cov_logs:
        for chunk in pd.read_csv(path, chunksize=200000):
            for _, row in chunk.iterrows():
                sample = exp42.canonical_rdo_row(row.to_dict())
                if sample is None:
                    continue
                out.setdefault(sample.group_key, []).append(sample)
    return out
```

Add the public runner:

```python
def run_formal_experiment_4_2(
    vec_logs: list[Path],
    cov_logs: list[Path],
    out_dir: Path,
    sizes: list[tuple[int, int]],
    theta_values: list[float],
    min_samples: int,
    write_figures: bool = True,
    lambda_u: float = 0.0,
    rom_lfnst: Path = Path("source/Lib/CommonLib/Rom.cpp"),
) -> dict[str, int]:
    empirical = _read_formal_vectors(vec_logs, theta_values)
    rdo = _read_formal_rdo(cov_logs)
    theory_by_key: dict[exp42.GroupKey, np.ndarray] = {}
    lfnst_by_key: dict[exp42.GroupKey, np.ndarray] = {}
    lfnst8, lfnst4, _, _ = parse_rom_lfnst(rom_lfnst)
    for key in empirical:
        if (key.w, key.h) not in set(sizes):
            continue
        theta = theta_values[min(max(key.lat_bin, 0), len(theta_values) - 1)]
        theory_by_key[key] = theory_matrices_for(
            key.w, key.h, theta, transpose=key.transpose
        ).Sigma_x[: key.k, : key.k]
        source = lfnst4 if key.k == 16 else lfnst8
        mat = source[key.set_idx, :, :2, : key.k] if False else None
        # Use explicit stacking because source layout is [set][candidate][out][in].
        lfnst_by_key[key] = np.stack([source[key.set_idx, 0, :, : key.k], source[key.set_idx, 1, :, : key.k]])
    return exp42.write_formal_analysis_outputs(
        out_dir=out_dir,
        empirical_accs=empirical,
        theory_cov_by_key=theory_by_key,
        lfnst_by_key=lfnst_by_key,
        rdo_by_key=rdo,
        min_samples=min_samples,
        lambda_u=lambda_u,
    )
```

During implementation, delete the temporary `mat = ... if False else None` line before running tests. The final code must only contain:

```python
lfnst_by_key[key] = np.stack([source[key.set_idx, 0, :, : key.k], source[key.set_idx, 1, :, : key.k]])
```

- [ ] **Step 4: Add CLI flags**

Extend `main()` with:

```python
parser.add_argument("--formal-4-2", action="store_true", help="write formal Experiment 4.2 NCE/rank/top1/reliability metrics")
parser.add_argument("--cov-log", action="append", default=[], help="LardLfnstCovLog CSV path/glob. Repeatable.")
parser.add_argument("--lambda-u", type=float, default=0.0)
parser.add_argument("--rom-lfnst", type=Path, default=Path("source/Lib/CommonLib/Rom.cpp"))
```

After resolving `vec_logs`, add:

```python
if args.formal_4_2:
    cov_logs = _resolve_inputs(args.cov_log)
    if not cov_logs:
        raise SystemExit("--formal-4-2 requires --cov-log")
    formal_result = run_formal_experiment_4_2(
        vec_logs=vec_logs,
        cov_logs=cov_logs,
        out_dir=args.out_dir,
        sizes=sizes,
        theta_values=theta_values,
        min_samples=args.min_samples,
        write_figures=True,
        lambda_u=args.lambda_u,
        rom_lfnst=args.rom_lfnst,
    )
    print(f"4.2-formal groups={formal_result['groups']} top1_groups={formal_result['top1_groups']}")
    return
```

- [ ] **Step 5: Run runner tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_run_lfnst_covariance_model_validation -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add tools/lard_lfnst/run_lfnst_covariance_model_validation.py tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py
git commit -m "feat: integrate formal experiment 4.2 analysis"
```

## Task 5: Figures for Formal Outputs

**Files:**
- Modify: `tools/lard_lfnst/experiment_4_2_metrics.py`
- Modify: `tools/lard_lfnst/test_experiment_4_2_metrics.py`

- [ ] **Step 1: Add failing figure contract test**

Append:

```python
    def test_plot_formal_outputs_creates_required_figures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            cov = pd.DataFrame(
                [
                    {"QP": 32, "W": 4, "H": 4, "latBin": 0, "setIdx": 0, "transpose": 0, "K": 4, "Kz": 8, "NCE_full": 0.1, "NCE_off": 0.2, "samples": 10},
                    {"QP": 32, "W": 8, "H": 8, "latBin": 2, "setIdx": 0, "transpose": 0, "K": 48, "Kz": 8, "NCE_full": 0.3, "NCE_off": 0.4, "samples": 20},
                ]
            )
            merged = pd.DataFrame(
                [
                    {"G_max_resp_th": 1.0, "P_positive_gain": 0.2, "U_max_offplus_th": 0.5, "O_x_th": 0.1, "chi_diag_th": 0.9},
                    {"G_max_resp_th": 2.0, "P_positive_gain": 0.8, "U_max_offplus_th": 0.8, "O_x_th": 0.3, "chi_diag_th": 0.4},
                ]
            )
            rel = pd.DataFrame([{"bin": "Q1", "P_no_gain": 0.8}, {"bin": "Q2", "P_no_gain": 0.2}])
            m.plot_formal_outputs(out, cov, merged, rel)
            self.assertTrue((out / "fig_4_2_nce_by_size_lat.png").exists())
            self.assertTrue((out / "fig_4_2_response_vs_gain.png").exists())
            self.assertTrue((out / "fig_4_2_low_gain_reliability.png").exists())
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: FAIL because `plot_formal_outputs` is absent.

- [ ] **Step 3: Implement plotting helper**

Add imports:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
```

Add function:

```python
def plot_formal_outputs(out_dir: Path, cov_df: pd.DataFrame, merged_df: pd.DataFrame, reliability_df: pd.DataFrame) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.0, 3.8), constrained_layout=True)
    if not cov_df.empty:
        frame = cov_df.copy()
        frame["sizeId"] = frame["W"].astype(str) + "x" + frame["H"].astype(str)
        labels = []
        values = []
        for (size, lat), group in frame.groupby(["sizeId", "latBin"], sort=True):
            labels.append(f"{size}/L{lat}")
            values.append(float(group["NCE_off"].median()))
        ax.bar(np.arange(len(values)), values)
        ax.set_xticks(np.arange(len(labels)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("median NCE-off")
    ax.set_title("Experiment 4.2 covariance error")
    fig.savefig(out_dir / "fig_4_2_nce_by_size_lat.png", dpi=220)
    fig.savefig(out_dir / "fig_4_2_nce_by_size_lat.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.8), constrained_layout=True)
    if not merged_df.empty:
        ax.scatter(merged_df["G_max_resp_th"], merged_df["P_positive_gain"], s=22, alpha=0.75, label="G")
        ax.set_xlabel("theoretical G_max_resp")
        ax.set_ylabel("P(DeltaJmax > 0)")
    ax.grid(True, alpha=0.3)
    ax.set_title("Theory response vs real gain")
    fig.savefig(out_dir / "fig_4_2_response_vs_gain.png", dpi=220)
    fig.savefig(out_dir / "fig_4_2_response_vs_gain.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.6), constrained_layout=True)
    if not reliability_df.empty:
        ax.plot(np.arange(len(reliability_df)), reliability_df["P_no_gain"], marker="o")
        ax.set_xticks(np.arange(len(reliability_df)))
        ax.set_xticklabels(reliability_df["bin"].astype(str))
    ax.set_xlabel("S_low quantile")
    ax.set_ylabel("P(DeltaJmax <= 0)")
    ax.grid(True, alpha=0.3)
    ax.set_title("Low-gain reliability")
    fig.savefig(out_dir / "fig_4_2_low_gain_reliability.png", dpi=220)
    fig.savefig(out_dir / "fig_4_2_low_gain_reliability.pdf")
    plt.close(fig)
```

Call `plot_formal_outputs()` at the end of `write_formal_analysis_outputs()` after `merged` and reliability data are created. Store reliability in a variable before writing it:

```python
reliability = reliability_curve(merged)
reliability.to_csv(out_dir / "low_gain_reliability_curve.csv", index=False)
plot_formal_outputs(out_dir, cov_df, merged, reliability)
```

- [ ] **Step 4: Run figure tests**

Run:

```powershell
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add tools/lard_lfnst/experiment_4_2_metrics.py tools/lard_lfnst/test_experiment_4_2_metrics.py
git commit -m "feat: plot experiment 4.2 formal figures"
```

## Task 6: Documentation and Focused Verification

**Files:**
- Modify: `docs/lard_lfnst_covariance_model_validation_4_2.md`
- Test: focused unit tests

- [ ] **Step 1: Update experiment documentation**

Append a new section to `docs/lard_lfnst_covariance_model_validation_4_2.md`:

```markdown
## Formal 4.2 low-frequency covariance validation

The formal analysis reuses two existing logs:

- `LardLfnst2ndVecFile` for pre-LFNST, pre-quantization vectors `x00..x47`;
- `LardLfnstCovLog` for `J0/J1/J2`, `bestIdx`, and residual block statistics.

Run:

```powershell
python tools\lard_lfnst\run_lfnst_covariance_model_validation.py `
  --formal-4-2 `
  --out-dir lahtp_runs\covariance_model_validation_4_2_formal `
  --sizes 4,8,16 `
  --theta-values 0,30,60,75 `
  --min-samples 200 `
  --vec-log tools\lard_lfnst\empirical_mechanism_diag_20260624\AerialCity\QP*\empirical_lfnst_vec.csv `
  --cov-log path\to\LardLfnstCovLog.csv
```

Primary outputs:

- `covariance_group_metrics.csv`: `NCE_full`, `NCE_off`, covariance-rank Spearman;
- `response_group_metrics.csv`: empirical/theoretical `O_x`, `chi_diag`, `G_max_resp`, `U_max_off+`;
- `rdo_gain_group_metrics.csv`: `P(DeltaJmax > 0)` and mean gains;
- `top1_candidate_match.csv`: theory-vs-RDO candidate match on useful-gain groups;
- `low_gain_reliability_curve.csv`: `S_low` bins versus `P(DeltaJmax <= 0)`.
```

Remove mojibake only if it is touched in the edited section; do not rewrite the whole document in this task.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m unittest `
  tools.lard_lfnst.test_experiment_4_2_metrics `
  tools.lard_lfnst.test_run_lfnst_covariance_model_validation -v
```

Expected: all tests PASS.

- [ ] **Step 3: Run formal CLI smoke on synthetic test data**

Run the existing runner test indirectly by executing:

```powershell
python tools\lard_lfnst\run_lfnst_covariance_model_validation.py `
  --out-dir lahtp_runs\smoke_exp42_formal `
  --sizes 4 `
  --theta-values 0,60 `
  --skip-empirical
```

Expected: command exits 0 and legacy theory outputs are still produced. This confirms the new flags did not break the old path.

- [ ] **Step 4: Commit Task 6**

Run:

```powershell
git add docs/lard_lfnst_covariance_model_validation_4_2.md tools/lard_lfnst/experiment_4_2_metrics.py tools/lard_lfnst/run_lfnst_covariance_model_validation.py tools/lard_lfnst/test_experiment_4_2_metrics.py tools/lard_lfnst/test_run_lfnst_covariance_model_validation.py
git commit -m "docs: document formal experiment 4.2 analysis"
```

## Task 7: Final Verification

**Files:**
- Modify only if a verified defect is found.

- [ ] **Step 1: Run all focused tests**

Run:

```powershell
python -m unittest `
  tools.lard_lfnst.test_experiment_4_2_metrics `
  tools.lard_lfnst.test_run_lfnst_covariance_model_validation -v
```

Expected: all tests PASS.

- [ ] **Step 2: Check only intended files changed**

Run:

```powershell
git status --short
```

Expected: no unrelated new edits from the implementation tasks except repository pre-existing dirty files. The implementation files should already be committed task-by-task.

- [ ] **Step 3: Record final handoff**

Report:

```text
Implemented formal Experiment 4.2 offline analysis.
Focused tests passed:
python -m unittest tools.lard_lfnst.test_experiment_4_2_metrics tools.lard_lfnst.test_run_lfnst_covariance_model_validation -v
```

Do not claim formal experiment results until real `--vec-log` and `--cov-log` traces have been run.

## Plan Self-Review

- Spec coverage: canonical schema, empirical covariance, theoretical covariance, correlation conversion, `NCE_full`, `NCE_off`, covariance-rank Spearman, response metric Spearman, top-1 candidate match, real RDO gain relation, low-gain reliability curve, outputs, and tests are covered by Tasks 1--7.
- Placeholder scan: the plan contains no deferred implementation sections, no unspecified metrics, and no undefined output files.
- Type consistency: `GroupKey`, `VectorSample`, `RdoSample`, `CovAccumulator`, `write_formal_analysis_outputs`, and `run_formal_experiment_4_2` are introduced before they are consumed in later tasks.
- Scope check: the plan modifies only offline Python analysis/tests/docs and does not alter encoder behavior.
