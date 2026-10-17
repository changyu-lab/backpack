#!/usr/bin/env python3
"""Strengthen A3 controlled-stretch analysis with paired deltas and CIs.

This script reuses the existing A3 VVenC intra-residual traces.  It builds a
cache of covariance statistics at the paired unit level:

  (sample_id, area_group, stretch_s)

and then reports paired deltas against s=1.00 with bootstrap confidence
intervals.  It also writes normalized ROI energy vectors and heatmaps so the
structural metrics are separated from total residual energy changes.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

EPS = 1.0e-12
BLOCK = 128
DEFAULT_STRETCHES = ["1.00", "1.15", "1.41", "2.00", "3.86", "5.00"]
METRICS = ["C_off", "rho_eig", "H0", "sigma_r2", "roi_energy_mean", "lf_roi_mean"]


class OnlineCov:
    def __init__(self) -> None:
        self.n = 0
        self.dim: int | None = None
        self.sum: np.ndarray | None = None
        self.sum_outer: np.ndarray | None = None
        self.energy_sum = 0.0
        self.lf_sum = 0.0

    def _set_dim(self, dim: int) -> None:
        if self.dim is None:
            self.dim = dim
            self.sum = np.zeros(dim, dtype=np.float64)
            self.sum_outer = np.zeros((dim, dim), dtype=np.float64)
            return
        if dim < self.dim:
            self.dim = dim
            assert self.sum is not None and self.sum_outer is not None
            self.sum = self.sum[:dim].copy()
            self.sum_outer = self.sum_outer[:dim, :dim].copy()

    def update(self, vec_in: np.ndarray) -> None:
        if vec_in.size <= 0:
            return
        self._set_dim(int(vec_in.size))
        assert self.dim is not None and self.sum is not None and self.sum_outer is not None
        vec = vec_in[: self.dim].astype(np.float64, copy=False)
        self.n += 1
        self.sum += vec
        self.sum_outer += np.outer(vec, vec)
        self.energy_sum += float(np.dot(vec, vec))
        self.lf_sum += lf_ratio(vec)

    def stats(self) -> dict[str, float]:
        if self.n < 2 or self.dim is None or self.sum is None or self.sum_outer is None:
            return {k: math.nan for k in METRICS}
        cov = (self.sum_outer - np.outer(self.sum, self.sum) / float(self.n)) / float(self.n - 1)
        fro = float(np.linalg.norm(cov, "fro"))
        off = cov.copy()
        np.fill_diagonal(off, 0.0)
        eig = np.maximum(np.linalg.eigvalsh(cov), 0.0)
        diag = np.maximum(np.diag(cov), 0.0)
        return {
            "C_off": float(np.linalg.norm(off, "fro") / (fro + EPS)),
            "rho_eig": float(np.max(eig) / (np.sum(eig) + EPS)),
            "H0": entropy_from_energy(diag),
            "sigma_r2": float(np.trace(cov) / max(1, self.dim)),
            "roi_energy_mean": self.energy_sum / float(self.n),
            "lf_roi_mean": self.lf_sum / float(self.n),
        }


class OnlineEnergy:
    def __init__(self) -> None:
        self.n = 0
        self.dim: int | None = None
        self.sum: np.ndarray | None = None

    def update(self, vec_in: np.ndarray) -> None:
        if vec_in.size <= 0:
            return
        dim = int(vec_in.size)
        if self.dim is None:
            self.dim = dim
            self.sum = np.zeros(dim, dtype=np.float64)
        elif dim < self.dim:
            self.dim = dim
            assert self.sum is not None
            self.sum = self.sum[:dim].copy()
        assert self.sum is not None and self.dim is not None
        vec = vec_in[: self.dim].astype(np.float64, copy=False)
        self.sum += vec * vec
        self.n += 1

    def mean(self) -> np.ndarray:
        if self.n <= 0 or self.sum is None:
            return np.zeros(0, dtype=np.float64)
        return self.sum / float(self.n)


def entropy_from_energy(energy: np.ndarray) -> float:
    total = float(np.sum(energy))
    if total <= EPS:
        return 0.0
    p = energy / total
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def roi_indices(dim: int) -> list[tuple[int, int, int]]:
    side = 4 if dim <= 16 else 8
    out: list[tuple[int, int, int]] = []
    idx = 0
    for v in range(side):
        for u in range(side):
            if side == 8 and u >= 4 and v >= 4:
                continue
            out.append((idx, u, v))
            idx += 1
    return out[:dim]


def lf_ratio(vec: np.ndarray) -> float:
    idxs = [idx for idx, u, v in roi_indices(vec.size) if u <= 1 and v <= 1]
    e = float(np.dot(vec, vec))
    return float(np.dot(vec[idxs], vec[idxs]) / (e + EPS)) if idxs else math.nan


def area_group(w: int, h: int) -> str:
    area = w * h
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
    return "area_large"


def f_int(row: dict[str, str], key: str, default: int = 0) -> int:
    val = row.get(key, "")
    if val == "":
        return default
    return int(float(val))


def f_float(row: dict[str, str], key: str, default: float = math.nan) -> float:
    val = row.get(key, "")
    if val == "":
        return default
    return float(val)


def s_token_to_key(token: str) -> str:
    return f"{float(token[1:].replace('p', '.')):.2f}"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        if not rows:
            raise ValueError(f"cannot infer header for empty CSV {path}")
        fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_sample_area_cache(args: argparse.Namespace) -> Path:
    out_dir = Path(args.out_dir)
    cache_path = out_dir / "metrics" / "table_a3_sample_area_cov_stats.csv"
    if cache_path.exists() and not args.force:
        return cache_path

    samples = load_csv(out_dir / "metadata" / "samples.csv")
    sample_by_tile = {
        (int(r["group_id"]), int(r["tile_row"]), int(r["tile_col"])): r["sample_id"]
        for r in samples
    }
    mosaics = load_csv(out_dir / "metadata" / "mosaics.csv")
    mosaic_by_key = {(f"{float(r['stretch_s']):.2f}", int(r["group_id"])): r for r in mosaics}

    covs: dict[tuple[str, str, str], OnlineCov] = {}
    energies: dict[str, OnlineEnergy] = {}
    trace_paths = sorted(out_dir.glob("encode/s*/g*/qp*/trace_a3_stretch_intra_residual.csv"))
    if args.limit_traces > 0:
        trace_paths = trace_paths[: args.limit_traces]

    for idx, trace in enumerate(trace_paths, 1):
        parts = trace.parts
        s_key = s_token_to_key(next(p for p in parts if p.startswith("s") and "p" in p))
        g_part = next(p for p in parts if p.startswith("g") and p[1:].isdigit())
        group_id = int(g_part[1:])
        ws = int(mosaic_by_key[(s_key, group_id)]["Ws"])
        if idx % 10 == 0 or idx == 1:
            print(f"[cache] {idx}/{len(trace_paths)} {trace}", flush=True)
        with trace.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            has_roi_raw = bool(reader.fieldnames and "roiRaw00" in reader.fieldnames)
            for row in reader:
                if f_int(row, "lfnstIdx") != 0 or f_int(row, "mtsIdx") != 0:
                    continue
                roi_dim = f_int(row, "roiDim", 0)
                if roi_dim <= 0:
                    continue
                prefix = "roiRaw" if has_roi_raw and row.get("roiRaw00", "") != "" else "roiQ"
                vals = [f_float(row, f"{prefix}{i:02d}") for i in range(min(roi_dim, 48))]
                if not vals or not all(math.isfinite(v) for v in vals):
                    continue
                vec = np.asarray(vals, dtype=np.float64)
                x, y, w, h = f_int(row, "x"), f_int(row, "y"), f_int(row, "w"), f_int(row, "h")
                col = int((x + 0.5 * w) // ws)
                tile_row = int((y + 0.5 * h) // BLOCK)
                sample_id = sample_by_tile.get((group_id, tile_row, col))
                if sample_id is None:
                    continue
                ag = area_group(w, h)
                key = (s_key, str(sample_id), ag)
                if key not in covs:
                    covs[key] = OnlineCov()
                covs[key].update(vec)
                if s_key not in energies:
                    energies[s_key] = OnlineEnergy()
                energies[s_key].update(vec)

    rows: list[dict[str, object]] = []
    for (s_key, sample_id, ag), acc in sorted(covs.items(), key=lambda item: (float(item[0][0]), int(item[0][1]), item[0][2])):
        st = acc.stats()
        if not all(math.isfinite(st[k]) for k in ["C_off", "rho_eig", "H0"]):
            continue
        row: dict[str, object] = {
            "stretch_s": s_key,
            "sample_id": int(sample_id),
            "area_group": ag,
            "n_blocks": acc.n,
        }
        row.update(st)
        rows.append(row)
    write_csv(cache_path, rows)

    energy_rows: list[dict[str, object]] = []
    norm_rows: list[dict[str, object]] = []
    for s_key, acc in sorted(energies.items(), key=lambda item: float(item[0])):
        mean = acc.mean()
        total = float(np.sum(mean))
        erow: dict[str, object] = {"stretch_s": s_key, "roiDim": int(mean.size), "n": acc.n}
        nrow: dict[str, object] = {"stretch_s": s_key, "roiDim": int(mean.size), "n": acc.n}
        for i, val in enumerate(mean):
            erow[f"e{i:02d}"] = float(val)
            nrow[f"e{i:02d}"] = float(val / (total + EPS))
        energy_rows.append(erow)
        norm_rows.append(nrow)
    write_csv(out_dir / "metrics" / "table_a3_roi_energy_vectors_from_cache.csv", energy_rows)
    write_csv(out_dir / "metrics" / "table_a3_normalized_roi_energy_vectors.csv", norm_rows)
    return cache_path


def bootstrap_mean(values: np.ndarray, rng: np.random.Generator, reps: int) -> tuple[float, float, float]:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return math.nan, math.nan, math.nan
    if values.size == 1 or reps <= 0:
        v = float(np.mean(values))
        return v, v, v
    idx = rng.integers(0, values.size, size=(reps, values.size))
    means = np.mean(values[idx], axis=1)
    return float(np.mean(values)), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def summarize(args: argparse.Namespace) -> None:
    if args.paired_unit == "group_area_mode":
        summarize_group_area_mode(args)
        return
    if args.paired_unit == "group_area":
        summarize_group_area(args)
        return

    out_dir = Path(args.out_dir)
    cache = build_sample_area_cache(args)
    rows = load_csv(cache)
    parsed: list[dict[str, object]] = []
    for r in rows:
        d: dict[str, object] = {
            "stretch_s": f"{float(r['stretch_s']):.2f}",
            "sample_id": int(r["sample_id"]),
            "area_group": r["area_group"],
            "n_blocks": int(r["n_blocks"]),
        }
        for m in METRICS:
            d[m] = float(r[m])
        parsed.append(d)

    by_key = {(r["stretch_s"], r["sample_id"], r["area_group"]): r for r in parsed}
    all_units = sorted({(int(r["sample_id"]), str(r["area_group"])) for r in parsed})
    stretches = [s for s in DEFAULT_STRETCHES if any(r["stretch_s"] == s for r in parsed)]
    common_units = [
        unit for unit in all_units
        if all((s, unit[0], unit[1]) in by_key for s in stretches)
    ]

    rng = np.random.default_rng(args.seed)
    raw_rows: list[dict[str, object]] = []
    delta_rows: list[dict[str, object]] = []
    for s in stretches:
        s_units = [unit for unit in common_units if (s, unit[0], unit[1]) in by_key]
        for area in sorted({u[1] for u in s_units}):
            units = [u for u in s_units if u[1] == area]
            if len(units) < args.min_units:
                continue
            raw: dict[str, object] = {"stretch_s": s, "area_group": area, "paired_units": len(units)}
            delt: dict[str, object] = {"stretch_s": s, "area_group": area, "paired_units": len(units)}
            for m in METRICS:
                vals = np.asarray([float(by_key[(s, u[0], u[1])][m]) for u in units], dtype=np.float64)
                mean, lo, hi = bootstrap_mean(vals, rng, args.bootstrap)
                raw[f"{m}_mean"] = mean
                raw[f"{m}_ci_low"] = lo
                raw[f"{m}_ci_high"] = hi
                deltas = np.asarray([float(by_key[(s, u[0], u[1])][m]) - float(by_key[("1.00", u[0], u[1])][m]) for u in units], dtype=np.float64)
                dmean, dlo, dhi = bootstrap_mean(deltas, rng, args.bootstrap)
                delt[f"delta_{m}_mean"] = dmean
                delt[f"delta_{m}_ci_low"] = dlo
                delt[f"delta_{m}_ci_high"] = dhi
            raw_rows.append(raw)
            delta_rows.append(delt)

        units = s_units
        if len(units) >= args.min_units:
            raw = {"stretch_s": s, "area_group": "all_common", "paired_units": len(units)}
            delt = {"stretch_s": s, "area_group": "all_common", "paired_units": len(units)}
            for m in METRICS:
                vals = np.asarray([float(by_key[(s, u[0], u[1])][m]) for u in units], dtype=np.float64)
                mean, lo, hi = bootstrap_mean(vals, rng, args.bootstrap)
                raw[f"{m}_mean"] = mean
                raw[f"{m}_ci_low"] = lo
                raw[f"{m}_ci_high"] = hi
                deltas = np.asarray([float(by_key[(s, u[0], u[1])][m]) - float(by_key[("1.00", u[0], u[1])][m]) for u in units], dtype=np.float64)
                dmean, dlo, dhi = bootstrap_mean(deltas, rng, args.bootstrap)
                delt[f"delta_{m}_mean"] = dmean
                delt[f"delta_{m}_ci_low"] = dlo
                delt[f"delta_{m}_ci_high"] = dhi
            raw_rows.append(raw)
            delta_rows.append(delt)

    write_csv(out_dir / "metrics" / "table_a3_paired_stats_by_s_size_bootstrap.csv", raw_rows)
    write_csv(out_dir / "metrics" / "table_a3_paired_delta_vs_s1_by_size_bootstrap.csv", delta_rows)
    write_csv(
        out_dir / "metrics" / "table_a3_paired_common_support_summary.csv",
        [
            {
                "stretches": " ".join(stretches),
                "all_sample_area_units": len(all_units),
                "common_sample_area_units": len(common_units),
                "bootstrap_reps": args.bootstrap,
                "paired_unit": "sample_id x area_group",
            }
        ],
    )
    make_plots(out_dir)


def update_cov(covs: dict[tuple[str, str, str], OnlineCov], key: tuple[str, str, str], vec: np.ndarray) -> None:
    if key not in covs:
        covs[key] = OnlineCov()
    covs[key].update(vec)


def build_group_area_cache_fast(args: argparse.Namespace) -> Path:
    """Build paired group-area covariance cache with low-overhead CSV parsing.

    Pairing by group controls the same 10 source samples across all stretch
    factors.  It does not require identical CU/TU partitioning after stretch.
    """
    out_dir = Path(args.out_dir)
    cache_path = out_dir / "metrics" / "table_a3_group_area_cov_stats.csv"
    if cache_path.exists() and not args.force:
        return cache_path

    covs: dict[tuple[str, str, str], OnlineCov] = {}
    energies: dict[str, OnlineEnergy] = {}
    trace_paths = sorted(out_dir.glob("encode/s*/g*/qp*/trace_a3_stretch_intra_residual.csv"))
    if args.limit_traces > 0:
        trace_paths = trace_paths[: args.limit_traces]

    for idx, trace in enumerate(trace_paths, 1):
        parts = trace.parts
        s_key = s_token_to_key(next(p for p in parts if p.startswith("s") and "p" in p))
        group_id = next(p for p in parts if p.startswith("g") and p[1:].isdigit())[1:]
        if idx % 5 == 0 or idx == 1:
            print(f"[group-cache] {idx}/{len(trace_paths)} {trace}", flush=True)
        with trace.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            header = fh.readline().strip().split(",")
            col = {name: i for i, name in enumerate(header)}
            need = ["w", "h", "lfnstIdx", "mtsIdx", "roiDim", "roiRaw00"]
            if any(n not in col for n in need):
                continue
            raw_cols = [col.get(f"roiRaw{i:02d}", -1) for i in range(48)]
            q_cols = [col.get(f"roiQ{i:02d}", -1) for i in range(48)]
            for line in fh:
                parts_line = line.rstrip("\n\r").split(",")
                try:
                    if int(float(parts_line[col["lfnstIdx"]])) != 0 or int(float(parts_line[col["mtsIdx"]])) != 0:
                        continue
                    roi_dim = int(float(parts_line[col["roiDim"]]))
                    if roi_dim <= 0:
                        continue
                    cols = raw_cols if raw_cols[0] >= 0 and parts_line[raw_cols[0]] != "" else q_cols
                    vals = [float(parts_line[cols[i]]) for i in range(min(roi_dim, 48)) if cols[i] >= 0]
                    if not vals:
                        continue
                    w = int(float(parts_line[col["w"]]))
                    h = int(float(parts_line[col["h"]]))
                except (ValueError, IndexError):
                    continue
                vec = np.asarray(vals, dtype=np.float64)
                ag = area_group(w, h)
                update_cov(covs, (s_key, group_id, ag), vec)
                if s_key not in energies:
                    energies[s_key] = OnlineEnergy()
                energies[s_key].update(vec)

    rows: list[dict[str, object]] = []
    for (s_key, group_id, ag), acc in sorted(covs.items(), key=lambda item: (float(item[0][0]), int(item[0][1]), item[0][2])):
        st = acc.stats()
        if not all(math.isfinite(st[k]) for k in ["C_off", "rho_eig", "H0"]):
            continue
        row: dict[str, object] = {
            "stretch_s": s_key,
            "group_id": int(group_id),
            "area_group": ag,
            "n_blocks": acc.n,
        }
        row.update(st)
        rows.append(row)
    write_csv(cache_path, rows)

    energy_rows: list[dict[str, object]] = []
    norm_rows: list[dict[str, object]] = []
    for s_key, acc in sorted(energies.items(), key=lambda item: float(item[0])):
        mean = acc.mean()
        total = float(np.sum(mean))
        erow: dict[str, object] = {"stretch_s": s_key, "roiDim": int(mean.size), "n": acc.n}
        nrow: dict[str, object] = {"stretch_s": s_key, "roiDim": int(mean.size), "n": acc.n}
        for i, val in enumerate(mean):
            erow[f"e{i:02d}"] = float(val)
            nrow[f"e{i:02d}"] = float(val / (total + EPS))
        energy_rows.append(erow)
        norm_rows.append(nrow)
    write_csv(out_dir / "metrics" / "table_a3_roi_energy_vectors_group_cache.csv", energy_rows)
    write_csv(out_dir / "metrics" / "table_a3_normalized_roi_energy_vectors.csv", norm_rows)
    return cache_path


def mode_group(mode: int) -> str:
    if mode < 0:
        return "unknown"
    if mode == 0:
        return "planar"
    if mode == 1:
        return "dc"
    if 2 <= mode <= 17:
        return "horizontalish"
    if 18 <= mode <= 49:
        return "diagonal"
    return "verticalish"


def build_group_area_mode_cache_fast(args: argparse.Namespace) -> Path:
    """Build covariance cache conditioned on sample group, size, and mode group."""
    out_dir = Path(args.out_dir)
    cache_path = out_dir / "metrics" / "table_a3_group_area_mode_cov_stats.csv"
    if cache_path.exists() and not args.force:
        return cache_path

    covs: dict[tuple[str, str, str, str], OnlineCov] = {}
    trace_paths = sorted(out_dir.glob("encode/s*/g*/qp*/trace_a3_stretch_intra_residual.csv"))
    if args.limit_traces > 0:
        trace_paths = trace_paths[: args.limit_traces]

    for idx, trace in enumerate(trace_paths, 1):
        parts = trace.parts
        s_key = s_token_to_key(next(p for p in parts if p.startswith("s") and "p" in p))
        group_id = next(p for p in parts if p.startswith("g") and p[1:].isdigit())[1:]
        if idx % 5 == 0 or idx == 1:
            print(f"[mode-cache] {idx}/{len(trace_paths)} {trace}", flush=True)
        with trace.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            header = fh.readline().strip().split(",")
            col = {name: i for i, name in enumerate(header)}
            need = ["w", "h", "lfnstIdx", "mtsIdx", "roiDim", "intraMode", "roiRaw00"]
            if any(n not in col for n in need):
                continue
            raw_cols = [col.get(f"roiRaw{i:02d}", -1) for i in range(48)]
            q_cols = [col.get(f"roiQ{i:02d}", -1) for i in range(48)]
            for line in fh:
                parts_line = line.rstrip("\n\r").split(",")
                try:
                    if int(float(parts_line[col["lfnstIdx"]])) != 0 or int(float(parts_line[col["mtsIdx"]])) != 0:
                        continue
                    roi_dim = int(float(parts_line[col["roiDim"]]))
                    if roi_dim <= 0:
                        continue
                    cols = raw_cols if raw_cols[0] >= 0 and parts_line[raw_cols[0]] != "" else q_cols
                    vals = [float(parts_line[cols[i]]) for i in range(min(roi_dim, 48)) if cols[i] >= 0]
                    if not vals:
                        continue
                    w = int(float(parts_line[col["w"]]))
                    h = int(float(parts_line[col["h"]]))
                    mode = int(float(parts_line[col["intraMode"]]))
                except (ValueError, IndexError):
                    continue
                vec = np.asarray(vals, dtype=np.float64)
                ag = area_group(w, h)
                mg = mode_group(mode)
                key = (s_key, group_id, ag, mg)
                if key not in covs:
                    covs[key] = OnlineCov()
                covs[key].update(vec)

    rows: list[dict[str, object]] = []
    for (s_key, group_id, ag, mg), acc in sorted(covs.items(), key=lambda item: (float(item[0][0]), int(item[0][1]), item[0][2], item[0][3])):
        st = acc.stats()
        if not all(math.isfinite(st[k]) for k in ["C_off", "rho_eig", "H0"]):
            continue
        row: dict[str, object] = {
            "stretch_s": s_key,
            "group_id": int(group_id),
            "area_group": ag,
            "modeGroup": mg,
            "n_blocks": acc.n,
        }
        row.update(st)
        rows.append(row)
    write_csv(cache_path, rows)
    return cache_path


def summarize_group_area(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    cache = build_group_area_cache_fast(args)
    rows = load_csv(cache)
    parsed: list[dict[str, object]] = []
    for r in rows:
        d: dict[str, object] = {
            "stretch_s": f"{float(r['stretch_s']):.2f}",
            "group_id": int(r["group_id"]),
            "area_group": r["area_group"],
            "n_blocks": int(r["n_blocks"]),
        }
        for m in METRICS:
            d[m] = float(r[m])
        parsed.append(d)

    by_key = {(r["stretch_s"], r["group_id"], r["area_group"]): r for r in parsed}
    stretches = [s for s in DEFAULT_STRETCHES if any(r["stretch_s"] == s for r in parsed)]
    all_units = sorted({(int(r["group_id"]), str(r["area_group"])) for r in parsed})
    common_units = [unit for unit in all_units if all((s, unit[0], unit[1]) in by_key for s in stretches)]
    rng = np.random.default_rng(args.seed)
    raw_rows: list[dict[str, object]] = []
    delta_rows: list[dict[str, object]] = []

    def add_rows(area: str, s: str, units: list[tuple[int, str]]) -> None:
        raw: dict[str, object] = {"stretch_s": s, "area_group": area, "paired_units": len(units), "paired_unit": "group_id x area_group"}
        delt: dict[str, object] = {"stretch_s": s, "area_group": area, "paired_units": len(units), "paired_unit": "group_id x area_group"}
        for m in METRICS:
            vals = np.asarray([float(by_key[(s, u[0], u[1])][m]) for u in units], dtype=np.float64)
            mean, lo, hi = bootstrap_mean(vals, rng, args.bootstrap)
            raw[f"{m}_mean"] = mean
            raw[f"{m}_ci_low"] = lo
            raw[f"{m}_ci_high"] = hi
            deltas = np.asarray([float(by_key[(s, u[0], u[1])][m]) - float(by_key[("1.00", u[0], u[1])][m]) for u in units], dtype=np.float64)
            dmean, dlo, dhi = bootstrap_mean(deltas, rng, args.bootstrap)
            delt[f"delta_{m}_mean"] = dmean
            delt[f"delta_{m}_ci_low"] = dlo
            delt[f"delta_{m}_ci_high"] = dhi
        raw_rows.append(raw)
        delta_rows.append(delt)

    for s in stretches:
        s_units = [unit for unit in common_units if (s, unit[0], unit[1]) in by_key]
        for area in sorted({u[1] for u in s_units}):
            units = [u for u in s_units if u[1] == area]
            if len(units) >= args.min_units:
                add_rows(area, s, units)
        if len(s_units) >= args.min_units:
            add_rows("all_common", s, s_units)

    write_csv(out_dir / "metrics" / "table_a3_paired_group_stats_by_s_size_bootstrap.csv", raw_rows)
    write_csv(out_dir / "metrics" / "table_a3_paired_group_delta_vs_s1_by_size_bootstrap.csv", delta_rows)
    write_csv(
        out_dir / "metrics" / "table_a3_paired_group_common_support_summary.csv",
        [
            {
                "stretches": " ".join(stretches),
                "all_group_area_units": len(all_units),
                "common_group_area_units": len(common_units),
                "bootstrap_reps": args.bootstrap,
                "paired_unit": "group_id x area_group",
            }
        ],
    )
    make_group_plots(out_dir)


def summarize_group_area_mode(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    cache = build_group_area_mode_cache_fast(args)
    rows = load_csv(cache)
    parsed: list[dict[str, object]] = []
    for r in rows:
        d: dict[str, object] = {
            "stretch_s": f"{float(r['stretch_s']):.2f}",
            "group_id": int(r["group_id"]),
            "area_group": r["area_group"],
            "modeGroup": r["modeGroup"],
            "n_blocks": int(r["n_blocks"]),
        }
        for m in METRICS:
            d[m] = float(r[m])
        parsed.append(d)

    by_key = {(r["stretch_s"], r["group_id"], r["area_group"], r["modeGroup"]): r for r in parsed}
    stretches = [s for s in DEFAULT_STRETCHES if any(r["stretch_s"] == s for r in parsed)]
    all_units = sorted({(int(r["group_id"]), str(r["area_group"]), str(r["modeGroup"])) for r in parsed})
    common_units = [unit for unit in all_units if all((s, unit[0], unit[1], unit[2]) in by_key for s in stretches)]
    rng = np.random.default_rng(args.seed)
    raw_rows: list[dict[str, object]] = []
    delta_rows: list[dict[str, object]] = []

    def add_rows(s: str, area: str, mode: str, units: list[tuple[int, str, str]]) -> None:
        raw: dict[str, object] = {
            "stretch_s": s,
            "area_group": area,
            "modeGroup": mode,
            "paired_units": len(units),
            "paired_unit": "group_id x area_group x modeGroup",
        }
        delt: dict[str, object] = dict(raw)
        for m in METRICS:
            vals = np.asarray([float(by_key[(s, u[0], u[1], u[2])][m]) for u in units], dtype=np.float64)
            mean, lo, hi = bootstrap_mean(vals, rng, args.bootstrap)
            raw[f"{m}_mean"] = mean
            raw[f"{m}_ci_low"] = lo
            raw[f"{m}_ci_high"] = hi
            deltas = np.asarray(
                [
                    float(by_key[(s, u[0], u[1], u[2])][m])
                    - float(by_key[("1.00", u[0], u[1], u[2])][m])
                    for u in units
                ],
                dtype=np.float64,
            )
            dmean, dlo, dhi = bootstrap_mean(deltas, rng, args.bootstrap)
            delt[f"delta_{m}_mean"] = dmean
            delt[f"delta_{m}_ci_low"] = dlo
            delt[f"delta_{m}_ci_high"] = dhi
        raw_rows.append(raw)
        delta_rows.append(delt)

    for s in stretches:
        s_units = [unit for unit in common_units if (s, unit[0], unit[1], unit[2]) in by_key]
        # Fully conditioned cells.
        for area in sorted({u[1] for u in s_units}):
            for mode in sorted({u[2] for u in s_units if u[1] == area}):
                units = [u for u in s_units if u[1] == area and u[2] == mode]
                if len(units) >= args.min_units:
                    add_rows(s, area, mode, units)
        # Size-controlled, mode-standardized common aggregate.
        for area in sorted({u[1] for u in s_units}):
            units = [u for u in s_units if u[1] == area]
            if len(units) >= args.min_units:
                add_rows(s, area, "all_common_modes", units)
        # Overall size+mode controlled aggregate.
        if len(s_units) >= args.min_units:
            add_rows(s, "all_common_sizes", "all_common_modes", s_units)

    write_csv(out_dir / "metrics" / "table_a3_paired_group_area_mode_stats_bootstrap.csv", raw_rows)
    write_csv(out_dir / "metrics" / "table_a3_paired_group_area_mode_delta_vs_s1_bootstrap.csv", delta_rows)
    write_csv(
        out_dir / "metrics" / "table_a3_paired_group_area_mode_common_support_summary.csv",
        [
            {
                "stretches": " ".join(stretches),
                "all_group_area_mode_units": len(all_units),
                "common_group_area_mode_units": len(common_units),
                "bootstrap_reps": args.bootstrap,
                "paired_unit": "group_id x area_group x modeGroup",
            }
        ],
    )
    make_group_area_mode_plots(out_dir)


def make_group_area_mode_plots(out_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    rows = read_table(out_dir / "metrics" / "table_a3_paired_group_area_mode_delta_vs_s1_bootstrap.csv")

    # Plot size-controlled, mode-standardized curves.
    areas = ["area_16", "area_32", "area_64", "area_256", "area_1024", "area_large", "all_common_sizes"]
    plt.figure(figsize=(8.2, 4.8))
    for area in areas:
        rs = [r for r in rows if r["area_group"] == area and r["modeGroup"] == "all_common_modes"]
        if not rs:
            continue
        rs.sort(key=lambda r: float(r["stretch_s"]))
        x = np.asarray([float(r["stretch_s"]) for r in rs], dtype=np.float64)
        y = np.asarray([float(r["delta_C_off_mean"]) for r in rs], dtype=np.float64)
        lo = np.asarray([float(r["delta_C_off_ci_low"]) for r in rs], dtype=np.float64)
        hi = np.asarray([float(r["delta_C_off_ci_high"]) for r in rs], dtype=np.float64)
        plt.errorbar(x, y, yerr=np.vstack([y - lo, hi - y]), marker="o", capsize=3, label=area)
    plt.axhline(0.0, color="black", linewidth=0.8)
    plt.xlabel("stretchS")
    plt.ylabel("Delta C_off vs s=1.00")
    plt.title("Paired A3 delta conditioned on size and mode group")
    plt.grid(alpha=0.25)
    plt.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plt.savefig(fig_dir / "fig_a3_paired_delta_Coff_size_mode_controlled.png", dpi=180)
    plt.close()

    # Plot fully conditioned mode curves for medium area groups.
    for area in ["area_32", "area_64", "area_256"]:
        plt.figure(figsize=(8.2, 4.8))
        for mode in ["planar", "dc", "horizontalish", "diagonal", "verticalish"]:
            rs = [r for r in rows if r["area_group"] == area and r["modeGroup"] == mode]
            if not rs:
                continue
            rs.sort(key=lambda r: float(r["stretch_s"]))
            x = np.asarray([float(r["stretch_s"]) for r in rs], dtype=np.float64)
            y = np.asarray([float(r["delta_C_off_mean"]) for r in rs], dtype=np.float64)
            lo = np.asarray([float(r["delta_C_off_ci_low"]) for r in rs], dtype=np.float64)
            hi = np.asarray([float(r["delta_C_off_ci_high"]) for r in rs], dtype=np.float64)
            plt.errorbar(x, y, yerr=np.vstack([y - lo, hi - y]), marker="o", capsize=3, label=mode)
        plt.axhline(0.0, color="black", linewidth=0.8)
        plt.xlabel("stretchS")
        plt.ylabel("Delta C_off vs s=1.00")
        plt.title(f"Paired A3 delta by mode group, {area}")
        plt.grid(alpha=0.25)
        plt.legend(fontsize=8, ncol=2)
        plt.tight_layout()
        plt.savefig(fig_dir / f"fig_a3_paired_delta_Coff_by_mode_{area}.png", dpi=180)
        plt.close()


def make_group_plots(out_dir: Path) -> None:
    # Reuse plotting code by copying group table to the generic filename
    group_delta = out_dir / "metrics" / "table_a3_paired_group_delta_vs_s1_by_size_bootstrap.csv"
    generic_delta = out_dir / "metrics" / "table_a3_paired_delta_vs_s1_by_size_bootstrap.csv"
    generic_stats = out_dir / "metrics" / "table_a3_paired_stats_by_s_size_bootstrap.csv"
    group_stats = out_dir / "metrics" / "table_a3_paired_group_stats_by_s_size_bootstrap.csv"
    generic_delta.write_text(group_delta.read_text(encoding="utf-8"), encoding="utf-8")
    generic_stats.write_text(group_stats.read_text(encoding="utf-8"), encoding="utf-8")
    make_plots(out_dir)


def read_table(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def metric_ci(row: dict[str, str], prefix: str) -> tuple[float, float, float]:
    return float(row[f"{prefix}_mean"]), float(row[f"{prefix}_ci_low"]), float(row[f"{prefix}_ci_high"])


def make_plots(out_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    delta = read_table(out_dir / "metrics" / "table_a3_paired_delta_vs_s1_by_size_bootstrap.csv")
    areas = ["area_16", "area_32", "area_64", "area_256", "area_1024", "area_large", "all_common"]
    for metric in ["C_off", "rho_eig", "H0"]:
        plt.figure(figsize=(8.0, 4.8))
        for area in areas:
            rows = [r for r in delta if r["area_group"] == area]
            if not rows:
                continue
            rows.sort(key=lambda r: float(r["stretch_s"]))
            x = np.asarray([float(r["stretch_s"]) for r in rows], dtype=np.float64)
            y = np.asarray([float(r[f"delta_{metric}_mean"]) for r in rows], dtype=np.float64)
            lo = np.asarray([float(r[f"delta_{metric}_ci_low"]) for r in rows], dtype=np.float64)
            hi = np.asarray([float(r[f"delta_{metric}_ci_high"]) for r in rows], dtype=np.float64)
            plt.errorbar(x, y, yerr=np.vstack([y - lo, hi - y]), marker="o", capsize=3, label=area)
        plt.axhline(0.0, color="black", linewidth=0.8)
        plt.xlabel("stretchS")
        plt.ylabel(f"Delta {metric} vs s=1.00")
        plt.grid(alpha=0.25)
        plt.legend(fontsize=8, ncol=2)
        plt.tight_layout()
        plt.savefig(fig_dir / f"fig_a3_paired_delta_{metric}_vs_s1_by_size.png", dpi=180)
        plt.close()

    norm_path = out_dir / "metrics" / "table_a3_normalized_roi_energy_vectors.csv"
    if norm_path.exists():
        norm = read_table(norm_path)
        fig, axes = plt.subplots(1, len(norm), figsize=(2.25 * len(norm), 2.5), squeeze=False)
        for ax, row in zip(axes[0], sorted(norm, key=lambda r: float(r["stretch_s"]))):
            dim = int(row["roiDim"])
            vals = np.asarray([float(row[f"e{i:02d}"]) for i in range(dim)], dtype=np.float64)
            side = 4 if dim <= 16 else 8
            mat = np.full((side, side), np.nan, dtype=np.float64)
            for idx, u, v in roi_indices(dim):
                mat[v, u] = vals[idx]
            im = ax.imshow(mat, cmap="viridis")
            ax.set_title(f"s={float(row['stretch_s']):.2f}")
            ax.set_xticks([])
            ax.set_yticks([])
        fig.colorbar(im, ax=axes.ravel().tolist(), fraction=0.025, pad=0.02)
        fig.savefig(fig_dir / "fig_a3_normalized_roi_energy_maps.png", dpi=180, bbox_inches="tight")
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="lahtp_runs/a3_controlled_stretch_intra")
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260602)
    parser.add_argument("--min-units", type=int, default=10)
    parser.add_argument("--limit-traces", type=int, default=0, help="debug only: limit number of original trace files")
    parser.add_argument("--paired-unit", choices=["group_area", "group_area_mode", "sample_area"], default="group_area")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    summarize(args)


if __name__ == "__main__":
    main()
