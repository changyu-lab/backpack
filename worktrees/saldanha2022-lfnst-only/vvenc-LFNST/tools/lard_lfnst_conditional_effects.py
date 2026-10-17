#!/usr/bin/env python3
"""Conditional-effect experiments for LFNST latitude/size behavior.

The script uses existing full-RDO `blocks.csv` files and generates:
  2.1 raw latitude behavior;
  2.2 discrete stratified slopes;
  2.3 marginal standardization;
  2.4 weighted logistic model comparison;
  2.5 matched low/high latitude comparison.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2
from scipy.stats import norm
from scipy.stats import t as student_t
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neighbors import NearestNeighbors


LAT_BUCKETS = [(0.0, 30.0, "[0,30)"), (30.0, 60.0, "[30,60)"), (60.0, 75.0, "[60,75)"), (75.0, 90.0001, "[75,90]")]
LAT_ORDER = [b for _, _, b in LAT_BUCKETS]
LAT_MID = {"[0,30)": 15.0, "[30,60)": 45.0, "[60,75)": 67.5, "[75,90]": 82.5}
SIZE_ORDER = ["area_16", "area_32", "area_64", "area_256", "area_1024", "area_large", "area_large_elong"]
MODE_ORDER = ["planar", "dc", "ang_02_17", "ang_18_34", "ang_35_50", "ang_51_66"]
LFNST_LUT = [
    0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
]


def qp_from_path(path: Path) -> int:
    m = re.search(r"QP(\d+)", str(path), flags=re.IGNORECASE)
    return int(m.group(1)) if m else -1


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


def size_class(size: str) -> str:
    if size == "area_16":
        return "small"
    if size in {"area_32", "area_64", "area_256"}:
        return "medium"
    if size == "area_1024":
        return "large"
    return "very_large"


def mode_group(mode: int) -> str:
    if mode == 0:
        return "planar"
    if mode == 1:
        return "dc"
    if mode <= 17:
        return "ang_02_17"
    if mode <= 34:
        return "ang_18_34"
    if mode <= 50:
        return "ang_35_50"
    return "ang_51_66"


def lfnst_set(mode: int) -> int:
    return LFNST_LUT[mode] if 0 <= mode < len(LFNST_LUT) else -1


def bb(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).lower() in {"1", "true", "yes"}


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


def ratio(a: float, b: float) -> float:
    return a / b if b else math.nan


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def finite_delta(row: dict[str, str]) -> float:
    delta = ff(row, "deltaBestLfnst")
    if math.isfinite(delta):
        return delta
    j0, j1, j2 = ff(row, "j0"), ff(row, "j1"), ff(row, "j2")
    vals = [v for v in (j1, j2) if math.isfinite(v) and abs(v) < 1.0e100]
    if math.isfinite(j0) and vals:
        return j0 - min(vals)
    return math.nan


@dataclass
class Acc:
    waste_n: int = 0
    waste: int = 0
    gain_n: int = 0
    gain: int = 0
    sum_delta: float = 0.0

    def add(self, wasted: bool, delta: float) -> None:
        self.waste_n += 1
        self.waste += int(wasted)
        if math.isfinite(delta):
            self.gain_n += 1
            self.gain += int(delta > 0.0)
            if abs(delta) < 1.0e100:
                self.sum_delta += delta


def scan_counts(block_root: Path) -> tuple[dict, dict, dict, dict, int]:
    by_lat = defaultdict(Acc)
    by_cell_lat = defaultdict(Acc)
    by_cell = defaultdict(Acc)
    by_lat_size = defaultdict(Acc)
    rows = 0
    for path in sorted(block_root.glob("*/blocks.csv")):
        qp = qp_from_path(path)
        with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
            for row in csv.DictReader(fh):
                if not bb(row, "hasLfnst"):
                    continue
                rows += 1
                lat = lat_bucket(ff(row, "absLatDeg"))
                mode = ii(row, "intraMode")
                size = size_group(ii(row, "w"), ii(row, "h"))
                cell = (qp, size, mode_group(mode), lfnst_set(mode))
                delta = finite_delta(row)
                wasted = bb(row, "oracleSkip") or ii(row, "bestIdx") == 0
                by_lat[lat].add(wasted, delta)
                by_cell_lat[cell + (lat,)].add(wasted, delta)
                by_cell[cell].add(wasted, delta)
                by_lat_size[(lat, size)].add(wasted, delta)
    return by_lat, by_cell_lat, by_cell, by_lat_size, rows


def experiment_raw(block_root: Path, out_dir: Path) -> tuple[dict, dict, dict, dict]:
    by_lat, by_cell_lat, by_cell, by_lat_size, rows_scanned = scan_counts(block_root)
    rows = []
    for lat in LAT_ORDER:
        a = by_lat[lat]
        rows.append(
            {
                "Latitude": lat,
                "LFNST_RDO_tested_samples": a.waste_n,
                "Wasted_RDO_samples": a.waste,
                "P_waste": ratio(a.waste, a.waste_n),
                "DeltaJ_valid_samples": a.gain_n,
                "Positive_gain_samples": a.gain,
                "P_gain": ratio(a.gain, a.gain_n),
                "Mean_DeltaJ": ratio(a.sum_delta, a.gain_n),
            }
        )
    write_rows(out_dir / "table_raw_lfnst_behavior_by_latitude.csv", rows)

    x = np.arange(len(LAT_ORDER))
    fig, ax = plt.subplots(figsize=(5.8, 3.5))
    ax.plot(x, [r["P_waste"] for r in rows], marker="o")
    ax.set_xticks(x)
    ax.set_xticklabels(LAT_ORDER)
    ax.set_ylabel("P_waste")
    ax.grid(True, axis="y", alpha=0.35)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_raw_wasted_rdo_by_latitude.png", dpi=240)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.8, 3.5))
    ax.plot(x, [r["P_gain"] for r in rows], marker="o")
    ax.set_xticks(x)
    ax.set_xticklabels(LAT_ORDER)
    ax.set_ylabel("P_gain")
    ax.grid(True, axis="y", alpha=0.35)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_raw_positive_gain_by_latitude.png", dpi=240)
    plt.close(fig)

    # Boxplot needs delta samples; use a bounded streaming reservoir per bucket.
    rng = np.random.default_rng(20260524)
    reservoir: dict[str, list[float]] = {lat: [] for lat in LAT_ORDER}
    seen = defaultdict(int)
    max_keep = 120000
    for path in sorted(block_root.glob("*/blocks.csv")):
        with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
            for row in csv.DictReader(fh):
                if not bb(row, "hasLfnst"):
                    continue
                delta = finite_delta(row)
                if not math.isfinite(delta):
                    continue
                lat = lat_bucket(ff(row, "absLatDeg"))
                seen[lat] += 1
                clipped = float(np.clip(delta, -2.0e7, 2.0e7))
                if len(reservoir[lat]) < max_keep:
                    reservoir[lat].append(clipped)
                else:
                    j = int(rng.integers(0, seen[lat]))
                    if j < max_keep:
                        reservoir[lat][j] = clipped
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.boxplot([reservoir[lat] for lat in LAT_ORDER], labels=LAT_ORDER, showfliers=False)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_ylabel("DeltaJ_LFNST (clipped for display)")
    ax.grid(True, axis="y", alpha=0.35)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_deltaJ_distribution_by_latitude.png", dpi=240)
    plt.close(fig)

    return by_lat, by_cell_lat, by_cell, by_lat_size


def experiment_stratified(by_cell_lat: dict, out_dir: Path, n_min: int) -> pd.DataFrame:
    rows = []
    cell_rows = []
    cells = sorted({k[:4] for k in by_cell_lat})
    for cell in cells:
        qp, size, mode, lset = cell
        lat_points = []
        for lat_idx, lat in enumerate(LAT_ORDER, start=1):
            a = by_cell_lat.get(cell + (lat,), Acc())
            if a.gain_n >= n_min:
                lat_points.append((lat_idx, LAT_MID[lat], a))
            cell_rows.append(
                {
                    "QP": qp,
                    "BlockSizeGroup": size,
                    "SizeClass": size_class(size),
                    "IntraModeGroup": mode,
                    "LFNSTSet": lset,
                    "Latitude": lat,
                    "LFNST_RDO_tested_samples": a.waste_n,
                    "P_waste": ratio(a.waste, a.waste_n),
                    "DeltaJ_valid_samples": a.gain_n,
                    "P_gain": ratio(a.gain, a.gain_n),
                    "Mean_DeltaJ": ratio(a.sum_delta, a.gain_n),
                }
            )
        if len(lat_points) >= 3:
            x = np.asarray([p[1] for p in lat_points], dtype=np.float64)
            y_gain = np.asarray([ratio(p[2].gain, p[2].gain_n) for p in lat_points], dtype=np.float64)
            y_waste = np.asarray([ratio(p[2].waste, p[2].waste_n) for p in lat_points], dtype=np.float64)
            w = np.asarray([p[2].gain_n for p in lat_points], dtype=np.float64)
            slope_gain, intercept_gain = np.polyfit(x, y_gain, 1, w=np.sqrt(w))
            slope_waste, intercept_waste = np.polyfit(x, y_waste, 1, w=np.sqrt(w))
            rows.append(
                {
                    "QP": qp,
                    "BlockSizeGroup": size,
                    "SizeClass": size_class(size),
                    "IntraModeGroup": mode,
                    "LFNSTSet": lset,
                    "ValidLatitudeBuckets": len(lat_points),
                    "TotalValidSamples": int(w.sum()),
                    "GainSlope_per_degree": slope_gain,
                    "GainSlope_per_bucket_approx": slope_gain * 22.5,
                    "WasteSlope_per_degree": slope_waste,
                    "WasteSlope_per_bucket_approx": slope_waste * 22.5,
                    "GainSlopePositive": int(slope_gain > 0.0),
                    "WasteSlopeNegative": int(slope_waste < 0.0),
                }
            )
    write_rows(out_dir / "table_stratified_gain_by_lat_qp_size_mode_set.csv", cell_rows)
    write_rows(out_dir / "table_cellwise_latitude_slope.csv", rows)

    df = pd.DataFrame(rows)
    if not df.empty:
        fig, ax = plt.subplots(figsize=(6.0, 3.5))
        ax.hist(df["GainSlope_per_bucket_approx"], bins=35, color="#4C78A8", alpha=0.85)
        ax.axvline(0.0, color="black", linewidth=0.9)
        ax.set_xlabel("Cell-wise P_gain slope per latitude bucket")
        ax.set_ylabel("Cells")
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(out_dir / "fig_cellwise_slope_distribution.png", dpi=240)
        plt.close(fig)

        selected = (
            pd.DataFrame(cell_rows)
            .merge(df.sort_values("TotalValidSamples", ascending=False).head(6)[["QP", "BlockSizeGroup", "IntraModeGroup", "LFNSTSet"]], on=["QP", "BlockSizeGroup", "IntraModeGroup", "LFNSTSet"])
            .sort_values(["QP", "BlockSizeGroup", "IntraModeGroup", "LFNSTSet", "Latitude"])
        )
        fig, ax = plt.subplots(figsize=(7.0, 4.0))
        for key, sub in selected.groupby(["QP", "BlockSizeGroup", "IntraModeGroup", "LFNSTSet"]):
            sub = sub.set_index("Latitude").reindex(LAT_ORDER).reset_index()
            label = f"QP{key[0]} {key[1]} {key[2]} S{key[3]}"
            ax.plot(np.arange(len(LAT_ORDER)), sub["P_gain"], marker="o", label=label)
        ax.set_xticks(np.arange(len(LAT_ORDER)))
        ax.set_xticklabels(LAT_ORDER)
        ax.set_ylabel("P_gain within fixed cell")
        ax.grid(True, axis="y", alpha=0.35)
        ax.legend(fontsize=7, ncol=2)
        fig.tight_layout()
        fig.savefig(out_dir / "fig_selected_cells_gain_curve.png", dpi=240)
        plt.close(fig)
    return df


def experiment_standardized(by_lat: dict, by_cell_lat: dict, by_cell: dict, out_dir: Path, n_min: int, boot: int) -> pd.DataFrame:
    common_cells = []
    for cell in sorted({k[:4] for k in by_cell_lat}):
        if all(by_cell_lat.get(cell + (lat,), Acc()).gain_n >= n_min and by_cell_lat.get(cell + (lat,), Acc()).waste_n >= n_min for lat in LAT_ORDER):
            common_cells.append(cell)
    common_rows = []
    total_common = sum(by_cell[cell].gain_n for cell in common_cells)
    for cell in common_cells:
        qp, size, mode, lset = cell
        common_rows.append(
            {
                "QP": qp,
                "BlockSizeGroup": size,
                "SizeClass": size_class(size),
                "IntraModeGroup": mode,
                "LFNSTSet": lset,
                "GlobalSamples": by_cell[cell].gain_n,
                "GlobalWeight": ratio(by_cell[cell].gain_n, total_common),
                "UniformWeight": ratio(1, len(common_cells)),
            }
        )
    write_rows(out_dir / "table_common_support_cells.csv", common_rows)

    rng = np.random.default_rng(20260524)
    rows = []
    for ref_name in ["global", "uniform"]:
        weights = np.asarray(
            [ratio(by_cell[cell].gain_n, total_common) if ref_name == "global" else ratio(1, len(common_cells)) for cell in common_cells],
            dtype=np.float64,
        )
        for lat in LAT_ORDER:
            gain_rates = []
            waste_rates = []
            gain_ns = []
            waste_ns = []
            for cell in common_cells:
                a = by_cell_lat[cell + (lat,)]
                gain_rates.append(ratio(a.gain, a.gain_n))
                waste_rates.append(ratio(a.waste, a.waste_n))
                gain_ns.append(a.gain_n)
                waste_ns.append(a.waste_n)
            gain_rates = np.asarray(gain_rates)
            waste_rates = np.asarray(waste_rates)
            gain_ns = np.asarray(gain_ns)
            waste_ns = np.asarray(waste_ns)
            pg = float(np.sum(weights * gain_rates))
            pw = float(np.sum(weights * waste_rates))
            boot_gain = []
            boot_waste = []
            for _ in range(boot):
                bg = rng.binomial(gain_ns, gain_rates) / gain_ns
                bw = rng.binomial(waste_ns, waste_rates) / waste_ns
                boot_gain.append(float(np.sum(weights * bg)))
                boot_waste.append(float(np.sum(weights * bw)))
            rows.append(
                {
                    "ReferenceDistribution": ref_name,
                    "Latitude": lat,
                    "CommonSupportCells": len(common_cells),
                    "Raw_P_gain": ratio(by_lat[lat].gain, by_lat[lat].gain_n),
                    "Standardized_P_gain": pg,
                    "Standardized_P_gain_ci_low": float(np.percentile(boot_gain, 2.5)),
                    "Standardized_P_gain_ci_high": float(np.percentile(boot_gain, 97.5)),
                    "Raw_P_waste": ratio(by_lat[lat].waste, by_lat[lat].waste_n),
                    "Standardized_P_waste": pw,
                    "Standardized_P_waste_ci_low": float(np.percentile(boot_waste, 2.5)),
                    "Standardized_P_waste_ci_high": float(np.percentile(boot_waste, 97.5)),
                }
            )
    write_rows(out_dir / "table_standardized_gain_by_latitude.csv", rows)
    df = pd.DataFrame(rows)

    for metric, fname, ylabel in [
        ("P_gain", "fig_raw_vs_standardized_positive_gain.png", "P_gain"),
        ("P_waste", "fig_raw_vs_standardized_wasted_rdo.png", "P_waste"),
    ]:
        fig, ax = plt.subplots(figsize=(6.4, 3.7))
        x = np.arange(len(LAT_ORDER))
        raw_vals = [df[(df["ReferenceDistribution"] == "global") & (df["Latitude"] == lat)][f"Raw_{metric}"].iloc[0] for lat in LAT_ORDER]
        ax.plot(x, raw_vals, marker="o", color="black", label="raw")
        for ref, marker in [("global", "s"), ("uniform", "^")]:
            sub = df[df["ReferenceDistribution"] == ref].set_index("Latitude").reindex(LAT_ORDER)
            y = sub[f"Standardized_{metric}"].to_numpy()
            lo = sub[f"Standardized_{metric}_ci_low"].to_numpy()
            hi = sub[f"Standardized_{metric}_ci_high"].to_numpy()
            ax.errorbar(x, y, yerr=[y - lo, hi - y], marker=marker, capsize=3, label=f"standardized-{ref}")
        ax.set_xticks(x)
        ax.set_xticklabels(LAT_ORDER)
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", alpha=0.35)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / fname, dpi=240)
        plt.close(fig)
    return df


def load_feature_frame(block_root: Path, cache_path: Path) -> pd.DataFrame:
    if cache_path.exists():
        return pd.read_pickle(cache_path)
    frames = []
    base_cols = ["poc", "w", "h", "qp", "intraMode", "absLatDeg", "roiEnergyQ", "lfRatio", "predNz", "bestIdx", "oracleSkip", "hasLfnst", "deltaBestLfnst"]
    optional_cols = ["last0", "m0", "corrProxy", "deltaN", "deltaL", "deltaM"]
    for path in sorted(block_root.glob("*/blocks.csv")):
        with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
            header = next(csv.reader(fh))
        usecols = [c for c in base_cols + optional_cols if c in header]
        chunks = pd.read_csv(path, usecols=usecols, chunksize=250000)
        for ch in chunks:
            ch = ch[ch["hasLfnst"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
            ch["deltaBestLfnst"] = pd.to_numeric(ch["deltaBestLfnst"], errors="coerce")
            ch = ch[np.isfinite(ch["deltaBestLfnst"])]
            ch["w"] = ch["w"].astype(np.int16)
            ch["h"] = ch["h"].astype(np.int16)
            ch["qp"] = ch["qp"].astype(np.int16)
            ch["intraMode"] = ch["intraMode"].astype(np.int16)
            ch["poc"] = ch["poc"].astype(np.int16)
            frames.append(ch)
    df = pd.concat(frames, ignore_index=True)
    df["latBucket"] = pd.Categorical([lat_bucket(v) for v in df["absLatDeg"].to_numpy()], categories=LAT_ORDER, ordered=True)
    df["theta_norm"] = df["absLatDeg"].astype(np.float64) / 90.0
    df["area"] = (df["w"].astype(np.int32) * df["h"].astype(np.int32)).astype(np.int32)
    df["logArea"] = np.log2(df["area"].astype(np.float64))
    df["sizeGroup"] = pd.Categorical([size_group(int(w), int(h)) for w, h in zip(df["w"], df["h"])], categories=SIZE_ORDER)
    df["sizeClass"] = pd.Categorical([size_class(s) for s in df["sizeGroup"].astype(str)])
    df["modeGroup"] = pd.Categorical([mode_group(int(m)) for m in df["intraMode"]], categories=MODE_ORDER)
    df["lfnstSet"] = pd.Categorical([lfnst_set(int(m)) for m in df["intraMode"]])
    df["logRoi"] = np.log1p(pd.to_numeric(df["roiEnergyQ"], errors="coerce").astype(np.float64).clip(lower=0.0))
    df["lfRatio"] = pd.to_numeric(df["lfRatio"], errors="coerce").astype(np.float64).clip(0.0, 1.0)
    df["predNz"] = pd.to_numeric(df["predNz"], errors="coerce").astype(np.float64).clip(lower=0.0)
    df["last0"] = pd.to_numeric(df["last0"], errors="coerce").fillna(-1.0).astype(np.float64) if "last0" in df.columns else -1.0
    df["m0"] = pd.to_numeric(df["m0"], errors="coerce").fillna(0.0).astype(np.float64).clip(lower=0.0) if "m0" in df.columns else 0.0
    df["logM0"] = np.log1p(df["m0"].astype(np.float64))
    df["corrProxy"] = pd.to_numeric(df["corrProxy"], errors="coerce").fillna(0.0).astype(np.float64).clip(lower=0.0) if "corrProxy" in df.columns else 0.0
    for col in ["deltaN", "deltaL", "deltaM"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64) if col in df.columns else math.nan
    df["gain"] = (df["deltaBestLfnst"] > 0.0).astype(np.int8)
    df["waste"] = ((df["oracleSkip"].astype(str).str.lower().isin(["true", "1", "yes"])) | (pd.to_numeric(df["bestIdx"], errors="coerce").fillna(0).astype(int) == 0)).astype(np.int8)
    df = df[["poc", "qp", "absLatDeg", "theta_norm", "latBucket", "area", "logArea", "sizeGroup", "sizeClass", "modeGroup", "lfnstSet", "logRoi", "lfRatio", "predNz", "last0", "logM0", "corrProxy", "deltaN", "deltaL", "deltaM", "gain", "waste", "deltaBestLfnst"]].copy()
    df.to_pickle(cache_path)
    return df


def weighted_auc_from_grouped(model_df: pd.DataFrame, pred: np.ndarray) -> float:
    y = np.r_[np.ones(len(model_df)), np.zeros(len(model_df))]
    scores = np.r_[pred, pred]
    weights = np.r_[model_df["success"].to_numpy(), model_df["failure"].to_numpy()]
    mask = weights > 0
    return float(roc_auc_score(y[mask], scores[mask], sample_weight=weights[mask]))


def model_matrix(df: pd.DataFrame, model: str) -> tuple[pd.DataFrame, list[str]]:
    x = pd.DataFrame(index=df.index)
    x["qp"] = df["qp"].astype(float)
    x["logArea"] = df["logArea"].astype(float)
    categorical_cols = ["sizeGroup", "modeGroup", "lfnstSet", "roiBin", "lfBin", "nzBin", "lastBin", "m0Bin", "corrBin"]
    for col in [c for c in categorical_cols if c in df.columns]:
        d = pd.get_dummies(df[col].astype(str), prefix=col, drop_first=True, dtype=float)
        x = pd.concat([x, d], axis=1)
    if model in {"M1", "M2"}:
        x["theta_norm"] = df["theta_norm"].astype(float)
    if model == "M2":
        for size in sorted(df["sizeGroup"].astype(str).unique()):
            if size == sorted(df["sizeGroup"].astype(str).unique())[0]:
                continue
            x[f"theta_x_size_{size}"] = df["theta_norm"].astype(float) * (df["sizeGroup"].astype(str) == size).astype(float)
    cols = list(x.columns)
    return x, cols


def fit_grouped_logistic(g: pd.DataFrame, model: str) -> dict[str, object]:
    xdf, cols = model_matrix(g, model)
    # Two-row grouped representation: one success row and one failure row.
    X = np.vstack([xdf.to_numpy(dtype=np.float64), xdf.to_numpy(dtype=np.float64)])
    y = np.r_[np.ones(len(g), dtype=np.float64), np.zeros(len(g), dtype=np.float64)]
    sw = np.r_[g["success"].to_numpy(dtype=np.float64), g["failure"].to_numpy(dtype=np.float64)]
    keep = sw > 0
    X, y, sw = X[keep], y[keep], sw[keep]
    try:
        clf = LogisticRegression(penalty="none", solver="lbfgs", max_iter=500, fit_intercept=True)
        clf.fit(X, y, sample_weight=sw)
    except Exception:
        clf = LogisticRegression(C=1.0e6, solver="lbfgs", max_iter=500, fit_intercept=True)
        clf.fit(X, y, sample_weight=sw)
    coef = clf.coef_.ravel()
    intercept = float(clf.intercept_[0])
    p_cell = clf.predict_proba(xdf.to_numpy(dtype=np.float64))[:, 1]
    eps = 1.0e-12
    ll = float(np.sum(g["success"].to_numpy() * np.log(np.clip(p_cell, eps, 1.0)) + g["failure"].to_numpy() * np.log(np.clip(1.0 - p_cell, eps, 1.0))))
    p_null = float(g["success"].sum() / g["total"].sum())
    ll_null = float(np.sum(g["success"].to_numpy() * np.log(p_null) + g["failure"].to_numpy() * np.log(1.0 - p_null)))
    k = len(coef) + 1
    n = float(g["total"].sum())
    # Approximate covariance from observed Fisher information.
    Xh = np.column_stack([np.ones(len(X), dtype=np.float64), X])
    pred_row = clf.predict_proba(X)[:, 1]
    w = sw * pred_row * (1.0 - pred_row)
    fisher = Xh.T @ (Xh * w[:, None])
    cov = np.linalg.pinv(fisher)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    params = np.r_[intercept, coef]
    z = np.divide(params, se, out=np.full_like(params, np.nan), where=se > 0)
    pvals = 2.0 * norm.sf(np.abs(z))
    names = ["Intercept"] + cols
    return {
        "name": model,
        "clf": clf,
        "cols": cols,
        "pred": p_cell,
        "ll": ll,
        "ll_null": ll_null,
        "aic": 2 * k - 2 * ll,
        "bic": math.log(n) * k - 2 * ll,
        "df_model": k - 1,
        "auc": weighted_auc_from_grouped(g, p_cell),
        "coef_table": pd.DataFrame(
            {
                "Term": names,
                "Coefficient": params,
                "StdErr": se,
                "z": z,
                "p_value": pvals,
                "ci_low": params - 1.96 * se,
                "ci_high": params + 1.96 * se,
                "OddsRatio": np.exp(np.clip(params, -50, 50)),
            }
        ),
    }


def wls_coefficients(df: pd.DataFrame, y: np.ndarray, feature_model: str) -> pd.DataFrame:
    xdf, cols = model_matrix(df, feature_model)
    X = np.column_stack([np.ones(len(xdf), dtype=np.float64), xdf.to_numpy(dtype=np.float64)])
    names = ["Intercept"] + cols
    beta = np.linalg.pinv(X.T @ X) @ (X.T @ y)
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    sigma2 = float((resid @ resid) / dof)
    cov = sigma2 * np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    tval = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    pval = 2.0 * student_t.sf(np.abs(tval), dof)
    return pd.DataFrame(
        {
            "Term": names,
            "Coefficient_deltaJ_million": beta,
            "StdErr": se,
            "t": tval,
            "p_value": pval,
            "ci_low": beta - 1.96 * se,
            "ci_high": beta + 1.96 * se,
        }
    )


def experiment_regression(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    qdf = df.copy()
    qdf["roiBin"] = pd.qcut(qdf["logRoi"], 6, labels=False, duplicates="drop")
    qdf["lfBin"] = pd.qcut(qdf["lfRatio"], 5, labels=False, duplicates="drop")
    qdf["nzBin"] = pd.qcut(qdf["predNz"], 6, labels=False, duplicates="drop")
    qdf["lastBin"] = pd.qcut(qdf["last0"], 6, labels=False, duplicates="drop")
    qdf["m0Bin"] = pd.qcut(qdf["logM0"], 6, labels=False, duplicates="drop")
    qdf["corrBin"] = pd.qcut(qdf["corrProxy"], 6, labels=False, duplicates="drop")
    qdf["thetaBin"] = np.floor(qdf["absLatDeg"] / 5.0).astype(int)
    group_cols = ["thetaBin", "qp", "sizeGroup", "modeGroup", "lfnstSet", "roiBin", "lfBin", "nzBin", "lastBin", "m0Bin", "corrBin"]
    g = qdf.groupby(group_cols, observed=True).agg(
        total=("gain", "size"),
        success=("gain", "sum"),
        theta_norm=("theta_norm", "mean"),
        absLatDeg=("absLatDeg", "mean"),
        logArea=("logArea", "mean"),
        logRoi=("logRoi", "mean"),
        lfRatio=("lfRatio", "mean"),
        predNz=("predNz", "mean"),
        last0=("last0", "mean"),
        logM0=("logM0", "mean"),
        corrProxy=("corrProxy", "mean"),
    ).reset_index()
    g = g[g["total"] >= 20].copy()
    g["failure"] = g["total"] - g["success"]
    g["prop"] = g["success"] / g["total"]
    g["sizeGroup"] = g["sizeGroup"].astype(str)
    g["modeGroup"] = g["modeGroup"].astype(str)
    g["lfnstSet"] = g["lfnstSet"].astype(str)
    g["roiBin"] = g["roiBin"].astype(str)
    g["lfBin"] = g["lfBin"].astype(str)
    g["nzBin"] = g["nzBin"].astype(str)
    g["lastBin"] = g["lastBin"].astype(str)
    g["m0Bin"] = g["m0Bin"].astype(str)
    g["corrBin"] = g["corrBin"].astype(str)

    models = {
        "M0_no_latitude": fit_grouped_logistic(g, "M0"),
        "M1_add_latitude": fit_grouped_logistic(g, "M1"),
        "M2_latitude_size_interaction": fit_grouped_logistic(g, "M2"),
    }

    comp_rows = []
    prev_name = None
    for name, model in models.items():
        lr_stat = p_value = math.nan
        if prev_name:
            prev = models[prev_name]
            lr_stat = 2.0 * (model["ll"] - prev["ll"])
            df_diff = model["df_model"] - prev["df_model"]
            p_value = float(chi2.sf(lr_stat, df_diff)) if df_diff > 0 else math.nan
        comp_rows.append(
            {
                "Model": name,
                "NumGroupedCells": len(g),
                "TotalWeightedSamples": int(g["total"].sum()),
                "DfModel": float(model["df_model"]),
                "LogLikelihood": float(model["ll"]),
                "AIC": float(model["aic"]),
                "BIC_llf": float(model["bic"]),
                "McFaddenPseudoR2": float(1.0 - model["ll"] / model["ll_null"]),
                "WeightedAUC": float(model["auc"]),
                "LR_vs_previous": lr_stat,
                "LR_p_value": p_value,
            }
        )
        prev_name = name
    write_rows(out_dir / "table_model_comparison_likelihood.csv", comp_rows)

    m2 = models["M2_latitude_size_interaction"]
    write_rows(out_dir / "table_logistic_model_coefficients.csv", m2["coef_table"].to_dict("records"))

    # OLS on clipped deltaJ for continuous-gain evidence.
    sample = df.copy()
    if len(sample) > 650000:
        sample = sample.sample(650000, random_state=20260524)
    sample["roiBin"] = pd.qcut(sample["logRoi"], 6, labels=False, duplicates="drop").astype(str)
    sample["lfBin"] = pd.qcut(sample["lfRatio"], 5, labels=False, duplicates="drop").astype(str)
    sample["nzBin"] = pd.qcut(sample["predNz"], 6, labels=False, duplicates="drop").astype(str)
    sample["lastBin"] = pd.qcut(sample["last0"], 6, labels=False, duplicates="drop").astype(str)
    sample["m0Bin"] = pd.qcut(sample["logM0"], 6, labels=False, duplicates="drop").astype(str)
    sample["corrBin"] = pd.qcut(sample["corrProxy"], 6, labels=False, duplicates="drop").astype(str)
    y_delta = (np.clip(sample["deltaBestLfnst"].astype(float), -2.0e7, 2.0e7) / 1.0e6).to_numpy(dtype=np.float64)
    write_rows(out_dir / "table_deltaJ_regression_coefficients.csv", wls_coefficients(sample, y_delta, "M2").to_dict("records"))

    # Partial effects by size group.
    base = g.copy()
    base_vals = {
        "qp": float(base["qp"].median()),
        "logArea": float(base["logArea"].median()),
        "modeGroup": base["modeGroup"].mode().iloc[0],
        "lfnstSet": base["lfnstSet"].mode().iloc[0],
        "roiBin": base["roiBin"].mode().iloc[0],
        "lfBin": base["lfBin"].mode().iloc[0],
        "nzBin": base["nzBin"].mode().iloc[0],
        "lastBin": base["lastBin"].mode().iloc[0],
        "m0Bin": base["m0Bin"].mode().iloc[0],
        "corrBin": base["corrBin"].mode().iloc[0],
    }
    pred_rows = []
    theta_grid = np.linspace(0.0, 85.0, 18)
    for size in [s for s in SIZE_ORDER if s in set(g["sizeGroup"])]:
        log_area = math.log2({"area_16": 16, "area_32": 32, "area_64": 64, "area_256": 256, "area_1024": 1024}.get(size, 4096))
        tmp = pd.DataFrame(
            {
                **base_vals,
                "sizeGroup": size,
                "theta_norm": theta_grid / 90.0,
                "absLatDeg": theta_grid,
                "logArea": log_area,
            }
        )
        xtmp, _ = model_matrix(tmp, "M2")
        for col in m2["cols"]:
            if col not in xtmp:
                xtmp[col] = 0.0
            if col == f"theta_x_size_{size}":
                xtmp[col] = tmp["theta_norm"].to_numpy(dtype=np.float64)
        xtmp = xtmp[m2["cols"]]
        p = m2["clf"].predict_proba(xtmp.to_numpy(dtype=np.float64))[:, 1]
        for t, val in zip(theta_grid, p):
            pred_rows.append({"BlockSizeGroup": size, "absLatDeg": t, "Predicted_P_gain": float(val)})
    write_rows(out_dir / "partial_effect_latitude_by_size.csv", pred_rows)
    pdf = pd.DataFrame(pred_rows)
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    for size, sub in pdf.groupby("BlockSizeGroup"):
        ax.plot(sub["absLatDeg"], sub["Predicted_P_gain"], label=size)
    ax.set_xlabel("|latitude| (degree)")
    ax.set_ylabel("Adjusted Pr(DeltaJ > 0)")
    ax.grid(True, axis="y", alpha=0.35)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_partial_effect_latitude_by_size.png", dpi=240)
    plt.close(fig)

    pivot = pdf.pivot(index="BlockSizeGroup", columns="absLatDeg", values="Predicted_P_gain")
    fig, ax = plt.subplots(figsize=(7.2, 3.5))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="viridis", vmin=0.0, vmax=1.0)
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    xticks = np.linspace(0, len(pivot.columns) - 1, 6, dtype=int)
    ax.set_xticks(xticks)
    ax.set_xticklabels([f"{pivot.columns[i]:.0f}" for i in xticks])
    ax.set_xlabel("|latitude| (degree)")
    ax.set_title("Adjusted P_gain partial dependence")
    fig.colorbar(im, ax=ax, label="P_gain")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_partial_dependence_theta_area.png", dpi=240)
    plt.close(fig)
    return g


def smd(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    va = np.nanvar(a, ddof=1)
    vb = np.nanvar(b, ddof=1)
    denom = math.sqrt((va + vb) / 2.0)
    return float((np.nanmean(a) - np.nanmean(b)) / denom) if denom > 0 else 0.0


def experiment_matching(df: pd.DataFrame, out_dir: Path, max_high_per_stratum: int) -> None:
    cols = ["logRoi", "lfRatio", "predNz", "last0", "logM0", "corrProxy"]
    low = df[df["absLatDeg"] < 30.0].copy()
    high = df[df["absLatDeg"] >= 60.0].copy()
    match_rows = []
    rng = np.random.default_rng(20260524)
    strata_cols = ["qp", "sizeGroup", "modeGroup", "lfnstSet"]
    for key, hi in high.groupby(strata_cols, observed=True):
        lo_mask = np.ones(len(low), dtype=bool)
        for c, v in zip(strata_cols, key):
            lo_mask &= (low[c].to_numpy() == v)
        lo = low[lo_mask]
        if len(lo) < 10 or len(hi) < 10:
            continue
        if len(hi) > max_high_per_stratum:
            hi = hi.sample(max_high_per_stratum, random_state=int(rng.integers(1, 2**31 - 1)))
        comb = pd.concat([hi[cols], lo[cols]], axis=0)
        mean = comb.mean()
        std = comb.std().replace(0.0, 1.0)
        x_low = ((lo[cols] - mean) / std).to_numpy()
        x_high = ((hi[cols] - mean) / std).to_numpy()
        nn = NearestNeighbors(n_neighbors=1, algorithm="auto").fit(x_low)
        dist, idx = nn.kneighbors(x_high)
        lo_match = lo.iloc[idx[:, 0]].reset_index(drop=True)
        hi = hi.reset_index(drop=True)
        for i in range(len(hi)):
            match_rows.append(
                {
                    "QP": int(hi.loc[i, "qp"]),
                    "BlockSizeGroup": str(hi.loc[i, "sizeGroup"]),
                    "SizeClass": str(hi.loc[i, "sizeClass"]),
                    "IntraModeGroup": str(hi.loc[i, "modeGroup"]),
                    "LFNSTSet": str(hi.loc[i, "lfnstSet"]),
                    "Distance": float(dist[i, 0]),
                    "High_gain": int(hi.loc[i, "gain"]),
                    "Low_gain": int(lo_match.loc[i, "gain"]),
                    "High_deltaJ": float(hi.loc[i, "deltaBestLfnst"]),
                    "Low_deltaJ": float(lo_match.loc[i, "deltaBestLfnst"]),
                    "High_logRoi": float(hi.loc[i, "logRoi"]),
                    "Low_logRoi": float(lo_match.loc[i, "logRoi"]),
                    "High_lfRatio": float(hi.loc[i, "lfRatio"]),
                    "Low_lfRatio": float(lo_match.loc[i, "lfRatio"]),
                    "High_predNz": float(hi.loc[i, "predNz"]),
                    "Low_predNz": float(lo_match.loc[i, "predNz"]),
                    "High_last0": float(hi.loc[i, "last0"]),
                    "Low_last0": float(lo_match.loc[i, "last0"]),
                    "High_logM0": float(hi.loc[i, "logM0"]),
                    "Low_logM0": float(lo_match.loc[i, "logM0"]),
                    "High_corrProxy": float(hi.loc[i, "corrProxy"]),
                    "Low_corrProxy": float(lo_match.loc[i, "corrProxy"]),
                }
            )
    m = pd.DataFrame(match_rows)
    m.to_csv(out_dir / "matched_pairs_low_high_latitude.csv", index=False)

    balance_rows = []
    for var in cols:
        before = smd(high[var], low[var])
        after = smd(m[f"High_{var}"], m[f"Low_{var}"]) if not m.empty else math.nan
        balance_rows.append({"Variable": var, "SMD_before": before, "SMD_after": after, "AbsSMD_before": abs(before), "AbsSMD_after": abs(after)})
    write_rows(out_dir / "table_matching_balance_before_after.csv", balance_rows)

    comp_rows = []
    groups = [("all", m)]
    for sc, sub in m.groupby("SizeClass") if not m.empty else []:
        groups.append((str(sc), sub))
    for name, sub in groups:
        comp_rows.append(
            {
                "Group": name,
                "MatchedPairs": len(sub),
                "P_gain_high": float(sub["High_gain"].mean()) if len(sub) else math.nan,
                "P_gain_low": float(sub["Low_gain"].mean()) if len(sub) else math.nan,
                "P_gain_high_minus_low": float((sub["High_gain"] - sub["Low_gain"]).mean()) if len(sub) else math.nan,
                "MeanDeltaJ_high": float(sub["High_deltaJ"].mean()) if len(sub) else math.nan,
                "MeanDeltaJ_low": float(sub["Low_deltaJ"].mean()) if len(sub) else math.nan,
                "MeanDeltaJ_high_minus_low": float((sub["High_deltaJ"] - sub["Low_deltaJ"]).mean()) if len(sub) else math.nan,
            }
        )
    write_rows(out_dir / "table_matched_gain_comparison.csv", comp_rows)

    fig, ax = plt.subplots(figsize=(5.8, 3.2))
    y = np.arange(len(balance_rows))
    ax.scatter([r["AbsSMD_before"] for r in balance_rows], y, label="before")
    ax.scatter([r["AbsSMD_after"] for r in balance_rows], y, label="after")
    ax.axvline(0.1, color="red", linestyle="--", linewidth=0.9)
    ax.set_yticks(y)
    ax.set_yticklabels([r["Variable"] for r in balance_rows])
    ax.set_xlabel("|standardized mean difference|")
    ax.grid(True, axis="x", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "fig_covariate_balance_love_plot.png", dpi=240)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    hi = np.clip(m["High_deltaJ"].to_numpy(), -2.0e7, 2.0e7) if not m.empty else []
    lo = np.clip(m["Low_deltaJ"].to_numpy(), -2.0e7, 2.0e7) if not m.empty else []
    ax.hist(lo, bins=80, alpha=0.55, density=True, label="matched low lat")
    ax.hist(hi, bins=80, alpha=0.55, density=True, label="matched high lat")
    ax.axvline(0.0, color="black", linewidth=0.8)
    ax.set_xlabel("DeltaJ_LFNST (clipped)")
    ax.set_ylabel("density")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "fig_matched_deltaJ_distribution.png", dpi=240)
    plt.close(fig)


def make_report(out_dir: Path) -> None:
    raw = pd.read_csv(out_dir / "table_raw_lfnst_behavior_by_latitude.csv")
    slopes = pd.read_csv(out_dir / "table_cellwise_latitude_slope.csv")
    std = pd.read_csv(out_dir / "table_standardized_gain_by_latitude.csv")
    comp = pd.read_csv(out_dir / "table_model_comparison_likelihood.csv")
    match = pd.read_csv(out_dir / "table_matched_gain_comparison.csv")

    def fmt(x: float) -> str:
        return f"{x:.6g}" if isinstance(x, (float, np.floating)) and math.isfinite(float(x)) else str(x)

    def md_table(df: pd.DataFrame, cols: list[str]) -> str:
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, r in df[cols].iterrows():
            lines.append("| " + " | ".join(fmt(v) for v in r.tolist()) + " |")
        return "\n".join(lines)

    medium = slopes[slopes["SizeClass"] == "medium"]
    report = [
        "# Conditional LFNST Latitude/Size Behavior Experiments",
        "",
        "## Scope",
        "",
        "This report uses the existing AerialCity full-RDO trace. The available ROI controls are `roiEnergyQ`, `lfRatio`, and `predNz`. The current trace does not contain an independent no-LFNST last-position feature `L0`, so `L0` is not included in the regression/matching controls.",
        "",
        "## 2.1 Raw Observation",
        "",
        md_table(raw, ["Latitude", "P_waste", "P_gain", "Mean_DeltaJ"]),
        "",
        "Figures: `fig_raw_wasted_rdo_by_latitude.png`, `fig_raw_positive_gain_by_latitude.png`, `fig_deltaJ_distribution_by_latitude.png`.",
        "",
        "## 2.2 Stratified Cell Slopes",
        "",
        f"Valid cells: `{len(slopes)}`. Cells with positive P_gain slope: `{int(slopes['GainSlopePositive'].sum())}` / `{len(slopes)}`.",
        f"Medium-size cells with positive P_gain slope: `{int(medium['GainSlopePositive'].sum())}` / `{len(medium)}`.",
        "",
        "Outputs: `table_stratified_gain_by_lat_qp_size_mode_set.csv`, `table_cellwise_latitude_slope.csv`, `fig_cellwise_slope_distribution.png`, `fig_selected_cells_gain_curve.png`.",
        "",
        "## 2.3 Marginal Standardization",
        "",
        md_table(std[std["ReferenceDistribution"] == "global"], ["Latitude", "Raw_P_gain", "Standardized_P_gain", "Raw_P_waste", "Standardized_P_waste"]),
        "",
        "Outputs: `table_standardized_gain_by_latitude.csv`, `table_common_support_cells.csv`, `fig_raw_vs_standardized_positive_gain.png`, `fig_raw_vs_standardized_wasted_rdo.png`.",
        "",
        "## 2.4 Multivariable Logistic Regression",
        "",
        md_table(comp, ["Model", "LogLikelihood", "AIC", "McFaddenPseudoR2", "WeightedAUC", "LR_vs_previous", "LR_p_value"]),
        "",
        "Outputs: `table_logistic_model_coefficients.csv`, `table_deltaJ_regression_coefficients.csv`, `fig_partial_effect_latitude_by_size.png`, `fig_partial_dependence_theta_area.png`.",
        "",
        "## 2.5 Matching Analysis",
        "",
        md_table(match, ["Group", "MatchedPairs", "P_gain_high", "P_gain_low", "P_gain_high_minus_low", "MeanDeltaJ_high_minus_low"]),
        "",
        "Outputs: `table_matching_balance_before_after.csv`, `fig_covariate_balance_love_plot.png`, `table_matched_gain_comparison.csv`, `fig_matched_deltaJ_distribution.png`.",
        "",
        "## Interpretation",
        "",
        "Use the raw curves only as motivation. The conditional evidence is the stratified slope distribution, marginal standardization, the likelihood improvement from adding latitude and latitude-size interaction, and the matched comparison. If the standardized/matched effects remain non-zero, latitude provides explanatory information beyond the observed QP/size/mode/set and ROI-feature composition. The interaction model is the main evidence for size-dependent latitude behavior.",
        "",
    ]
    (out_dir / "conditional_effects_report.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--block-root", type=Path, default=Path("lahtp_runs/aerialcity_final_trace_fullrdo_skip6_theta45"))
    parser.add_argument("--out-dir", type=Path, default=Path("lahtp_runs/conditional_lfnst_latitude_size_effects"))
    parser.add_argument("--n-min", type=int, default=100)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--max-high-per-stratum", type=int, default=5000)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    by_lat, by_cell_lat, by_cell, _ = experiment_raw(args.block_root, args.out_dir)
    experiment_stratified(by_cell_lat, args.out_dir, args.n_min)
    experiment_standardized(by_lat, by_cell_lat, by_cell, args.out_dir, args.n_min, args.bootstrap)
    cache_path = args.out_dir / "lfnst_conditional_features.pkl"
    df = load_feature_frame(args.block_root, cache_path)
    experiment_regression(df, args.out_dir)
    experiment_matching(df, args.out_dir, args.max_high_per_stratum)
    make_report(args.out_dir)


if __name__ == "__main__":
    main()
