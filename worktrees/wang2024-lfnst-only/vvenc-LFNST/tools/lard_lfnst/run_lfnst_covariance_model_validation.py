#!/usr/bin/env python3
"""Run paper experiment 4.2 covariance-model validation.

4.2-A visualizes the theoretical propagation
R_hor(theta) -> Sigma_E(theta) -> Sigma_F(theta) -> Sigma_x(theta).

4.2-B compares the theoretical low-frequency covariance Sigma_x(theta) with
empirical no-LFNST primary-transform LFNST input vectors produced by
LardLfnst2ndVecFile.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.compute_lfnst_theory_stats import dct2_orthonormal_matrix, lfnst_input_coords, parse_rom_lfnst
from tools.lard_lfnst import experiment_4_2_metrics as exp42
from tools.lard_lfnst import model_validation_stats as mvstats


EPS = 1.0e-12
DEFAULT_THETAS = [0.0, 30.0, 60.0, 75.0]
DEFAULT_SIZES = [(4, 4), (8, 8), (16, 16)]
DEFAULT_VEC_GLOB = "tools/lard_lfnst/empirical_mechanism_diag_20260624/*/QP*/empirical_lfnst_vec.csv"


@dataclass(frozen=True)
class TheoryMatrices:
    width: int
    height: int
    theta_deg: float
    R_hor: np.ndarray
    R_ver: np.ndarray
    Sigma_E: np.ndarray
    Sigma_F: np.ndarray
    Sigma_x: np.ndarray
    coords: list[tuple[int, int]]


class CovAccumulator:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.n = 0
        self.sum = np.zeros(dim, dtype=np.float64)
        self.cross = np.zeros((dim, dim), dtype=np.float64)

    def add_many(self, values: np.ndarray) -> None:
        if values.size == 0:
            return
        vals = values[:, : self.dim].astype(np.float64, copy=False)
        vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
        self.n += int(vals.shape[0])
        self.sum += vals.sum(axis=0)
        self.cross += vals.T @ vals

    def add_one(self, values: np.ndarray) -> None:
        vec = values[: self.dim].astype(np.float64, copy=False)
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
        self.n += 1
        self.sum += vec
        self.cross += np.outer(vec, vec)

    def covariance(self) -> np.ndarray:
        if self.n <= 0:
            return np.zeros((self.dim, self.dim), dtype=np.float64)
        mean = self.sum / float(self.n)
        cov = self.cross / float(self.n) - np.outer(mean, mean)
        return (cov + cov.T) * 0.5


def corr_matrix_h(width: int, theta_deg: float, rho0: float = 0.6) -> np.ndarray:
    idx = np.arange(width, dtype=np.float64)
    dist = np.abs(idx[:, None] - idx[None, :])
    return rho0 ** (dist * math.cos(math.radians(abs(theta_deg))))


def corr_matrix_v(height: int, rho_ver: float = 0.6) -> np.ndarray:
    idx = np.arange(height, dtype=np.float64)
    dist = np.abs(idx[:, None] - idx[None, :])
    return rho_ver ** dist


def _sigma_x_from_sigma_f(sigma_f: np.ndarray, width: int, height: int, transpose: int) -> tuple[np.ndarray, list[tuple[int, int]]]:
    sb_size = 4 if min(width, height) == 4 else 8
    coords = lfnst_input_coords(width, height, sb_size, transpose)
    indices = [y * width + x for x, y in coords]
    return sigma_f[np.ix_(indices, indices)], coords


def theory_matrices_for(
    width: int,
    height: int,
    theta_deg: float,
    rho0: float = 0.6,
    rho_ver: float = 0.6,
    sigma_e2: float = 1.0,
    transpose: int = 0,
) -> TheoryMatrices:
    r_hor = corr_matrix_h(width, theta_deg, rho0)
    r_ver = corr_matrix_v(height, rho_ver)
    sigma_e = sigma_e2 * np.kron(r_ver, r_hor)
    dct_h = dct2_orthonormal_matrix(width)
    dct_v = dct2_orthonormal_matrix(height)
    transform = np.kron(dct_v, dct_h)
    sigma_f = transform @ sigma_e @ transform.T
    sigma_f = (sigma_f + sigma_f.T) * 0.5
    sigma_x, coords = _sigma_x_from_sigma_f(sigma_f, width, height, transpose)
    sigma_x = (sigma_x + sigma_x.T) * 0.5
    return TheoryMatrices(width, height, theta_deg, r_hor, r_ver, sigma_e, sigma_f, sigma_x, coords)


def _corr_from_cov(sigma: np.ndarray) -> np.ndarray:
    diag = np.sqrt(np.maximum(np.diag(sigma), EPS))
    return sigma / (diag[:, None] * diag[None, :] + EPS)


def offdiag_abs_mean_corr(sigma: np.ndarray) -> float:
    if sigma.shape[0] <= 1:
        return 0.0
    corr = np.abs(_corr_from_cov(sigma))
    mask = ~np.eye(corr.shape[0], dtype=bool)
    return float(np.mean(corr[mask]))


def diag_dominance(sigma: np.ndarray) -> float:
    return float(np.sum(np.abs(np.diag(sigma))) / (np.sum(np.abs(sigma)) + EPS))


def frobenius_cosine(a: np.ndarray, b: np.ndarray) -> float:
    dim = min(a.shape[0], b.shape[0])
    aa = a[:dim, :dim]
    bb = b[:dim, :dim]
    return float(np.sum(aa * bb) / (np.linalg.norm(aa, "fro") * np.linalg.norm(bb, "fro") + EPS))


def _pearson(x: Iterable[float], y: Iterable[float]) -> float:
    xa = np.asarray(list(x), dtype=np.float64)
    ya = np.asarray(list(y), dtype=np.float64)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa = xa[mask]
    ya = ya[mask]
    if xa.size < 2 or np.std(xa) <= EPS or np.std(ya) <= EPS:
        return float("nan")
    return float(np.corrcoef(xa, ya)[0, 1])


def parse_sizes(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for token in text.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if "x" in token:
            w_text, h_text = token.split("x", 1)
            out.append((int(w_text), int(h_text)))
        else:
            n = int(token)
            out.append((n, n))
    return out


def parse_float_list(text: str) -> list[float]:
    return [float(v.strip()) for v in text.split(",") if v.strip()]


def _theta_label(theta: float) -> str:
    return f"{int(round(theta))}deg"


def _block_label(width: int, height: int) -> str:
    return f"{width}x{height}"


def _shuffle_theta(theta: float, theta_values: list[float]) -> float:
    ordered = sorted(float(v) for v in theta_values)
    if len(ordered) <= 1:
        return ordered[0]
    nearest = min(range(len(ordered)), key=lambda idx: abs(ordered[idx] - theta))
    return ordered[(nearest + 1) % len(ordered)]


def _nearest_theta(value: float, theta_values: list[float]) -> float:
    return min(theta_values, key=lambda theta: abs(float(theta) - float(value)))


def _theta_from_chunk(chunk: pd.DataFrame, theta_values: list[float]) -> pd.Series:
    if "latBucket" in chunk.columns:
        mapping = {0: theta_values[0], 1: theta_values[min(1, len(theta_values) - 1)],
                   2: theta_values[min(2, len(theta_values) - 1)], 3: theta_values[-1]}
        return chunk["latBucket"].fillna(0).astype(int).map(lambda v: float(mapping.get(int(v), theta_values[-1])))
    if "latBin" in chunk.columns:
        unique = sorted(set(int(v) for v in chunk["latBin"].dropna().unique()))
        if unique and max(unique) < len(theta_values):
            return chunk["latBin"].fillna(0).astype(int).map(lambda v: float(theta_values[min(int(v), len(theta_values) - 1)]))
    return chunk["absLatDeg"].map(lambda v: _nearest_theta(float(v), theta_values))


def _theta_from_values(lat_bucket: int | None, lat_bin: int | None, abs_lat: float, theta_values: list[float]) -> float:
    if lat_bucket is not None:
        mapping = {
            0: theta_values[0],
            1: theta_values[min(1, len(theta_values) - 1)],
            2: theta_values[min(2, len(theta_values) - 1)],
            3: theta_values[-1],
        }
        return float(mapping.get(int(lat_bucket), theta_values[-1]))
    if lat_bin is not None and 0 <= int(lat_bin) < len(theta_values):
        return float(theta_values[int(lat_bin)])
    return _nearest_theta(abs_lat, theta_values)


def _resolve_inputs(inputs: Iterable[str | Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        text = str(item)
        matches = [Path(p) for p in glob.glob(text)]
        if matches:
            paths.extend(matches)
        elif Path(text).exists():
            paths.append(Path(text))
    return sorted(set(paths))


def _theory_cache(
    sizes: list[tuple[int, int]],
    theta_values: list[float],
    rho0: float,
    rho_ver: float,
    sigma_e2: float,
) -> dict[tuple[float, int, int, int], TheoryMatrices]:
    cache: dict[tuple[float, int, int, int], TheoryMatrices] = {}
    for theta in theta_values:
        for width, height in sizes:
            for transpose in (0, 1):
                cache[(float(theta), width, height, transpose)] = theory_matrices_for(
                    width, height, theta, rho0=rho0, rho_ver=rho_ver, sigma_e2=sigma_e2, transpose=transpose
                )
    return cache


def run_theory_propagation(
    out_dir: Path,
    sizes: list[tuple[int, int]] | None = None,
    theta_values: list[float] | None = None,
    rho0: float = 0.6,
    rho_ver: float = 0.6,
    sigma_e2: float = 1.0,
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes = sizes or DEFAULT_SIZES
    theta_values = theta_values or DEFAULT_THETAS
    matrices: dict[str, np.ndarray] = {}
    rows: list[dict[str, object]] = []

    for width, height in sizes:
        per_theta = [theory_matrices_for(width, height, theta, rho0, rho_ver, sigma_e2, transpose=0) for theta in theta_values]
        for mats in per_theta:
            key = f"{_block_label(width, height)}_{_theta_label(mats.theta_deg)}"
            matrices[f"R_hor_{key}"] = mats.R_hor.astype(np.float32)
            matrices[f"Sigma_E_{key}"] = mats.Sigma_E.astype(np.float32)
            matrices[f"Sigma_F_{key}"] = mats.Sigma_F.astype(np.float32)
            matrices[f"Sigma_x_{key}"] = mats.Sigma_x.astype(np.float32)
            rows.append(
                {
                    "thetaDeg": mats.theta_deg,
                    "blockSize": _block_label(width, height),
                    "Rhor_far": float(mats.R_hor[0, -1]),
                    "SigmaE_offdiag": offdiag_abs_mean_corr(mats.Sigma_E),
                    "SigmaF_offdiag": offdiag_abs_mean_corr(mats.Sigma_F),
                    "Sigmax_offdiag": offdiag_abs_mean_corr(mats.Sigma_x),
                    "Sigmax_diagDominance": diag_dominance(mats.Sigma_x),
                    "Sigmax_trace": float(np.trace(mats.Sigma_x)),
                }
            )
        _plot_theory_small_multiples(out_dir, width, height, per_theta)

    np.savez_compressed(out_dir / "theory_covariance_matrices.npz", **matrices)
    pd.DataFrame(rows).to_csv(out_dir / "theory_covariance_metrics.csv", index=False)
    (out_dir / "theory_covariance_metadata.json").write_text(
        json.dumps(
            {"rho0": rho0, "rho_ver": rho_ver, "sigma_e2": sigma_e2, "theta_values": theta_values, "sizes": sizes},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"sizes": len(sizes), "theta_values": len(theta_values)}


def _plot_theory_small_multiples(out_dir: Path, width: int, height: int, per_theta: list[TheoryMatrices]) -> None:
    columns = [
        ("R_hor", lambda m: m.R_hor, "viridis", False),
        ("Sigma_E", lambda m: m.Sigma_E, "RdBu_r", True),
        ("Sigma_F", lambda m: m.Sigma_F, "RdBu_r", True),
        ("Sigma_x", lambda m: m.Sigma_x, "RdBu_r", True),
    ]
    fig, axes = plt.subplots(len(per_theta), len(columns), figsize=(8.8, 2.0 * len(per_theta)), constrained_layout=True)
    axes = np.asarray(axes).reshape(len(per_theta), len(columns))
    ranges: list[tuple[float, float]] = []
    for _, getter, _, symmetric in columns:
        vals = [getter(m) for m in per_theta]
        if symmetric:
            vmax = max(float(np.max(np.abs(v))) for v in vals)
            ranges.append((-vmax, vmax))
        else:
            ranges.append((0.0, max(float(np.max(v)) for v in vals)))
    for row, mats in enumerate(per_theta):
        for col, (name, getter, cmap, _) in enumerate(columns):
            ax = axes[row, col]
            vmin, vmax = ranges[col]
            im = ax.imshow(getter(mats), cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
            ax.set_xticks([])
            ax.set_yticks([])
            if row == 0:
                ax.set_title(name)
            if col == 0:
                ax.set_ylabel(f"{mats.theta_deg:g} deg")
            if row == len(per_theta) - 1:
                fig.colorbar(im, ax=axes[:, col], shrink=0.72)
    fig.suptitle(f"4.2-A covariance propagation, {_block_label(width, height)}")
    stem = out_dir / f"fig_4_2_A_theory_covariance_propagation_{width}x{height}"
    fig.savefig(stem.with_suffix(".png"), dpi=260)
    fig.savefig(stem.with_suffix(".pdf"))
    plt.close(fig)


def run_empirical_validation(
    vec_logs: list[Path],
    out_dir: Path,
    sizes: list[tuple[int, int]] | None = None,
    theta_values: list[float] | None = None,
    min_samples: int = 64,
    rho0: float = 0.6,
    rho_ver: float = 0.6,
    sigma_e2: float = 1.0,
    chunksize: int = 200000,
    write_figures: bool = True,
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes = sizes or DEFAULT_SIZES
    theta_values = theta_values or DEFAULT_THETAS
    size_set = set(sizes)
    theory = _theory_cache(sizes, theta_values, rho0, rho_ver, sigma_e2)
    accs: dict[tuple[float, int, int, int, int, int, int], CovAccumulator] = {}
    rows_seen = 0

    for path in vec_logs:
        rows_seen += _accumulate_vec_log_streaming(path, accs, size_set, theta_values)

    group_rows: list[dict[str, object]] = []
    matrices: dict[str, np.ndarray] = {}
    for (theta, width, height, qp, mode_group, transpose, dim), acc in sorted(accs.items()):
        if acc.n < min_samples:
            continue
        sigma_emp = acc.covariance()
        theta_correct = _nearest_theta(theta, theta_values)
        sig_th = theory[(theta_correct, width, height, transpose)].Sigma_x[:dim, :dim]
        wrong_thetas = [t for t in theta_values if abs(float(t) - float(theta_correct)) > 1e-9]
        wrong_sigs = [theory[(float(t), width, height, transpose)].Sigma_x[:dim, :dim] for t in wrong_thetas]
        sim_wrong = float(np.mean([frobenius_cosine(sigma_emp, sig) for sig in wrong_sigs])) if wrong_sigs else float("nan")
        ox_wrong = float(np.mean([offdiag_abs_mean_corr(sig) for sig in wrong_sigs])) if wrong_sigs else float("nan")
        ddiag_wrong = float(np.mean([diag_dominance(sig) for sig in wrong_sigs])) if wrong_sigs else float("nan")
        row = {
            "thetaDeg": theta_correct,
            "latBin": _theta_label(theta_correct),
            "blockSize": _block_label(width, height),
            "W": width,
            "H": height,
            "QP": qp,
            "modeGroup": mode_group,
            "transpose": transpose,
            "dim": dim,
            "samples": acc.n,
            "simF_correct": frobenius_cosine(sigma_emp, sig_th),
            "simF_shuffled": sim_wrong,
            "Ox_emp": offdiag_abs_mean_corr(sigma_emp),
            "Ox_theory": offdiag_abs_mean_corr(sig_th),
            "Ox_shuffled": ox_wrong,
            "Ddiag_emp": diag_dominance(sigma_emp),
            "Ddiag_theory": diag_dominance(sig_th),
            "Ddiag_shuffled": ddiag_wrong,
        }
        group_rows.append(row)
        stem = f"theta{int(theta_correct)}_{width}x{height}_qp{qp}_mg{mode_group}_tr{transpose}_d{dim}"
        matrices[f"emp_{stem}"] = sigma_emp.astype(np.float32)
        matrices[f"theory_{stem}"] = sig_th.astype(np.float32)

    group_df = pd.DataFrame(group_rows)
    group_df.to_csv(out_dir / "covariance_similarity_by_group.csv", index=False)
    if matrices:
        np.savez_compressed(out_dir / "empirical_theory_covariance_matrices.npz", **matrices)

    if group_df.empty:
        summary = pd.DataFrame(
            [{"groups": 0, "rows_seen": rows_seen, "mean_simF_correct": np.nan, "mean_simF_shuffled": np.nan, "corr_Ox": np.nan}]
        )
    else:
        summary = pd.DataFrame(
            [
                {
                    "groups": int(len(group_df)),
                    "rows_seen": int(rows_seen),
                    "samples_used": int(group_df["samples"].sum()),
                    "mean_simF_correct": float(np.average(group_df["simF_correct"], weights=group_df["samples"])),
                    "mean_simF_shuffled": float(np.average(group_df["simF_shuffled"], weights=group_df["samples"])),
                    "median_simF_correct": float(group_df["simF_correct"].median()),
                    "median_simF_shuffled": float(group_df["simF_shuffled"].median()),
                    "corr_Ox": _pearson(group_df["Ox_emp"], group_df["Ox_theory"]),
                    "corr_Ddiag": _pearson(group_df["Ddiag_emp"], group_df["Ddiag_theory"]),
                }
            ]
        )
    summary.to_csv(out_dir / "covariance_similarity_summary.csv", index=False)

    if write_figures:
        _plot_similarity_heatmaps(group_df, out_dir)
        _plot_real_vs_theory(group_df, matrices, out_dir)
    return {"rows_seen": rows_seen, "groups": int(len(group_df))}


def _accumulate_vec_log_streaming(
    path: Path,
    accs: dict[tuple[float, int, int, int, int, int, int], CovAccumulator],
    size_set: set[tuple[int, int]],
    theta_values: list[float],
) -> int:
    rows_used = 0
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        header = handle.readline().rstrip("\r\n").split(",")
        col = {name: idx for idx, name in enumerate(header)}
        required = ["w", "h", "qp", "modeGroup", "transposeFlag", "trSize", "absLatDeg", "x00"]
        missing = [name for name in required if name not in col]
        if missing:
            raise ValueError(f"{path} missing required columns: {missing}")
        x_cols = [col.get(f"x{i:02d}", -1) for i in range(48)]
        lat_bucket_col = col.get("latBucket", -1)
        lat_bin_col = col.get("latBin", -1)
        max_required_index = max(
            col["w"], col["h"], col["qp"], col["modeGroup"], col["transposeFlag"], col["trSize"], col["absLatDeg"], max(x_cols)
        )
        for line in handle:
            parts = line.rstrip("\r\n").split(",")
            if len(parts) <= max_required_index:
                continue
            try:
                width = int(float(parts[col["w"]]))
                height = int(float(parts[col["h"]]))
                if (width, height) not in size_set:
                    continue
                dim = int(float(parts[col["trSize"]]))
                if dim not in (16, 48):
                    continue
                qp = int(float(parts[col["qp"]]))
                mode_group = int(float(parts[col["modeGroup"]]))
                transpose = int(float(parts[col["transposeFlag"]]))
                abs_lat = float(parts[col["absLatDeg"]])
                lat_bucket = int(float(parts[lat_bucket_col])) if lat_bucket_col >= 0 and parts[lat_bucket_col] != "" else None
                lat_bin = int(float(parts[lat_bin_col])) if lat_bin_col >= 0 and parts[lat_bin_col] != "" else None
                vals = np.asarray([float(parts[x_cols[i]]) if x_cols[i] >= 0 and parts[x_cols[i]] != "" else 0.0 for i in range(dim)], dtype=np.float64)
            except (ValueError, IndexError):
                continue
            theta = _theta_from_values(lat_bucket, lat_bin, abs_lat, theta_values)
            key = (float(theta), width, height, qp, mode_group, transpose, dim)
            acc = accs.setdefault(key, CovAccumulator(dim))
            acc.add_one(vals)
            rows_used += 1
    return rows_used


def _weighted_pivot(df: pd.DataFrame, value: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows = []
    for (lat, size), group in df.groupby(["latBin", "blockSize"], sort=False):
        rows.append(
            {
                "latBin": lat,
                "blockSize": size,
                value: float(np.average(group[value], weights=group["samples"])),
            }
        )
    tmp = pd.DataFrame(rows)
    lat_order = sorted(tmp["latBin"].unique(), key=lambda x: float(str(x).replace("deg", "")))
    size_order = sorted(tmp["blockSize"].unique(), key=lambda s: parse_sizes(str(s))[0])
    return tmp.pivot(index="latBin", columns="blockSize", values=value).reindex(index=lat_order, columns=size_order)


def _plot_similarity_heatmaps(df: pd.DataFrame, out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.3), constrained_layout=True)
    correct = _weighted_pivot(df, "simF_correct")
    shuffled = _weighted_pivot(df, "simF_shuffled")
    for ax, table, title in zip(axes, [correct, shuffled], ["correct latitude", "shuffled latitude"]):
        if table.empty:
            ax.axis("off")
            ax.set_title(title)
            continue
        vals = table.to_numpy(dtype=float)
        im = ax.imshow(vals, cmap="viridis", vmin=0.0, vmax=1.0, aspect="auto")
        ax.set_title(title)
        ax.set_xticks(np.arange(len(table.columns)))
        ax.set_xticklabels(table.columns, rotation=30, ha="right")
        ax.set_yticks(np.arange(len(table.index)))
        ax.set_yticklabels(table.index)
        for y in range(vals.shape[0]):
            for x in range(vals.shape[1]):
                if np.isfinite(vals[y, x]):
                    ax.text(x, y, f"{vals[y, x]:.2f}", ha="center", va="center", fontsize=7, color="white" if vals[y, x] < 0.55 else "black")
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.82, label="Frobenius cosine")
    fig.savefig(out_dir / "fig_4_2_B_similarity_heatmap.png", dpi=260)
    fig.savefig(out_dir / "fig_4_2_B_similarity_heatmap.pdf")
    plt.close(fig)


def _matrix_range(mats: list[np.ndarray]) -> tuple[float, float]:
    vmax = max(float(np.max(np.abs(m))) for m in mats if m.size)
    return -vmax, vmax


def _plot_real_vs_theory(df: pd.DataFrame, matrices: dict[str, np.ndarray], out_dir: Path) -> None:
    if df.empty or not matrices:
        fig, ax = plt.subplots(figsize=(5, 2))
        ax.axis("off")
        ax.text(0.5, 0.5, "No empirical covariance groups passed min_samples", ha="center", va="center")
        fig.savefig(out_dir / "fig_4_2_B_real_vs_theory_matrices.png", dpi=220)
        plt.close(fig)
        return
    wanted = [0.0, 60.0]
    chosen = []
    for theta in wanted:
        nearest_theta = float(df.iloc[(df["thetaDeg"] - theta).abs().argsort()].iloc[0]["thetaDeg"])
        sub = df[np.isclose(df["thetaDeg"].astype(float), nearest_theta)].copy()
        if not sub.empty:
            chosen.append(sub.sort_values("samples", ascending=False).iloc[0])
    unique = []
    seen = set()
    for row in chosen:
        key = (row["thetaDeg"], row["blockSize"], row["QP"], row["modeGroup"], row["transpose"], row["dim"])
        if key not in seen:
            unique.append(row)
            seen.add(key)
    if not unique:
        unique = [df.sort_values("samples", ascending=False).iloc[0]]

    fig, axes = plt.subplots(len(unique), 2, figsize=(5.8, 2.65 * len(unique)), constrained_layout=True)
    axes = np.asarray(axes).reshape(len(unique), 2)
    all_mats = []
    pairs = []
    for row in unique:
        width, height = int(row["W"]), int(row["H"])
        stem = f"theta{int(row['thetaDeg'])}_{width}x{height}_qp{int(row['QP'])}_mg{int(row['modeGroup'])}_tr{int(row['transpose'])}_d{int(row['dim'])}"
        emp = _unit_frobenius(matrices[f"emp_{stem}"])
        th = _unit_frobenius(matrices[f"theory_{stem}"])
        pairs.append((row, emp, th))
        all_mats.extend([emp, th])
    vmin, vmax = _matrix_range(all_mats)
    for row_idx, (row, emp, th) in enumerate(pairs):
        for col_idx, (mat, title) in enumerate([(emp, "empirical"), (th, "theory")]):
            ax = axes[row_idx, col_idx]
            im = ax.imshow(mat, cmap="RdBu_r", vmin=vmin, vmax=vmax, interpolation="nearest")
            ax.set_xticks([])
            ax.set_yticks([])
            if row_idx == 0:
                ax.set_title(title)
            if col_idx == 0:
                ax.set_ylabel(f"{row['latBin']}, {row['blockSize']}\nQP{int(row['QP'])}, mode {int(row['modeGroup'])}")
    fig.suptitle("Unit-Frobenius covariance structure")
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.78)
    fig.savefig(out_dir / "fig_4_2_B_real_vs_theory_matrices.png", dpi=260)
    fig.savefig(out_dir / "fig_4_2_B_real_vs_theory_matrices.pdf")
    plt.close(fig)


def _unit_frobenius(mat: np.ndarray) -> np.ndarray:
    return mat / (np.linalg.norm(mat, "fro") + EPS)


TheoryMatrices = mvstats.TheoryMatrices
diag_dominance = mvstats.diag_dominance
frobenius_cosine = mvstats.frobenius_cosine
offdiag_abs_mean_corr = mvstats.offdiag_abs_mean_corr
theory_matrices_for = mvstats.theory_matrices_for


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
    allowed_sizes = set(sizes)
    theory_by_key: dict[exp42.GroupKey, np.ndarray] = {}
    lfnst_by_key: dict[exp42.GroupKey, np.ndarray] = {}
    lfnst8, lfnst4, _, _ = parse_rom_lfnst(rom_lfnst)
    for key in empirical:
        if (key.w, key.h) not in allowed_sizes:
            continue
        theta = theta_values[min(max(key.lat_bin, 0), len(theta_values) - 1)]
        theory_by_key[key] = theory_matrices_for(
            key.w, key.h, theta, transpose=key.transpose
        ).Sigma_x[: key.k, : key.k]
        source = lfnst4 if key.k == 16 else lfnst8
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run experiment 4.2 covariance model validation.")
    parser.add_argument("--out-dir", type=Path, default=Path("lahtp_runs/covariance_model_validation_4_2"))
    parser.add_argument("--vec-log", action="append", default=[], help="LardLfnst2ndVecFile CSV path/glob. Repeatable.")
    parser.add_argument("--cov-log", action="append", default=[], help="LardLfnstCovLog CSV path/glob. Repeatable.")
    parser.add_argument("--sizes", default="4,8,16")
    parser.add_argument("--theta-values", default="0,30,60,75")
    parser.add_argument("--rho0", type=float, default=0.6)
    parser.add_argument("--rho-ver", type=float, default=0.6)
    parser.add_argument("--sigma-e2", type=float, default=1.0)
    parser.add_argument("--min-samples", type=int, default=64)
    parser.add_argument("--chunksize", type=int, default=200000)
    parser.add_argument("--skip-empirical", action="store_true")
    parser.add_argument("--formal-4-2", action="store_true", help="write formal Experiment 4.2 NCE/rank/top1/reliability metrics")
    parser.add_argument("--lambda-u", type=float, default=0.0)
    parser.add_argument("--rom-lfnst", type=Path, default=Path("source/Lib/CommonLib/Rom.cpp"))
    args = parser.parse_args()

    sizes = parse_sizes(args.sizes)
    theta_values = parse_float_list(args.theta_values)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    theory_result = run_theory_propagation(args.out_dir, sizes, theta_values, args.rho0, args.rho_ver, args.sigma_e2)
    print(f"4.2-A sizes={theory_result['sizes']} theta_values={theory_result['theta_values']}")

    if args.skip_empirical:
        return
    vec_logs = _resolve_inputs(args.vec_log or [DEFAULT_VEC_GLOB])
    if not vec_logs:
        print("4.2-B skipped: no vec-log inputs matched. Pass --vec-log <LardLfnst2ndVecFile.csv>.")
        return
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
    emp_result = run_empirical_validation(
        vec_logs=vec_logs,
        out_dir=args.out_dir,
        sizes=sizes,
        theta_values=theta_values,
        min_samples=args.min_samples,
        rho0=args.rho0,
        rho_ver=args.rho_ver,
        sigma_e2=args.sigma_e2,
        chunksize=args.chunksize,
        write_figures=True,
    )
    print(f"4.2-B vec_logs={len(vec_logs)} rows_seen={emp_result['rows_seen']} groups={emp_result['groups']}")
    print(f"out_dir={args.out_dir}")


if __name__ == "__main__":
    main()
