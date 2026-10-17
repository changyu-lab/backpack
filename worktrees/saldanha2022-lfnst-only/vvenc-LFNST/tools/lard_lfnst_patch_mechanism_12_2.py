#!/usr/bin/env python3
"""Analyze SJTU patch-level controlled-stretch LFNST traces for section 12.2."""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np


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


def s_to_lat(s: float) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, 1.0 / s))))


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


class MeanAcc:
    def __init__(self) -> None:
        self.rows = 0
        self.sum = defaultdict(float)
        self.count = defaultdict(int)

    def add(self, **vals: float) -> None:
        self.rows += 1
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
        norm = float(np.linalg.norm(vec))
        if norm <= 0.0:
            return
        v = vec / norm
        self.n += 1
        self.sum += v
        self.outer += np.outer(v, v)

    def covariance(self) -> np.ndarray | None:
        if self.n < 2:
            return None
        mean = self.sum / self.n
        return self.outer / self.n - np.outer(mean, mean)

    def metrics(self) -> dict[str, float]:
        cov = self.covariance()
        if cov is None:
            return {"C_off": math.nan, "Lambda1Ratio": math.nan, "Lambda4Ratio": math.nan, "EffectiveRank": math.nan}
        diag = float(np.trace(cov))
        off = float(np.sum(np.abs(cov)) - np.sum(np.abs(np.diag(cov))))
        vals = np.maximum(np.linalg.eigvalsh(cov), 0.0)[::-1]
        total = float(vals.sum())
        return {
            "C_off": off / max(abs(diag), 1.0e-30),
            "Lambda1Ratio": float(vals[0] / total) if total > 0.0 else math.nan,
            "Lambda4Ratio": float(vals[:4].sum() / total) if total > 0.0 else math.nan,
            "EffectiveRank": float(total * total / max(float(np.dot(vals, vals)), 1.0e-30)) if total > 0.0 else math.nan,
        }


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    spearman = float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])
    return pearson, spearman


def parse_case(path: Path) -> tuple[str, float, int]:
    name = path.parent.name
    m = re.search(r"(train|validation)_s([0-9p.]+)_QP(\d+)", name, flags=re.IGNORECASE)
    if not m:
        name = path.stem
        m = re.search(r"(train|validation)_s([0-9p.]+)_qp(\d+)$", name, flags=re.IGNORECASE)
    if not m:
        raise RuntimeError(f"trace case must look like train_s1p15_QP32/trace.csv or train_s1p15_qp32.csv: {path}")
    split = m.group(1).lower()
    s = float(m.group(2).replace("p", "."))
    qp = int(m.group(3))
    return split, s, qp


def load_manifests(manifest_dir: Path) -> dict[str, dict[int, dict[str, str]]]:
    out: dict[str, dict[int, dict[str, str]]] = {}
    for split in ("train", "validation"):
        path = manifest_dir / f"sjtu_{split}_patch256_manifest.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            out[split] = {int(r["patchIndex"]): r for r in csv.DictReader(fh)}
    return out


