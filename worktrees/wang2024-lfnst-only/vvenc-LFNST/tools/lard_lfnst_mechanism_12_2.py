#!/usr/bin/env python3
"""Controlled-stretch mechanism checks for LARD-LFNST section 12.2.

The script consumes one or more LARD-LFNST candidate trace CSV files.  It keeps
the RD labels fixed and applies synthetic horizontal stretch factors to the
recorded no-LFNST residual spectrum, so spectrum-side mechanisms can be checked
without changing content, QP, block partitioning, or intra mode.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np


STRETCH_FACTORS = [1.0, 1.15, 1.41, 2.00, 3.86, 5.00]
LAT_BUCKETS = [(0.0, 30.0, "[0,30)"), (30.0, 60.0, "[30,60)"), (60.0, 75.0, "[60,75)"), (75.0, 90.0001, "[75,90]")]
SIZE_ORDER = ["area_16", "area_32", "area_64", "area_256", "area_1024", "area_large", "area_large_elong"]


def ff(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def ii(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def valid_cost(x: float) -> bool:
    return math.isfinite(x) and abs(x) < 1.0e100


def lat_bucket(abs_lat: float) -> str:
    for lo, hi, name in LAT_BUCKETS:
        if lo <= abs_lat < hi:
            return name
    return "unknown"


def size_group(w: int, h: int) -> str:
    area = w * h
    mn = min(w, h)
    mx = max(w, h)
    if area <= 16:
        return "area_16"
    if area <= 32:
        return "area_32"
    if area <= 64:
        return "area_64"
    if area <= 256:
        return "area_256"
    if area <= 1024:
        return "area_1024"
    return "area_large_elong" if mx >= 4 * mn else "area_large"


def s_to_lat(s: float) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, 1.0 / s))))


class MeanAcc:
    def __init__(self) -> None:
        self.n = 0
        self.sum = defaultdict(float)
        self.count = defaultdict(int)

    def add(self, **vals: float) -> None:
        self.n += 1
        for k, v in vals.items():
            if math.isfinite(v):
                self.sum[k] += v
                self.count[k] += 1

    def mean(self, key: str) -> float:
        return self.sum[key] / self.count[key] if self.count[key] else math.nan


class CovAcc:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.n = 0
        self.sum = np.zeros(dim, dtype=np.float64)
        self.outer = np.zeros((dim, dim), dtype=np.float64)

    def add(self, vec: np.ndarray) -> None:
        if vec.size != self.dim or not np.all(np.isfinite(vec)):
            return
        self.n += 1
        self.sum += vec
        self.outer += np.outer(vec, vec)

    def eig_metrics(self) -> dict[str, float]:
        if self.n < 2:
            return {"Top1EigenRatio": math.nan, "Top4EigenRatio": math.nan, "EffectiveRank": math.nan}
        mean = self.sum / self.n
        cov = self.outer / self.n - np.outer(mean, mean)
        vals = np.linalg.eigvalsh(cov)
        vals = np.maximum(vals, 0.0)[::-1]
        total = float(vals.sum())
        if total <= 0.0:
            return {"Top1EigenRatio": math.nan, "Top4EigenRatio": math.nan, "EffectiveRank": math.nan}
        return {
            "Top1EigenRatio": float(vals[0] / total),
            "Top4EigenRatio": float(vals[:4].sum() / total),
            "EffectiveRank": float(total * total / max(float(np.dot(vals, vals)), 1.0e-30)),
        }


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def rankdata(vals: np.ndarray) -> np.ndarray:
    order = np.argsort(vals, kind="mergesort")
    ranks = np.empty(vals.size, dtype=np.float64)
    ranks[order] = np.arange(vals.size, dtype=np.float64)
    i = 0
    while i < vals.size:
        j = i + 1
        while j < vals.size and vals[order[j]] == vals[order[i]]:
            j += 1
        if j - i > 1:
            ranks[order[i:j]] = 0.5 * (i + j - 1)
        i = j
    return ranks


def corr(x_vals: list[float], y_vals: list[float]) -> tuple[float, float]:
    x = np.asarray(x_vals, dtype=np.float64)
    y = np.asarray(y_vals, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(y)
    x = x[ok]
    y = y[ok]
    if x.size < 3 or float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return math.nan, math.nan
    pearson = float(np.corrcoef(x, y)[0, 1])
    rx = rankdata(x)
    ry = rankdata(y)
    spearman = float(np.corrcoef(rx, ry)[0, 1]) if float(np.std(rx)) > 0.0 and float(np.std(ry)) > 0.0 else math.nan
    return pearson, spearman


def stretch_energy_grid(grid: np.ndarray, s: float) -> np.ndarray:
    out = np.zeros_like(grid)
    for v in range(grid.shape[0]):
        row = grid[v]
        for u in range(grid.shape[1]):
            src = u * s
            lo = int(math.floor(src))
            hi = lo + 1
            if lo >= grid.shape[1]:
                continue
            if hi >= grid.shape[1]:
                out[v, u] = row[lo]
            else:
                t = src - lo
                out[v, u] = (1.0 - t) * row[lo] + t * row[hi]
    return out


def spectrum_metrics(spec: list[float], spec_side: int, s: float) -> tuple[float, float, float, np.ndarray]:
    grid = np.asarray(spec, dtype=np.float64).reshape(8, 8)
    grid = stretch_energy_grid(grid, s)
    total = float(grid.sum())
    if total <= 0.0 or not math.isfinite(total):
        return math.nan, math.nan, math.nan, np.asarray([], dtype=np.float64)

    roi_mask = np.zeros((8, 8), dtype=bool)
    if spec_side == 4:
        roi_mask[:4, :4] = True
    else:
        roi_mask[:, :] = True
        roi_mask[4:, 4:] = False
    lf_mask = np.zeros((8, 8), dtype=bool)
    lf_mask[:2, :2] = True
    roi_vec = np.maximum(grid[roi_mask], 0.0)
    roi = float(roi_vec.sum())
    if roi <= 0.0:
        return 0.0, math.nan, math.nan, roi_vec
    e_lf = float(grid[lf_mask].sum())
    sum_sqrt = float(np.sqrt(roi_vec).sum())
    c_proxy = ((sum_sqrt * sum_sqrt) - roi) / max((roi_vec.size - 1) * roi, 1.0e-30)
    norm_roi_vec = roi_vec / roi
    return roi / total, e_lf / roi, max(0.0, min(1.0, c_proxy)), norm_roi_vec


def load_trace(paths: Iterable[Path], max_blocks: int | None) -> dict[tuple[int, int, int, int, int, int, int], dict[str, object]]:
    states: dict[tuple[int, int, int, int, int, int, int], dict[str, object]] = {}
    spec_cols = [f"spec{i:02d}" for i in range(64)]
    for path in paths:
        with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in spec_cols if c not in (reader.fieldnames or [])]
            if missing:
                raise RuntimeError(f"{path} does not contain spec00..spec63")
            has_nonzero = "nonZero" in (reader.fieldnames or [])
            has_last = "lastPos" in (reader.fieldnames or [])
            for row in reader:
                key = (ii(row, "poc"), ii(row, "x"), ii(row, "y"), ii(row, "w"), ii(row, "h"), ii(row, "qp"), ii(row, "intraMode"))
                if key not in states:
                    if max_blocks is not None and len(states) >= max_blocks:
                        continue
                    states[key] = {
                        "w": ii(row, "w"),
                        "h": ii(row, "h"),
                        "absLatDeg": ff(row, "absLatDeg"),
                        "sizeGroup": size_group(ii(row, "w"), ii(row, "h")),
                        "j": {},
                        "n": {},
                        "last": {},
                        "spec": None,
                        "specSide": ii(row, "specSide", 8),
                        "hasNonZeroField": has_nonzero,
                        "hasLastPosField": has_last,
                    }
                st = states[key]
                idx = ii(row, "lfnstIdx", -1)
                cost = ff(row, "cost")
                if valid_cost(cost):
                    best = st["j"]  # type: ignore[index]
                    if idx not in best or cost < best[idx]:
                        best[idx] = cost
                        st["n"][idx] = ii(row, "nonZero", ii(row, "numSig", -1))  # type: ignore[index]
                        st["last"][idx] = ii(row, "lastPos", -1)  # type: ignore[index]
                if st["spec"] is None and idx == 0 and ii(row, "mtsIdx") == 0:
                    st["spec"] = [ff(row, c, 0.0) for c in spec_cols]
                    st["specSide"] = ii(row, "specSide", 8)
    return states


def analyze(paths: list[Path], out_dir: Path, max_blocks: int | None) -> dict[str, object]:
    states = load_trace(paths, max_blocks)
    energy_by_s_size = defaultdict(MeanAcc)
    energy_by_lat_size = defaultdict(MeanAcc)
    lf_by_gain = defaultdict(MeanAcc)
    cproxy_pairs = defaultdict(lambda: ([], []))
    cproxy_bins = defaultdict(list)
    cov_by_s_size: dict[tuple[float, str, int], CovAcc] = {}
    delta_by_lat_size = defaultdict(MeanAcc)
    pref_by_lat_size = defaultdict(lambda: defaultdict(int))

    usable = 0
    missing_last = 0
    missing_nonzero = 0

    for st in states.values():
        j = st["j"]  # type: ignore[index]
        spec = st["spec"]
        if spec is None or 0 not in j or (1 not in j and 2 not in j):
            continue
        j0 = float(j[0])
        j1 = float(j.get(1, math.inf))
        j2 = float(j.get(2, math.inf))
        best_lfnst = min(j1, j2)
        if not valid_cost(best_lfnst):
            continue
        delta_j = j0 - best_lfnst
        gain_sign = "positive" if delta_j > 0.0 else "negative"
        lat = lat_bucket(float(st["absLatDeg"]))
        sg = str(st["sizeGroup"])
        n = st["n"]  # type: ignore[index]
        last = st["last"]  # type: ignore[index]
        has_n = bool(st["hasNonZeroField"]) and n.get(0, -1) >= 0 and (n.get(1, -1) >= 0 or n.get(2, -1) >= 0)
        has_l = bool(st["hasLastPosField"]) and last.get(0, -1) >= 0 and (last.get(1, -1) >= 0 or last.get(2, -1) >= 0)
        delta_n = n.get(0, -1) - min(n.get(1, 1 << 30), n.get(2, 1 << 30)) if has_n else math.nan
        delta_l = last.get(0, -1) - min(last.get(1, 1 << 30), last.get(2, 1 << 30)) if has_l else math.nan
        missing_nonzero += 0 if has_n else 1
        missing_last += 0 if has_l else 1

        acc = delta_by_lat_size[(lat, sg)]
        acc.add(DeltaJ=delta_j, PositiveGain=float(delta_j > 0.0), DeltaN=float(delta_n), DeltaLast=float(delta_l))
        if valid_cost(j1) and valid_cost(j2):
            pref = pref_by_lat_size[(lat, sg)]
            pref["Samples"] += 1
            pref["PositiveGainSamples"] += int(delta_j > 0.0)
            pref["Cand1Wins"] += int(j1 < j2)
            pref["Cand2Wins"] += int(j2 < j1)
            pref["Ties"] += int(j1 == j2)
            pref["Cand1PositiveWins"] += int(delta_j > 0.0 and j1 <= j2)
            pref["Cand2PositiveWins"] += int(delta_j > 0.0 and j2 < j1)

        for s in STRETCH_FACTORS:
            e_roi_total, e_lf_roi, c_proxy, roi_vec = spectrum_metrics(spec, int(st["specSide"]), s)
            energy_by_s_size[(s, sg)].add(E_ROI_over_E_total=e_roi_total, E_LF_over_E_ROI=e_lf_roi, C_proxy=c_proxy)
            if s == 1.0:
                energy_by_lat_size[(lat, sg)].add(E_ROI_over_E_total=e_roi_total, E_LF_over_E_ROI=e_lf_roi, C_proxy=c_proxy)
            lf_by_gain[(s, gain_sign)].add(E_LF_over_E_ROI=e_lf_roi, DeltaJ=delta_j)
            cproxy_pairs[s][0].append(c_proxy)
            cproxy_pairs[s][1].append(delta_j)
            cproxy_bins[s].append((c_proxy, delta_j))
            dim = int(roi_vec.size)
            ck = (s, sg, dim)
            if dim:
                cov_by_s_size.setdefault(ck, CovAcc(dim)).add(roi_vec)
        usable += 1

    energy_rows = []
    for (s, sg), acc in sorted(energy_by_s_size.items(), key=lambda kv: (kv[0][0], SIZE_ORDER.index(kv[0][1]) if kv[0][1] in SIZE_ORDER else 99)):
        energy_rows.append(
            {
                "StretchS": s,
                "EquivalentLatitudeDeg": s_to_lat(s),
                "BlockSizeGroup": sg,
                "Samples": acc.n,
                "Mean_E_ROI_over_E_total": acc.mean("E_ROI_over_E_total"),
                "Mean_E_LF_over_E_ROI": acc.mean("E_LF_over_E_ROI"),
                "Mean_C_proxy": acc.mean("C_proxy"),
            }
        )
    write_rows(out_dir / "table_12_2_stretch_energy_by_s_size.csv", energy_rows)

    lat_energy_rows = []
    for (lat, sg), acc in sorted(energy_by_lat_size.items()):
        lat_energy_rows.append(
            {
                "Latitude": lat,
                "BlockSizeGroup": sg,
                "Samples": acc.n,
                "Mean_E_ROI_over_E_total": acc.mean("E_ROI_over_E_total"),
                "Mean_E_LF_over_E_ROI": acc.mean("E_LF_over_E_ROI"),
                "Mean_C_proxy": acc.mean("C_proxy"),
            }
        )
    write_rows(out_dir / "table_12_2_energy_by_latitude_size.csv", lat_energy_rows)

    gain_rows = []
    for (s, sign), acc in sorted(lf_by_gain.items()):
        gain_rows.append(
            {
                "StretchS": s,
                "EquivalentLatitudeDeg": s_to_lat(s),
                "GainSign": sign,
                "Samples": acc.n,
                "Mean_E_LF_over_E_ROI": acc.mean("E_LF_over_E_ROI"),
                "MeanDeltaJ": acc.mean("DeltaJ"),
            }
        )
    write_rows(out_dir / "table_12_2_lf_roi_by_gain_sign.csv", gain_rows)

    cproxy_rows = []
    for s, (xs, ys) in sorted(cproxy_pairs.items()):
        p, sp = corr(xs, ys)
        cproxy_rows.append(
            {
                "StretchS": s,
                "EquivalentLatitudeDeg": s_to_lat(s),
                "Samples": len(xs),
                "Pearson_C_proxy_DeltaJ": p,
                "Spearman_C_proxy_DeltaJ": sp,
            }
        )
        arr = np.asarray(cproxy_bins[s], dtype=np.float64)
        if arr.size:
            qs = np.quantile(arr[:, 0], [0.0, 0.25, 0.5, 0.75, 1.0])
            for i in range(4):
                if i == 3:
                    m = (arr[:, 0] >= qs[i]) & (arr[:, 0] <= qs[i + 1])
                else:
                    m = (arr[:, 0] >= qs[i]) & (arr[:, 0] < qs[i + 1])
                vals = arr[m, 1]
                cproxy_rows.append(
                    {
                        "StretchS": s,
                        "EquivalentLatitudeDeg": s_to_lat(s),
                        "Samples": int(vals.size),
                        "Pearson_C_proxy_DeltaJ": math.nan,
                        "Spearman_C_proxy_DeltaJ": math.nan,
                        "C_proxy_bin": f"Q{i + 1}",
                        "C_proxy_lo": float(qs[i]),
                        "C_proxy_hi": float(qs[i + 1]),
                        "MeanDeltaJ": float(vals.mean()) if vals.size else math.nan,
                        "PositiveGainRatio": float((vals > 0.0).mean()) if vals.size else math.nan,
                    }
                )
    write_rows(out_dir / "table_12_2_cproxy_deltaJ.csv", cproxy_rows)

    cov_rows = []
    for (s, sg, dim), acc in sorted(cov_by_s_size.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        row = {
            "StretchS": s,
            "EquivalentLatitudeDeg": s_to_lat(s),
            "BlockSizeGroup": sg,
            "RoiDim": dim,
            "Samples": acc.n,
        }
        row.update(acc.eig_metrics())
        cov_rows.append(row)
    write_rows(out_dir / "table_12_2_roi_cov_eigen_by_s_size.csv", cov_rows)

    delta_rows = []
    for (lat, sg), acc in sorted(delta_by_lat_size.items()):
        delta_rows.append(
            {
                "Latitude": lat,
                "BlockSizeGroup": sg,
                "Samples": acc.n,
                "MeanDeltaJ": acc.mean("DeltaJ"),
                "PositiveGainRatio": acc.mean("PositiveGain"),
                "MeanDeltaN": acc.mean("DeltaN"),
                "MeanDeltaLast": acc.mean("DeltaLast"),
            }
        )
    write_rows(out_dir / "table_12_2_deltaN_deltaLast_by_latitude_size.csv", delta_rows)

    pref_rows = []
    for (lat, sg), d in sorted(pref_by_lat_size.items()):
        samples = d["Samples"]
        pos = d["PositiveGainSamples"]
        pref_rows.append(
            {
                "Latitude": lat,
                "BlockSizeGroup": sg,
                "SamplesWithBothCandidates": samples,
                "PositiveGainSamples": pos,
                "Cand1WinRatioAll": d["Cand1Wins"] / samples if samples else math.nan,
                "Cand2WinRatioAll": d["Cand2Wins"] / samples if samples else math.nan,
                "TieRatioAll": d["Ties"] / samples if samples else math.nan,
                "Cand1PreferencePositiveGain": d["Cand1PositiveWins"] / pos if pos else math.nan,
                "Cand2PreferencePositiveGain": d["Cand2PositiveWins"] / pos if pos else math.nan,
            }
        )
    write_rows(out_dir / "table_12_2_candidate_preference_by_latitude_size.csv", pref_rows)

    report = [
        "# Section 12.2 Controlled Stretch Mechanism Checks",
        "",
        f"Input trace files: `{len(paths)}`",
        f"Candidate groups loaded: `{len(states)}`",
        f"Usable groups with `J0` and at least one LFNST candidate: `{usable}`",
        f"Stretch factors: `{', '.join(f'{s:g}' for s in STRETCH_FACTORS)}`",
        "",
        "Generated tables:",
        "",
        "- `table_12_2_stretch_energy_by_s_size.csv`: `E_ROI/E_total`, `E_LF/E_ROI`, and `C_proxy` versus controlled stretch and block size.",
        "- `table_12_2_energy_by_latitude_size.csv`: the same spectrum metrics versus measured latitude and block size.",
        "- `table_12_2_lf_roi_by_gain_sign.csv`: `E_LF/E_ROI` split by positive/negative LFNST gain.",
        "- `table_12_2_cproxy_deltaJ.csv`: correlation and quartile trend between `C_proxy` and `Delta J`.",
        "- `table_12_2_roi_cov_eigen_by_s_size.csv`: ROI covariance eigenvalue concentration.",
        "- `table_12_2_deltaN_deltaLast_by_latitude_size.csv`: `DeltaN=N0-min(N1,N2)` and `DeltaL=L0-min(L1,L2)` versus latitude and block size.",
        "- `table_12_2_candidate_preference_by_latitude_size.csv`: candidate 1/2 preference versus latitude and block size.",
        "",
        "`C_proxy` is an energy-only off-diagonal proxy: it is zero when ROI energy is concentrated in one coefficient and approaches one when ROI energy is spread across many coefficients. True signed covariance requires coefficient-vector tracing, not just `spec00..spec63` energy tracing.",
    ]
    if missing_nonzero:
        report.append("")
        report.append(f"Warning: `{missing_nonzero}` usable groups did not have the new `nonZero` trace field; rerun tracing with the updated encoder to fill `DeltaN`.")
    if missing_last:
        report.append("")
        report.append(f"Warning: `{missing_last}` usable groups did not have `lastPos`; rerun tracing with the updated encoder to fill `DeltaL`.")
    (out_dir / "mechanism_12_2_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    return {"groups": len(states), "usable": usable, "missingNonZero": missing_nonzero, "missingLastPos": missing_last}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_csv", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--max-blocks", type=int, help="optional cap for smoke tests on huge traces")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    meta = analyze(args.trace_csv, args.out_dir, args.max_blocks)
    print(args.out_dir / "mechanism_12_2_report.md")
    print(meta)


if __name__ == "__main__":
    main()
