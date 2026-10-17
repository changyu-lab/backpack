#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

EPS = 1e-12
SPEC_COLS = [f"spec{i:02d}" for i in range(64)]


@dataclass
class Acc:
    samples: int = 0
    energy: np.ndarray = field(default_factory=lambda: np.zeros(64, dtype=np.float64))


def parse_case(path: Path) -> tuple[str, float, int]:
    m = re.search(r"(train|validation)_s([0-9p.]+)_qp(\d+)$", path.stem, re.I)
    if not m:
        raise RuntimeError(f"bad trace name: {path}")
    return m.group(1).lower(), float(m.group(2).replace("p", ".")), int(m.group(3))


def trace_files(run_root: Path) -> list[Path]:
    trace_dir = run_root / "traces" if (run_root / "traces").is_dir() else run_root
    return sorted(p for p in trace_dir.glob("*_s*_qp*.csv") if not p.name.endswith(".final.csv") and p.stat().st_size > 0)


def load_manifest_buckets(manifest_dir: Path) -> dict[str, dict[int, str]]:
    out = {}
    for split in ("train", "validation"):
        path = manifest_dir / f"sjtu_{split}_patch256_manifest.csv"
        rows = {}
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows[int(r["patchIndex"])] = r.get("latitudeBucket") or bucket(abs(float(r["sourceLatitudeDeg"])))
        out[split] = rows
    return out


def bucket(lat: float) -> str:
    if lat < 30:
        return "[0,30)"
    if lat < 60:
        return "[30,60)"
    if lat < 75:
        return "[60,75)"
    return "[75,90]"


def active_mask(side: int) -> np.ndarray:
    mask = np.zeros(64, dtype=bool)
    if side == 4:
        for v in range(4):
            for u in range(4):
                mask[v * 8 + u] = True
    else:
        for v in range(8):
            for u in range(8):
                if not (u >= 4 and v >= 4):
                    mask[v * 8 + u] = True
    return mask


def distribution(acc: Acc, side: int) -> tuple[np.ndarray, np.ndarray]:
    mask = active_mask(side)
    e = np.maximum(acc.energy.copy(), 0.0)
    e[~mask] = 0.0
    p = e / (float(e.sum()) + EPS)
    return p, mask


def entropy(p: np.ndarray, mask: np.ndarray) -> float:
    q = p[mask]
    return float(-np.sum(q * np.log(q + EPS)))


def adir(p: np.ndarray, mask: np.ndarray) -> tuple[float, float, float]:
    mx = my = 0.0
    for v in range(8):
        for u in range(8):
            idx = v * 8 + u
            if mask[idx]:
                mx += u * u * float(p[idx])
                my += v * v * float(p[idx])
    return float((my - mx) / (my + mx + EPS)), mx, my


def js(p: np.ndarray, q: np.ndarray, mask: np.ndarray) -> float:
    pp = p[mask]
    qq = q[mask]
    mm = 0.5 * (pp + qq)
    return float(0.5 * np.sum(pp * (np.log(pp + EPS) - np.log(mm + EPS))) + 0.5 * np.sum(qq * (np.log(qq + EPS) - np.log(mm + EPS))))


def size_group(area: pd.Series, mn: pd.Series, mx: pd.Series) -> pd.Series:
    out = np.full(len(area), "area_large", dtype=object)
    out[area <= 1024] = "area_1024"
    out[area <= 256] = "area_256"
    out[area <= 64] = "area_64"
    out[area <= 32] = "area_32"
    out[area <= 16] = "area_16"
    out[(area > 1024) & (mx >= 4 * mn)] = "area_long"
    return pd.Series(out, index=area.index)


def mode_group(mode: pd.Series) -> pd.Series:
    out = np.full(len(mode), "g5_ang_51_plus", dtype=object)
    out[mode <= 50] = "g4_ang_35_50"
    out[mode <= 34] = "g3_ang_18_34"
    out[mode <= 17] = "g2_ang_2_17"
    out[mode == 1] = "g1_dc"
    out[mode == 0] = "g0_planar"
    return pd.Series(out, index=mode.index)