def patch_index_for_block(row: dict[str, str], patch: int = 128) -> int:
    poc = ii(row, "poc")
    x_center = ii(row, "x") + 0.5 * ii(row, "w")
    y_center = ii(row, "y") + 0.5 * ii(row, "h")
    tile_x = min(3, max(0, int(x_center // patch)))
    tile_y = min(3, max(0, int(y_center // patch)))
    return poc * 16 + tile_y * 4 + tile_x


def spectrum_metrics(spec: list[float], spec_side: int) -> tuple[float, float]:
    grid = np.asarray(spec, dtype=np.float64).reshape(8, 8)
    total = float(grid.sum())
    if total <= 0.0 or not math.isfinite(total):
        return math.nan, math.nan
    roi_mask = np.zeros((8, 8), dtype=bool)
    if spec_side == 4:
        roi_mask[:4, :4] = True
    else:
        roi_mask[:, :] = True
        roi_mask[4:, 4:] = False
    lf_mask = np.zeros((8, 8), dtype=bool)
    lf_mask[:2, :2] = True
    roi = float(grid[roi_mask].sum())
    return roi / total, float(grid[lf_mask].sum()) / roi if roi > 0.0 else math.nan


def c_proxy_from_roi(vec: np.ndarray) -> float:
    e = vec.astype(np.float64) ** 2
    total = float(e.sum())
    if total <= 0.0 or vec.size < 2:
        return math.nan
    return float(((np.sqrt(e).sum() ** 2) - total) / ((vec.size - 1) * total))


def load_trace_groups(path: Path, split: str, s: float, qp: int, manifest: dict[int, dict[str, str]], max_blocks: int | None) -> list[dict[str, object]]:
    spec_cols = [f"spec{i:02d}" for i in range(64)]
    roi_cols = [f"roiQ{i:02d}" for i in range(48)]
    groups: dict[tuple[int, int, int, int, int, int, int], dict[str, object]] = {}
    with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
        reader = csv.DictReader(fh)
        fields = set(reader.fieldnames or [])
        missing = [c for c in spec_cols + roi_cols + ["nonZero", "lastPos", "roiDim"] if c not in fields]
        if missing:
            raise RuntimeError(f"{path} missing required 12.2 trace fields: {missing[:8]}")
        for row in reader:
            key = (ii(row, "poc"), ii(row, "x"), ii(row, "y"), ii(row, "w"), ii(row, "h"), ii(row, "qp"), ii(row, "intraMode"))
            if key not in groups:
                if max_blocks is not None and len(groups) >= max_blocks:
                    continue
                pidx = patch_index_for_block(row)
                src = manifest.get(pidx)
                if src is None:
                    continue
                groups[key] = {
                    "Split": split,
                    "StretchS": s,
                    "EquivalentLatitudeDeg": s_to_lat(s),
                    "QP": qp,
                    "SourceLatitudeDeg": ff(src, "sourceLatitudeDeg"),
                    "LatitudeBucket": src.get("latitudeBucket", "unknown"),
                    "BlockSizeGroup": size_group(ii(row, "w"), ii(row, "h")),
                    "j": {},
                    "n": {},
                    "last": {},
                    "spec": None,
                    "specSide": ii(row, "specSide", 8),
                    "roi": None,
                }
            st = groups[key]
            idx = ii(row, "lfnstIdx", -1)
            cost = ff(row, "cost")
            if valid_cost(cost):
                best = st["j"]  # type: ignore[index]
                if idx not in best or cost < best[idx]:
                    best[idx] = cost
                    st["n"][idx] = ii(row, "nonZero", -1)  # type: ignore[index]
                    st["last"][idx] = ii(row, "lastPos", -1)  # type: ignore[index]
            if st["spec"] is None and idx == 0 and ii(row, "mtsIdx") == 0:
                st["spec"] = [ff(row, c, 0.0) for c in spec_cols]
                st["specSide"] = ii(row, "specSide", 8)
            if st["roi"] is None and ii(row, "roiDim") > 0:
                dim = min(ii(row, "roiDim"), 48)
                st["roi"] = np.asarray([ff(row, c, 0.0) for c in roi_cols[:dim]], dtype=np.float64)
    return list(groups.values())


def analyze(run_root: Path, manifest_dir: Path, out_dir: Path, max_blocks_per_trace: int | None) -> dict[str, object]:
    manifests = load_manifests(manifest_dir)
    trace_dir = run_root / "traces" if (run_root / "traces").is_dir() else run_root
    trace_files = sorted(trace_dir.glob("*_s*_qp*.csv"))
    trace_files = [p for p in trace_files if not p.name.endswith(".final.csv") and p.stat().st_size > 0]
    if not trace_files:
        trace_files = sorted(run_root.glob("*_s*_QP*/trace.csv"))
    if not trace_files:
        raise RuntimeError(f"no trace.csv files found under {run_root}")

    energy = defaultdict(MeanAcc)
    lf_gain = defaultdict(MeanAcc)
    delta = defaultdict(MeanAcc)
    pref = defaultdict(lambda: defaultdict(int))
    cov = {}
    cproxy_pairs = defaultdict(lambda: ([], []))
    coff_group_delta = defaultdict(lambda: ([], []))
    block_count = usable = 0

    for trace in trace_files:
        split, s, qp = parse_case(trace)
        if split not in manifests:
            raise RuntimeError(f"missing manifest for split {split}")
        groups = load_trace_groups(trace, split, s, qp, manifests[split], max_blocks_per_trace)
        block_count += len(groups)
        for st in groups:
            j = st["j"]  # type: ignore[index]
            spec = st["spec"]
            roi = st["roi"]
            if spec is None or roi is None or 0 not in j or (1 not in j and 2 not in j):
                continue
            j0 = float(j[0])
            j1 = float(j.get(1, math.inf))
            j2 = float(j.get(2, math.inf))
            best_lfnst = min(j1, j2)
            if not valid_cost(j0) or not valid_cost(best_lfnst):
                continue
            usable += 1
            delta_j = j0 - best_lfnst
            eroi, elf = spectrum_metrics(spec, int(st["specSide"]))
            cproxy = c_proxy_from_roi(roi)
            n = st["n"]  # type: ignore[index]
            last = st["last"]  # type: ignore[index]
            delta_n = n.get(0, -1) - min(n.get(1, 1 << 30), n.get(2, 1 << 30)) if n.get(0, -1) >= 0 and (n.get(1, -1) >= 0 or n.get(2, -1) >= 0) else math.nan
            delta_l = last.get(0, -1) - min(last.get(1, 1 << 30), last.get(2, 1 << 30)) if last.get(0, -1) >= 0 and (last.get(1, -1) >= 0 or last.get(2, -1) >= 0) else math.nan
            key = (st["Split"], st["StretchS"], st["EquivalentLatitudeDeg"], st["QP"], st["LatitudeBucket"], st["BlockSizeGroup"])
            energy[key].add(E_ROI_over_E_total=eroi, E_LF_over_E_ROI=elf, C_proxy=cproxy, DeltaJ=delta_j, PositiveGain=float(delta_j > 0.0))
            lf_gain[(st["Split"], st["StretchS"], st["EquivalentLatitudeDeg"], st["QP"], "positive" if delta_j > 0.0 else "negative")].add(E_LF_over_E_ROI=elf, DeltaJ=delta_j)
            delta[key].add(DeltaJ=delta_j, PositiveGain=float(delta_j > 0.0), DeltaN=delta_n, DeltaLast=delta_l)
            cproxy_pairs[(st["Split"], st["StretchS"], st["QP"])][0].append(cproxy)
            cproxy_pairs[(st["Split"], st["StretchS"], st["QP"])][1].append(delta_j)
            ckey = (st["Split"], st["StretchS"], st["EquivalentLatitudeDeg"], st["QP"], st["LatitudeBucket"], st["BlockSizeGroup"], int(roi.size))
            cov.setdefault(ckey, CovAcc(int(roi.size))).add(roi)
            if valid_cost(j1) and valid_cost(j2):
                p = pref[key]
                p["SamplesWithBothCandidates"] += 1
                p["PositiveGainSamples"] += int(delta_j > 0.0)
                p["Cand1Wins"] += int(j1 < j2)
                p["Cand2Wins"] += int(j2 < j1)
                p["Ties"] += int(j1 == j2)
                p["Cand1PositiveWins"] += int(delta_j > 0.0 and j1 <= j2)
                p["Cand2PositiveWins"] += int(delta_j > 0.0 and j2 < j1)

    energy_rows = []
    for key, acc in sorted(energy.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][3], kv[0][4], SIZE_ORDER.index(kv[0][5]) if kv[0][5] in SIZE_ORDER else 99)):
        split, s, eq_lat, qp, lat, sg = key
        energy_rows.append(
            {
                "Split": split,
                "StretchS": s,
                "EquivalentLatitudeDeg": eq_lat,
                "QP": qp,
                "LatitudeBucket": lat,
                "BlockSizeGroup": sg,
                "Samples": acc.rows,
                "Mean_E_ROI_over_E_total": acc.mean("E_ROI_over_E_total"),
                "Mean_E_LF_over_E_ROI": acc.mean("E_LF_over_E_ROI"),
                "Mean_C_proxy": acc.mean("C_proxy"),
                "MeanDeltaJ": acc.mean("DeltaJ"),
                "PositiveGainRatio": acc.mean("PositiveGain"),
            }
        )
    write_rows(out_dir / "table_12_2_energy_by_stretch_lat_size.csv", energy_rows)

    gain_rows = []
    for key, acc in sorted(lf_gain.items()):
        split, s, eq_lat, qp, sign = key
        gain_rows.append(
            {
                "Split": split,
                "StretchS": s,
                "EquivalentLatitudeDeg": eq_lat,
                "QP": qp,
                "GainSign": sign,
                "Samples": acc.rows,
                "Mean_E_LF_over_E_ROI": acc.mean("E_LF_over_E_ROI"),
                "MeanDeltaJ": acc.mean("DeltaJ"),
            }
        )
    write_rows(out_dir / "table_12_2_lf_roi_by_gain_sign.csv", gain_rows)

    cov_rows = []
    for key, acc in sorted(cov.items()):
        split, s, eq_lat, qp, lat, sg, dim = key
        row = {
            "Split": split,
            "StretchS": s,
            "EquivalentLatitudeDeg": eq_lat,
            "QP": qp,
            "LatitudeBucket": lat,
            "BlockSizeGroup": sg,
            "RoiDim": dim,
            "Samples": acc.n,
        }
        row.update(acc.metrics())
        cov_rows.append(row)
        dacc = delta.get((split, s, eq_lat, qp, lat, sg))
        if dacc is not None:
            coff_group_delta[(split, s, qp)][0].append(row["C_off"])
            coff_group_delta[(split, s, qp)][1].append(dacc.mean("DeltaJ"))
    write_rows(out_dir / "table_12_2_roi_cov_eigen.csv", cov_rows)

    corr_rows = []
    for key, (xs, ys) in sorted(cproxy_pairs.items()):
        p, sp = corr(xs, ys)
        corr_rows.append({"Metric": "per_block_C_proxy_vs_DeltaJ", "Split": key[0], "StretchS": key[1], "QP": key[2], "Samples": len(xs), "Pearson": p, "Spearman": sp})
        arr = np.asarray(list(zip(xs, ys)), dtype=np.float64)
        if arr.size:
            arr = arr[np.isfinite(arr[:, 0]) & np.isfinite(arr[:, 1])]
        if arr.size:
            qs = np.quantile(arr[:, 0], [0.0, 0.25, 0.5, 0.75, 1.0])
            for i in range(4):
                m = (arr[:, 0] >= qs[i]) & (arr[:, 0] <= qs[i + 1] if i == 3 else arr[:, 0] < qs[i + 1])
                vals = arr[m, 1]
                corr_rows.append(
                    {
                        "Metric": "C_proxy_quartile",
                        "Split": key[0],
                        "StretchS": key[1],
                        "QP": key[2],
                        "C_proxy_bin": f"Q{i + 1}",
                        "Samples": int(vals.size),
                        "C_proxy_lo": float(qs[i]),
                        "C_proxy_hi": float(qs[i + 1]),
                        "MeanDeltaJ": float(vals.mean()) if vals.size else math.nan,
                        "PositiveGainRatio": float((vals > 0.0).mean()) if vals.size else math.nan,
                    }
                )
    for key, (xs, ys) in sorted(coff_group_delta.items()):
        p, sp = corr(xs, ys)
        corr_rows.append({"Metric": "group_C_off_vs_MeanDeltaJ", "Split": key[0], "StretchS": key[1], "QP": key[2], "Samples": len(xs), "Pearson": p, "Spearman": sp})
    write_rows(out_dir / "table_12_2_correlation_deltaJ.csv", corr_rows)

    delta_rows = []
    for key, acc in sorted(delta.items()):
        split, s, eq_lat, qp, lat, sg = key
        delta_rows.append(
            {
                "Split": split,
                "StretchS": s,
                "EquivalentLatitudeDeg": eq_lat,
                "QP": qp,
                "LatitudeBucket": lat,
                "BlockSizeGroup": sg,
                "Samples": acc.rows,
                "MeanDeltaJ": acc.mean("DeltaJ"),
                "PositiveGainRatio": acc.mean("PositiveGain"),
                "MeanDeltaN": acc.mean("DeltaN"),
                "MeanDeltaLast": acc.mean("DeltaLast"),
            }
        )
    write_rows(out_dir / "table_12_2_deltaN_deltaL.csv", delta_rows)

    pref_rows = []
    for key, d in sorted(pref.items()):
        split, s, eq_lat, qp, lat, sg = key
        n = d["SamplesWithBothCandidates"]
        pos = d["PositiveGainSamples"]
        pref_rows.append(
            {
                "Split": split,
                "StretchS": s,
                "EquivalentLatitudeDeg": eq_lat,
                "QP": qp,
                "LatitudeBucket": lat,
                "BlockSizeGroup": sg,
                "SamplesWithBothCandidates": n,
                "PositiveGainSamples": pos,
                "Cand1WinRatioAll": d["Cand1Wins"] / n if n else math.nan,
                "Cand2WinRatioAll": d["Cand2Wins"] / n if n else math.nan,
                "TieRatioAll": d["Ties"] / n if n else math.nan,
                "Cand1PreferencePositiveGain": d["Cand1PositiveWins"] / pos if pos else math.nan,
                "Cand2PreferencePositiveGain": d["Cand2PositiveWins"] / pos if pos else math.nan,
            }
        )
    write_rows(out_dir / "table_12_2_candidate_preference.csv", pref_rows)

    report = [
        "# Section 12.2 SJTU Patch Controlled-Stretch Mechanism Experiment",
        "",
        f"Trace files: `{len(trace_files)}`",
        f"Block groups loaded: `{block_count}`",
        f"Usable groups with spectrum, signed ROI, J0, and at least one LFNST candidate: `{usable}`",
        "",
        "This is a patch-level controlled sequence experiment. It is intended for mechanism validation, not as a full ERP coding-performance result.",
        "",
        "Generated tables:",
        "",
        "- `table_12_2_energy_by_stretch_lat_size.csv`",
        "- `table_12_2_lf_roi_by_gain_sign.csv`",
        "- `table_12_2_correlation_deltaJ.csv`",
        "- `table_12_2_roi_cov_eigen.csv`",
        "- `table_12_2_deltaN_deltaL.csv`",
        "- `table_12_2_candidate_preference.csv`",
    ]
    (out_dir / "mechanism_12_2_patch_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"traces": len(trace_files), "groups": block_count, "usable": usable}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, default=Path(r"lahtp_runs\sjtu_patch_stretch_12_2\encodes"))
    ap.add_argument("--manifest-dir", type=Path, default=Path(r"lahtp_runs\sjtu_patch_stretch_12_2\manifests"))
    ap.add_argument("--out-dir", type=Path, default=Path(r"lahtp_runs\sjtu_patch_stretch_12_2\analysis"))
    ap.add_argument("--max-blocks-per-trace", type=int)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(analyze(args.run_root, args.manifest_dir, args.out_dir, args.max_blocks_per_trace))


if __name__ == "__main__":
    main()
