#!/usr/bin/env python3
"""A3 controlled horizontal-stretch experiment with VVenC intra residual traces.

The experiment samples ordinary 2D YUV pixels, stretches the same source blocks
horizontally, encodes the synthetic mosaics with VVenC AI, and analyzes the
signed no-LFNST DCT ROI vectors traced from intra-prediction residuals.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


DEFAULT_SOURCES = [
    "BasketballDrill_832x480_50.yuv",
    "BQMall_832x480_60.yuv",
    "BasketballDrive_1920x1080_50.yuv",
    "Cactus_1920x1080_50.yuv",
]
DEFAULT_STRETCHES = [1.00, 1.15, 1.41, 2.00, 3.86, 5.00]
DEFAULT_SMOKE_STRETCHES = [1.00, 2.00]
BLOCK = 128
GROUP_SIZE = 10
TILE_COLS = 5
TILE_ROWS = 2
EPS = 1.0e-12


@dataclass(frozen=True)
class SourceInfo:
    name: str
    path: Path
    width: int
    height: int
    fps: int
    frames: int


def parse_source_info(path: Path) -> SourceInfo:
    m = re.search(r"_(\d+)x(\d+)_(\d+)", path.name)
    if not m:
        raise ValueError(f"cannot parse width/height/fps from {path.name}")
    width, height, fps = map(int, m.groups())
    frame_size = width * height * 3 // 2
    frames = path.stat().st_size // frame_size
    if frames <= 0:
        raise ValueError(f"{path} is too small for {width}x{height} yuv420")
    return SourceInfo(path.stem, path, width, height, fps, int(frames))


def s_token(s: float) -> str:
    return f"{s:.2f}".replace(".", "p")


def ws_for_s(s: float, block: int = BLOCK) -> int:
    return int(8 * round((s * block) / 8))


def read_yuv420_frame(src: SourceInfo, frame_idx: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame_idx %= src.frames
    y_size = src.width * src.height
    uv_size = (src.width // 2) * (src.height // 2)
    frame_size = y_size + 2 * uv_size
    with src.path.open("rb") as fh:
        fh.seek(frame_idx * frame_size)
        raw = fh.read(frame_size)
    data = np.frombuffer(raw, dtype=np.uint8)
    if data.size != frame_size:
        raise RuntimeError(f"short frame from {src.path}: got {data.size}, expected {frame_size}")
    y = data[:y_size].reshape(src.height, src.width)
    u = data[y_size : y_size + uv_size].reshape(src.height // 2, src.width // 2)
    v = data[y_size + uv_size :].reshape(src.height // 2, src.width // 2)
    return y, u, v


def resize_horiz_linear(plane: np.ndarray, out_w: int) -> np.ndarray:
    h, in_w = plane.shape
    if out_w == in_w:
        return plane.copy()
    if out_w <= 1:
        raise ValueError("out_w must be > 1")
    src_x = np.linspace(0.0, in_w - 1, out_w, dtype=np.float64)
    x0 = np.floor(src_x).astype(np.int64)
    x1 = np.minimum(x0 + 1, in_w - 1)
    t = src_x - x0
    out = plane[:, x0].astype(np.float64) * (1.0 - t)[None, :] + plane[:, x1].astype(np.float64) * t[None, :]
    return np.rint(out).clip(0, 255).astype(np.uint8)


def stretch_patch(y: np.ndarray, u: np.ndarray, v: np.ndarray, ws: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return resize_horiz_linear(y, ws), resize_horiz_linear(u, ws // 2), resize_horiz_linear(v, ws // 2)


def load_samples(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and fieldnames is None:
        raise ValueError(f"cannot infer header for empty CSV {path}")
    names = fieldnames if fieldnames is not None else list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def prepare_samples(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    source_root = Path(args.source_root)
    sources = [parse_source_info(source_root / name) for name in args.sources]
    rows: list[dict[str, object]] = []
    for sample_id in range(args.samples):
        src = sources[sample_id % len(sources)]
        max_frame = max(1, src.frames - args.frames)
        start = rng.randrange(max_frame)
        x = rng.randrange(0, (src.width - args.block) // 2 + 1) * 2
        y = rng.randrange(0, (src.height - args.block) // 2 + 1) * 2
        group = sample_id // args.group_size
        group_idx = sample_id % args.group_size
        row = group_idx // args.tile_cols
        col = group_idx % args.tile_cols
        rows.append(
            {
                "sample_id": sample_id,
                "source_name": src.name,
                "source_path": str(src.path),
                "source_width": src.width,
                "source_height": src.height,
                "source_fps": src.fps,
                "start_frame": start,
                "source_x": x,
                "source_y": y,
                "block": args.block,
                "frames": args.frames,
                "group_id": group,
                "tile_row": row,
                "tile_col": col,
            }
        )
    write_csv(Path(args.out_dir) / "metadata" / "samples.csv", rows)


def make_mosaics(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    samples_path = out_dir / "metadata" / "samples.csv"
    samples = load_samples(samples_path)
    src_cache = {row["source_path"]: parse_source_info(Path(row["source_path"])) for row in samples}
    stretches = [float(s) for s in args.stretches]
    group_count = max(int(row["group_id"]) for row in samples) + 1
    manifest_rows: list[dict[str, object]] = []

    for s in stretches:
        ws = ws_for_s(s, args.block)
        width = args.tile_cols * ws
        height = args.tile_rows * args.block
        sdir = out_dir / "mosaics" / f"s{s_token(s)}"
        sdir.mkdir(parents=True, exist_ok=True)
        by_group: dict[int, list[dict[str, str]]] = {g: [] for g in range(group_count)}
        for row in samples:
            by_group[int(row["group_id"])].append(row)

        for group_id in range(group_count):
            path = sdir / f"a3_s{s_token(s)}_g{group_id:03d}_{width}x{height}_f{args.frames}.yuv"
            with path.open("wb") as fh:
                for frame_off in range(args.frames):
                    y_frame = np.zeros((height, width), dtype=np.uint8)
                    u_frame = np.full((height // 2, width // 2), 128, dtype=np.uint8)
                    v_frame = np.full((height // 2, width // 2), 128, dtype=np.uint8)
                    for row in by_group[group_id]:
                        src = src_cache[row["source_path"]]
                        yy, uu, vv = read_yuv420_frame(src, int(row["start_frame"]) + frame_off)
                        sx, sy = int(row["source_x"]), int(row["source_y"])
                        py = yy[sy : sy + args.block, sx : sx + args.block]
                        pu = uu[sy // 2 : (sy + args.block) // 2, sx // 2 : (sx + args.block) // 2]
                        pv = vv[sy // 2 : (sy + args.block) // 2, sx // 2 : (sx + args.block) // 2]
                        py, pu, pv = stretch_patch(py, pu, pv, ws)
                        ox = int(row["tile_col"]) * ws
                        oy = int(row["tile_row"]) * args.block
                        y_frame[oy : oy + args.block, ox : ox + ws] = py
                        u_frame[oy // 2 : (oy + args.block) // 2, ox // 2 : (ox + ws) // 2] = pu
                        v_frame[oy // 2 : (oy + args.block) // 2, ox // 2 : (ox + ws) // 2] = pv
                    fh.write(y_frame.tobytes())
                    fh.write(u_frame.tobytes())
                    fh.write(v_frame.tobytes())

            manifest_rows.append(
                {
                    "stretch_s": f"{s:.2f}",
                    "s_eff": f"{ws / args.block:.6f}",
                    "Ws": ws,
                    "group_id": group_id,
                    "width": width,
                    "height": height,
                    "frames": args.frames,
                    "mosaic_yuv": str(path),
                }
            )
    write_csv(out_dir / "metadata" / "mosaics.csv", manifest_rows)


def run_one(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(" ".join(cmd) + "\n\n")
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed with {proc.returncode}: {' '.join(cmd)}; see {log_path}")


def encode(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    vvenc = Path(args.vvenc)
    mosaics = load_samples(out_dir / "metadata" / "mosaics.csv")
    wanted = {f"{float(s):.2f}" for s in args.stretches} if args.stretches else None
    for row in mosaics:
        s = f"{float(row['stretch_s']):.2f}"
        if wanted and s not in wanted:
            continue
        group_id = int(row["group_id"])
        enc_dir = out_dir / "encode" / f"s{s_token(float(s))}" / f"g{group_id:03d}" / f"qp{args.qp}"
        bitstream = enc_dir / "stream.vvc"
        recon = enc_dir / "recon.yuv"
        trace = enc_dir / "trace_a3_stretch_intra_residual.csv"
        log = enc_dir / "vvenc.log"
        if trace.exists() and trace.stat().st_size > 1024 and not args.force:
            continue
        cmd = [
            str(vvenc),
            "-i",
            row["mosaic_yuv"],
            "-s",
            f"{row['width']}x{row['height']}",
            "-f",
            row["frames"],
            "-fr",
            str(args.frame_rate),
            "--preset",
            args.preset,
            "-q",
            str(args.qp),
            "-b",
            str(bitstream),
            "-o",
            str(recon),
            "--InputBitDepth",
            "8",
            "--OutputBitDepth",
            "8",
            "--PerceptQPA",
            "0",
            "--TargetBitrate",
            "0",
            "--IntraPeriod",
            "1",
            "--GOPSize",
            "1",
            "--LardLfnstSkip",
            "0",
            "--LardLfnstTraceFile",
            str(trace),
        ]
        try:
            run_one(cmd, log)
        except RuntimeError:
            if trace.exists() and trace.stat().st_size > 1024:
                with log.open("a", encoding="utf-8", errors="replace") as fh:
                    fh.write("\n[A3] vvenc returned non-zero, but trace is non-empty; accepting trace-only point.\n")
            else:
                raise
        if args.delete_recon and recon.exists():
            recon.unlink()
        if bitstream.exists() and bitstream.stat().st_size == 0:
            bitstream.unlink()


def f_float(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def f_int(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def mode_group(mode: int) -> str:
    if mode == 0:
        return "planar"
    if mode == 1:
        return "dc"
    if 2 <= mode <= 18:
        return "angular_low"
    if 19 <= mode <= 50:
        return "angular_mid"
    return "angular_high"


def area_group(w: int, h: int) -> str:
    a = w * h
    if a <= 16:
        return "area_16"
    if a <= 32:
        return "area_32"
    if a <= 64:
        return "area_64"
    if a <= 256:
        return "area_256"
    if a <= 1024:
        return "area_1024"
    return "area_large"


def roi_indices(roi_dim: int) -> list[tuple[int, int, int]]:
    side = 4 if roi_dim <= 16 else 8
    out = []
    idx = 0
    for v in range(side):
        for u in range(side):
            if side == 8 and u >= 4 and v >= 4:
                continue
            out.append((idx, u, v))
            idx += 1
    return out[:roi_dim]


def lf_ratio(vec: np.ndarray) -> float:
    idxs = [idx for idx, u, v in roi_indices(vec.size) if u <= 1 and v <= 1]
    e = float(np.dot(vec, vec))
    return float(np.dot(vec[idxs], vec[idxs]) / (e + EPS)) if idxs else math.nan


def entropy_from_energy(energy: np.ndarray) -> float:
    total = float(np.sum(energy))
    if total <= EPS:
        return 0.0
    p = energy / total
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def cov_stats(vectors: list[np.ndarray]) -> dict[str, float]:
    if len(vectors) < 2:
        return {
            "C_off": math.nan,
            "rho_eig": math.nan,
            "H0": math.nan,
            "sigma_r2": math.nan,
            "roi_energy_mean": math.nan,
            "lf_roi_mean": math.nan,
        }
    dim = min(v.size for v in vectors)
    x = np.stack([v[:dim] for v in vectors]).astype(np.float64)
    cov = np.cov(x, rowvar=False, bias=False)
    cov = np.atleast_2d(cov)
    fro = float(np.linalg.norm(cov, "fro"))
    off = cov.copy()
    np.fill_diagonal(off, 0.0)
    eig = np.linalg.eigvalsh(cov)
    eig = np.maximum(eig, 0.0)
    diag = np.maximum(np.diag(cov), 0.0)
    return {
        "C_off": float(np.linalg.norm(off, "fro") / (fro + EPS)),
        "rho_eig": float(np.max(eig) / (np.sum(eig) + EPS)),
        "H0": entropy_from_energy(diag),
        "sigma_r2": float(np.trace(cov) / max(1, dim)),
        "roi_energy_mean": float(np.mean(np.sum(x * x, axis=1))),
        "lf_roi_mean": float(np.mean([lf_ratio(v[:dim]) for v in vectors])),
    }


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
            return {
                "C_off": math.nan,
                "rho_eig": math.nan,
                "H0": math.nan,
                "sigma_r2": math.nan,
                "roi_energy_mean": math.nan,
                "lf_roi_mean": math.nan,
            }
        cov = (self.sum_outer - np.outer(self.sum, self.sum) / float(self.n)) / float(self.n - 1)
        fro = float(np.linalg.norm(cov, "fro"))
        off = cov.copy()
        np.fill_diagonal(off, 0.0)
        eig = np.linalg.eigvalsh(cov)
        eig = np.maximum(eig, 0.0)
        diag = np.maximum(np.diag(cov), 0.0)
        return {
            "C_off": float(np.linalg.norm(off, "fro") / (fro + EPS)),
            "rho_eig": float(np.max(eig) / (np.sum(eig) + EPS)),
            "H0": entropy_from_energy(diag),
            "sigma_r2": float(np.trace(cov) / max(1, self.dim)),
            "roi_energy_mean": self.energy_sum / float(self.n),
            "lf_roi_mean": self.lf_sum / float(self.n),
        }


class OnlineEnergyMean:
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
        assert self.dim is not None and self.sum is not None
        self.sum += vec_in[: self.dim] * vec_in[: self.dim]
        self.n += 1

    def mean(self) -> np.ndarray:
        if self.n <= 0 or self.sum is None:
            return np.zeros(0, dtype=np.float64)
        return self.sum / float(self.n)


def update_group(groups: dict[tuple[str, ...], OnlineCov], key: Iterable[object], vec: np.ndarray) -> None:
    k = tuple(str(v) for v in key)
    if k not in groups:
        groups[k] = OnlineCov()
    groups[k].update(vec)


def analyze(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    mosaics = load_samples(out_dir / "metadata" / "mosaics.csv")
    mosaic_by_key = {(f"{float(r['stretch_s']):.2f}", int(r["group_id"])): r for r in mosaics}
    sample_rows = load_samples(out_dir / "metadata" / "samples.csv")
    sample_by_tile = {
        (int(r["group_id"]), int(r["tile_row"]), int(r["tile_col"])): r
        for r in sample_rows
    }
    raw_groups: dict[tuple[str, ...], OnlineCov] = {}
    mode_groups: dict[tuple[str, ...], OnlineCov] = {}
    energy_maps: dict[str, OnlineEnergyMean] = {}
    vec_fields = ["stretch_s", "s_eff", "Ws", "qp", "group_id", "sample_id", "poc", "x", "y", "local_x", "local_y", "w", "h", "block_size", "area_group", "intraMode", "modeGroup", "roiDim", "roi_source", "roi_energy", "lf_roi_ratio", "corrProxy"]
    vec_path = out_dir / "metrics" / "trace_a3_roi_vectors.csv"
    vec_path.parent.mkdir(parents=True, exist_ok=True)
    vec_fh = vec_path.open("w", newline="", encoding="utf-8")
    vec_writer = csv.DictWriter(vec_fh, fieldnames=vec_fields)
    vec_writer.writeheader()

    trace_paths = sorted(out_dir.glob("encode/s*/g*/qp*/trace_a3_stretch_intra_residual.csv"))
    for trace in trace_paths:
        parts = trace.parts
        s_part = next(p for p in parts if p.startswith("s") and "p" in p)
        g_part = next(p for p in parts if p.startswith("g") and p[1:].isdigit())
        qp_part = next(p for p in parts if p.startswith("qp") and p[2:].isdigit())
        s = float(s_part[1:].replace("p", "."))
        s_key = f"{s:.2f}"
        group_id = int(g_part[1:])
        qp = int(qp_part[2:])
        meta = mosaic_by_key[(s_key, group_id)]
        ws = int(meta["Ws"])
        with trace.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if f_int(row, "lfnstIdx") != 0 or f_int(row, "mtsIdx") != 0:
                    continue
                roi_dim = f_int(row, "roiDim", 0)
                if roi_dim <= 0:
                    continue
                source_prefix = "roiRaw" if "roiRaw00" in row and row.get("roiRaw00", "") != "" else "roiQ"
                vals = [f_float(row, f"{source_prefix}{i:02d}") for i in range(min(roi_dim, 48))]
                if not vals or not all(math.isfinite(v) for v in vals):
                    continue
                vec = np.asarray(vals, dtype=np.float64)
                x = f_int(row, "x")
                y = f_int(row, "y")
                w = f_int(row, "w")
                h = f_int(row, "h")
                col = int((x + 0.5 * w) // ws)
                tile_row = int((y + 0.5 * h) // args.block)
                sample = sample_by_tile.get((group_id, tile_row, col))
                if sample is None:
                    continue
                mode = f_int(row, "intraMode")
                mg = mode_group(mode)
                ag = area_group(w, h)
                block_size = f"{w}x{h}"
                roi_energy = float(np.dot(vec, vec))
                lf = lf_ratio(vec)
                vec_writer.writerow(
                    {
                        "stretch_s": f"{s:.2f}",
                        "s_eff": f"{ws / args.block:.6f}",
                        "Ws": ws,
                        "qp": qp,
                        "group_id": group_id,
                        "sample_id": sample["sample_id"],
                        "poc": f_int(row, "poc"),
                        "x": x,
                        "y": y,
                        "local_x": x - col * ws,
                        "local_y": y - tile_row * args.block,
                        "w": w,
                        "h": h,
                        "block_size": block_size,
                        "area_group": ag,
                        "intraMode": mode,
                        "modeGroup": mg,
                        "roiDim": roi_dim,
                        "roi_source": source_prefix,
                        "roi_energy": roi_energy,
                        "lf_roi_ratio": lf,
                        "corrProxy": f_float(row, "corrProxy"),
                    }
                )
                update_group(raw_groups, [s_key], vec)
                update_group(raw_groups, [s_key, ag], vec)
                update_group(raw_groups, [s_key, block_size], vec)
                update_group(mode_groups, [s_key, mg], vec)
                if s_key not in energy_maps:
                    energy_maps[s_key] = OnlineEnergyMean()
                energy_maps[s_key].update(vec)
    vec_fh.close()

    def group_table(groups: dict[tuple[str, ...], OnlineCov], labels: list[str]) -> list[dict[str, object]]:
        out = []
        for key, acc in sorted(groups.items()):
            stats = acc.stats()
            row = {label: key[i] for i, label in enumerate(labels)}
            row.update({"n": acc.n})
            row.update(stats)
            out.append(row)
        return out

    by_s = group_table({k: v for k, v in raw_groups.items() if len(k) == 1}, ["stretch_s"])
    by_s_size = group_table({k: v for k, v in raw_groups.items() if len(k) == 2 and k[1].startswith("area_")}, ["stretch_s", "area_group"])
    by_mode = group_table(mode_groups, ["stretch_s", "modeGroup"])
    write_csv(out_dir / "metrics" / "table_a3_controlled_stretch_stats_by_s.csv", by_s)
    write_csv(out_dir / "metrics" / "table_a3_controlled_stretch_stats_by_s_size.csv", by_s_size)
    write_csv(out_dir / "metrics" / "table_a3_mode_controlled_stats.csv", by_mode)

    base = {r["area_group"]: r for r in by_s_size if r["stretch_s"] == "1.00"}
    delta_rows = []
    for row in by_s_size:
        b = base.get(row["area_group"])
        if not b:
            continue
        d = dict(row)
        for key in ["C_off", "rho_eig", "H0", "sigma_r2", "roi_energy_mean", "lf_roi_mean"]:
            d[f"delta_{key}_vs_s1"] = float(row[key]) - float(b[key])
        delta_rows.append(d)
    write_csv(out_dir / "metrics" / "table_a3_delta_vs_s1_by_size.csv", delta_rows)

    # Store mean ROI energy maps for plotting without re-reading the full trace.
    maps_rows = []
    for s_key, acc in sorted(energy_maps.items()):
        mean = acc.mean()
        dim = int(mean.size)
        row = {"stretch_s": s_key, "roiDim": dim}
        for i, value in enumerate(mean):
            row[f"e{i:02d}"] = float(value)
        maps_rows.append(row)
    write_csv(out_dir / "metrics" / "table_a3_mean_roi_energy_vectors.csv", maps_rows)


def read_float_table(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def plot(args: argparse.Namespace) -> None:
    import matplotlib.pyplot as plt

    out_dir = Path(args.out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    by_s = read_float_table(out_dir / "metrics" / "table_a3_controlled_stretch_stats_by_s.csv")
    by_size = read_float_table(out_dir / "metrics" / "table_a3_controlled_stretch_stats_by_s_size.csv")
    mode = read_float_table(out_dir / "metrics" / "table_a3_mode_controlled_stats.csv")
    maps = read_float_table(out_dir / "metrics" / "table_a3_mean_roi_energy_vectors.csv")

    def line_plot(metric: str, name: str) -> None:
        plt.figure(figsize=(7, 4.4))
        for ag in sorted({r["area_group"] for r in by_size}):
            rows = sorted([r for r in by_size if r["area_group"] == ag], key=lambda r: float(r["stretch_s"]))
            if not rows:
                continue
            plt.plot([float(r["stretch_s"]) for r in rows], [float(r[metric]) for r in rows], marker="o", label=ag)
        plt.xlabel("horizontal stretch factor s")
        plt.ylabel(metric)
        plt.grid(True, alpha=0.25)
        plt.legend(fontsize=8)
        plt.tight_layout()
        plt.savefig(fig_dir / name, dpi=200)
        plt.close()

    line_plot("C_off", "fig_a3_Coff_vs_stretchS_by_size.png")
    line_plot("rho_eig", "fig_a3_rhoeig_vs_stretchS_by_size.png")
    line_plot("H0", "fig_a3_H0_vs_stretchS_by_size.png")

    plt.figure(figsize=(7, 4.4))
    rows = sorted(by_s, key=lambda r: float(r["stretch_s"]))
    for metric in ["C_off", "rho_eig", "H0"]:
        vals = np.asarray([float(r[metric]) for r in rows], dtype=np.float64)
        vals = vals / (vals[0] if abs(vals[0]) > EPS else 1.0)
        plt.plot([float(r["stretch_s"]) for r in rows], vals, marker="o", label=f"{metric} / s1")
    plt.xlabel("horizontal stretch factor s")
    plt.ylabel("normalized raw metric")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "fig_a3_raw_metric_curves.png", dpi=200)
    plt.close()

    common_modes = sorted({r["modeGroup"] for r in mode})
    mode_rows = []
    for s in sorted({r["stretch_s"] for r in mode}, key=float):
        rs = [r for r in mode if r["stretch_s"] == s and r["modeGroup"] in common_modes and int(r["n"]) >= args.min_mode_n]
        if rs:
            mode_rows.append({"stretch_s": s, "C_off": np.mean([float(r["C_off"]) for r in rs]), "rho_eig": np.mean([float(r["rho_eig"]) for r in rs]), "H0": np.mean([float(r["H0"]) for r in rs])})
    if mode_rows:
        plt.figure(figsize=(7, 4.4))
        for metric in ["C_off", "rho_eig", "H0"]:
            raw = np.asarray([float(r[metric]) for r in rows], dtype=np.float64)
            ctrl = np.asarray([float(r[metric]) for r in mode_rows], dtype=np.float64)
            plt.plot([float(r["stretch_s"]) for r in rows], raw / (raw[0] if abs(raw[0]) > EPS else 1.0), marker="o", label=f"raw {metric}")
            plt.plot([float(r["stretch_s"]) for r in mode_rows], ctrl / (ctrl[0] if abs(ctrl[0]) > EPS else 1.0), marker="x", linestyle="--", label=f"mode {metric}")
        plt.xlabel("horizontal stretch factor s")
        plt.ylabel("normalized metric")
        plt.grid(True, alpha=0.25)
        plt.legend(fontsize=7, ncol=2)
        plt.tight_layout()
        plt.savefig(fig_dir / "fig_a3_raw_vs_mode_controlled_curves.png", dpi=200)
        plt.close()

    fig, axes = plt.subplots(1, len(maps), figsize=(2.2 * len(maps), 2.4), squeeze=False)
    for ax, row in zip(axes[0], sorted(maps, key=lambda r: float(r["stretch_s"]))):
        dim = int(row["roiDim"])
        side = 4 if dim <= 16 else 8
        mat = np.full((side, side), np.nan, dtype=np.float64)
        for idx, u, v in roi_indices(dim):
            mat[v, u] = float(row[f"e{idx:02d}"])
        im = ax.imshow(np.log10(mat + EPS), cmap="magma")
        ax.set_title(f"s={float(row['stretch_s']):.2f}")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.75, label="log10 mean ROI energy")
    fig.savefig(fig_dir / "fig_a3_same_sample_roi_energy_maps.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def run_pipeline(args: argparse.Namespace) -> None:
    prepare_samples(args)
    make_mosaics(args)
    encode(args)
    analyze(args)
    plot(args)


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out-dir", default="lahtp_runs/a3_controlled_stretch_intra")
    p.add_argument("--source-root", default="I:/HEVC-test")
    p.add_argument("--sources", nargs="+", default=DEFAULT_SOURCES)
    p.add_argument("--samples", type=int, default=200)
    p.add_argument("--frames", type=int, default=1)
    p.add_argument("--block", type=int, default=BLOCK)
    p.add_argument("--group-size", type=int, default=GROUP_SIZE)
    p.add_argument("--tile-cols", type=int, default=TILE_COLS)
    p.add_argument("--tile-rows", type=int, default=TILE_ROWS)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--stretches", nargs="*", type=float, default=DEFAULT_STRETCHES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ["prepare", "mosaic", "analyze", "plot", "run-full", "run-smoke"]:
        p = sub.add_parser(name)
        add_common(p)
        if name in {"run-smoke"}:
            p.set_defaults(samples=10, stretches=DEFAULT_SMOKE_STRETCHES, out_dir="lahtp_runs/a3_controlled_stretch_intra_smoke")
        if name in {"encode", "run-full", "run-smoke"}:
            pass

    enc = sub.add_parser("encode")
    add_common(enc)

    for p in [enc, sub.choices["run-full"], sub.choices["run-smoke"]]:
        p.add_argument("--vvenc", default="I:/vvenc-LFNST/bin/release-static/vvencFFapp.exe")
        p.add_argument("--qp", type=int, default=32)
        p.add_argument("--frame-rate", type=int, default=50)
        p.add_argument("--preset", default="medium")
        p.add_argument("--force", action="store_true")
        p.add_argument("--delete-recon", action="store_true", default=True)

    for p in [sub.choices["plot"], sub.choices["run-full"], sub.choices["run-smoke"]]:
        p.add_argument("--min-mode-n", type=int, default=20)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "prepare":
        prepare_samples(args)
    elif args.cmd == "mosaic":
        make_mosaics(args)
    elif args.cmd == "encode":
        encode(args)
    elif args.cmd == "analyze":
        analyze(args)
    elif args.cmd == "plot":
        plot(args)
    elif args.cmd in {"run-full", "run-smoke"}:
        run_pipeline(args)
    else:
        parser.error(f"unknown command {args.cmd}")


if __name__ == "__main__":
    main()