def analyze(run_root: Path, manifest_dir: Path, out_dir: Path, chunksize: int) -> dict[str, int]:
    manifest_buckets = load_manifest_buckets(manifest_dir)
    usecols = ["poc", "x", "y", "w", "h", "intraMode", "lfnstIdx", "mtsIdx", "specSide"] + SPEC_COLS
    acc: dict[tuple[str, float, int, str, str, str, int], Acc] = defaultdict(Acc)
    rows_seen = used = 0
    files = trace_files(run_root)
    for file_idx, trace in enumerate(files, 1):
        split, stretch, qp = parse_case(trace)
        lat_map = manifest_buckets[split]
        for df in pd.read_csv(trace, usecols=usecols, chunksize=chunksize, low_memory=False):
            rows_seen += len(df)
            df = df[(df["lfnstIdx"] == 0) & (df["mtsIdx"] == 0) & df["spec00"].notna()]
            if df.empty:
                continue
            tile_x = ((df["x"].astype(np.int64) + 0.5 * df["w"].astype(np.int64)) // 128).clip(0, 3).astype(np.int64)
            tile_y = ((df["y"].astype(np.int64) + 0.5 * df["h"].astype(np.int64)) // 128).clip(0, 3).astype(np.int64)
            patch_idx = (df["poc"].astype(np.int64) * 16 + tile_y * 4 + tile_x).astype(np.int64)
            df = df.assign(
                Split=split,
                StretchS=stretch,
                QP=qp,
                LatitudeBucket=patch_idx.map(lat_map),
                BlockSizeGroup=size_group(df["w"] * df["h"], np.minimum(df["w"], df["h"]), np.maximum(df["w"], df["h"])),
                ModeGroup=mode_group(df["intraMode"]),
            ).dropna(subset=["LatitudeBucket"])
            used += len(df)
            grouped = df.groupby(["Split", "StretchS", "QP", "LatitudeBucket", "BlockSizeGroup", "ModeGroup", "specSide"], sort=False)[SPEC_COLS].sum()
            counts = df.groupby(["Split", "StretchS", "QP", "LatitudeBucket", "BlockSizeGroup", "ModeGroup", "specSide"], sort=False).size()
            for key, sums in grouped.iterrows():
                k = (key[0], float(key[1]), int(key[2]), key[3], key[4], key[5], int(key[6]))
                acc[k].samples += int(counts.loc[key])
                acc[k].energy += sums.to_numpy(dtype=np.float64)
        print(f"[A1] {file_idx}/{len(files)} {trace.name} rows={rows_seen} used={used}", flush=True)

    pmap = {}
    rows = []
    for key, a in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3], kv[0][4], kv[0][5], kv[0][6])):
        p, mask = distribution(a, key[6])
        d, mx, my = adir(p, mask)
        pmap[key] = (p, mask)
        row = {
            "Split": key[0], "StretchS": key[1], "QP": key[2], "LatitudeBucket": key[3],
            "BlockSizeGroup": key[4], "ModeGroup": key[5], "SpecSide": key[6], "Samples": a.samples,
            "H0": entropy(p, mask), "A_dir": d, "M_x": mx, "M_y": my,
        }
        for i in range(64):
            if mask[i]:
                row[f"p{i:02d}"] = float(p[i])
        rows.append(row)
    for row in rows:
        key = (row["Split"], float(row["StretchS"]), int(row["QP"]), row["LatitudeBucket"], row["BlockSizeGroup"], row["ModeGroup"], int(row["SpecSide"]))
        low = (key[0], key[1], key[2], "[0,30)", key[4], key[5], key[6])
        row["D_JS_to_lowlat"] = 0.0 if key[3] == "[0,30)" else (js(pmap[key][0], pmap[low][0], pmap[key][1]) if low in pmap else math.nan)

    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ["Split", "StretchS", "QP", "LatitudeBucket", "BlockSizeGroup", "ModeGroup", "SpecSide", "Samples", "H0", "A_dir", "M_x", "M_y", "D_JS_to_lowlat"] + [f"p{i:02d}" for i in range(64)]
    with (out_dir / "table_A1_lowfreq_distribution.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    sum_acc = defaultdict(lambda: {"Samples": 0.0, "H0": 0.0, "A_dir": 0.0, "D_JS": 0.0, "D_JS_samples": 0.0})
    for r in rows:
        k = (r["Split"], r["StretchS"], r["QP"], r["LatitudeBucket"], r["BlockSizeGroup"])
        n = float(r["Samples"])
        a = sum_acc[k]
        a["Samples"] += n
        a["H0"] += float(r["H0"]) * n
        a["A_dir"] += float(r["A_dir"]) * n
        if math.isfinite(float(r["D_JS_to_lowlat"])):
            a["D_JS"] += float(r["D_JS_to_lowlat"]) * n
            a["D_JS_samples"] += n
    with (out_dir / "table_A1_summary_by_lat_size.csv").open("w", newline="", encoding="utf-8") as fh:
        cols2 = ["Split", "StretchS", "QP", "LatitudeBucket", "BlockSizeGroup", "Samples", "Mean_H0", "Mean_A_dir", "Mean_D_JS_to_lowlat"]
        w = csv.DictWriter(fh, fieldnames=cols2)
        w.writeheader()
        for k, a in sorted(sum_acc.items(), key=lambda kv: (kv[0][0], float(kv[0][1]), int(kv[0][2]), kv[0][3], kv[0][4])):
            n = a["Samples"]
            w.writerow({"Split": k[0], "StretchS": k[1], "QP": k[2], "LatitudeBucket": k[3], "BlockSizeGroup": k[4], "Samples": int(n), "Mean_H0": a["H0"] / n, "Mean_A_dir": a["A_dir"] / n, "Mean_D_JS_to_lowlat": a["D_JS"] / a["D_JS_samples"] if a["D_JS_samples"] else math.nan})

    (out_dir / "A1_projection_geometry_report.md").write_text(
        "\n".join([
            "# Experiment A1 Projection Geometry Low-Frequency Redistribution",
            "",
            f"Trace files: `{len(files)}`",
            f"Rows scanned: `{rows_seen}`",
            f"No-LFNST primary spectrum rows used: `{used}`",
            f"Distribution groups: `{len(rows)}`",
            "",
            "Computed from no-LFNST primary `spec00..spec63` squared coefficient energy.",
            "`D_JS_to_lowlat` is matched by split, stretch, QP, block-size group, mode group, and specSide.",
        ]) + "\n",
        encoding="utf-8",
    )
    return {"trace_files": len(files), "rows_seen": rows_seen, "used": used, "groups": len(rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--manifest-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--chunksize", type=int, default=200000)
    args = ap.parse_args()
    print(analyze(args.run_root, args.manifest_dir, args.out_dir, args.chunksize))


if __name__ == "__main__":
    main()
