#!/usr/bin/env python3
"""Fit quantized-ROI LFNST candidate pruning table from updated trace blocks."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


USECOLS = [
    "w", "h", "qp", "intraMode", "absLatDeg", "roiEnergyQ", "lfRatio",
    "n0dct2", "last0dct2", "corrProxy", "j0", "j1", "j2",
]


def size_group(w: np.ndarray, h: np.ndarray) -> np.ndarray:
    area = w * h
    mn = np.minimum(w, h)
    mx = np.maximum(w, h)
    return np.select([area <= 16, area <= 32, area <= 64, area <= 256, area <= 1024, mx >= 4 * mn],
                     [0, 1, 2, 3, 4, 6], default=5).astype(np.int16)


def mode_group(mode: np.ndarray) -> np.ndarray:
    return np.select([mode == 0, mode == 1, mode <= 17, mode <= 34, mode <= 50],
                     [0, 1, 2, 3, 4], default=5).astype(np.int16)


def lat_bucket(abs_lat: np.ndarray) -> np.ndarray:
    return np.select([abs_lat < 30, abs_lat < 50, abs_lat < 70], [0, 1, 2], default=3).astype(np.int16)


def nz_bucket(nz: np.ndarray) -> np.ndarray:
    return np.select([nz <= 0.5, nz <= 2, nz <= 4, nz <= 8, nz <= 16], [0, 1, 2, 3, 4], default=5).astype(np.int16)


def last_bucket(last: np.ndarray) -> np.ndarray:
    return np.select([last <= 0, last <= 3, last <= 7, last <= 15, last <= 31], [0, 1, 2, 3, 4], default=5).astype(np.int16)


def roi_bucket(roi: np.ndarray) -> np.ndarray:
    return np.select([roi <= 0.5, roi <= 2, roi <= 8, roi <= 32, roi <= 128], [0, 1, 2, 3, 4], default=5).astype(np.int16)


def lf_bucket(lf: np.ndarray) -> np.ndarray:
    return np.select([lf < 0.25, lf < 0.5, lf < 0.75], [0, 1, 2], default=3).astype(np.int16)


def corr_bucket(corr: np.ndarray) -> np.ndarray:
    return np.select([corr < 0.10, corr < 0.25, corr < 0.50, corr < 1.00], [0, 1, 2, 3], default=4).astype(np.int16)


def pack_key(qp: int, sg: int, mg: int, lb: int, nb: int, tb: int, rb: int, fb: int, cb: int) -> int:
    return ((((((((qp * 7 + sg) * 6 + mg) * 4 + lb) * 6 + nb) * 6 + tb) * 6 + rb) * 4 + fb) * 5 + cb)


def iter_chunks(paths: list[Path], chunksize: int):
    for path in paths:
        for df in pd.read_csv(path, usecols=USECOLS, chunksize=chunksize):
            for col in USECOLS:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            valid = (
                np.isfinite(df["j0"]) & np.isfinite(df["j1"]) & np.isfinite(df["j2"]) &
                (df["j0"] > 0) & (np.abs(df["j0"]) < 1.0e100) &
                (np.abs(df["j1"]) < 1.0e100) & (np.abs(df["j2"]) < 1.0e100) &
                (df["n0dct2"] >= 0) & (df["last0dct2"] >= 0) &
                np.isfinite(df["corrProxy"]) & np.isfinite(df["roiEnergyQ"]) & np.isfinite(df["lfRatio"])
            )
            df = df[valid]
            if len(df):
                yield df


def aggregate(paths: list[Path], chunksize: int, coarse: str) -> dict[tuple[int, ...], np.ndarray]:
    agg: dict[tuple[int, ...], np.ndarray] = defaultdict(lambda: np.zeros(12, dtype=np.float64))
    for df in iter_chunks(paths, chunksize):
        sg = size_group(df["w"].to_numpy(np.int32), df["h"].to_numpy(np.int32))
        mg = mode_group(df["intraMode"].to_numpy(np.int32))
        lb = lat_bucket(df["absLatDeg"].to_numpy(np.float64))
        nb = nz_bucket(df["n0dct2"].to_numpy(np.float64))
        tb = last_bucket(df["last0dct2"].to_numpy(np.float64))
        rb = roi_bucket(df["roiEnergyQ"].to_numpy(np.float64))
        fb = lf_bucket(df["lfRatio"].to_numpy(np.float64))
        cb = corr_bucket(df["corrProxy"].to_numpy(np.float64))
        j0 = df["j0"].to_numpy(np.float64)
        j1 = df["j1"].to_numpy(np.float64)
        j2 = df["j2"].to_numpy(np.float64)
        costs = np.stack([j0, j1, j2], axis=1)
        best = np.argmin(costs, axis=1)
        bestc = costs[np.arange(len(df)), best]
        denom = np.maximum(j0, 1.0)
        loss1 = np.maximum(0.0, (j0 - bestc) / denom)
        loss3 = np.maximum(0.0, (np.minimum(j0, j1) - bestc) / denom)
        loss5 = np.maximum(0.0, (np.minimum(j0, j2) - bestc) / denom)
        tmp = pd.DataFrame({
            "qp": df["qp"].to_numpy(np.int16), "sg": sg, "mg": mg, "lb": lb,
            "nb": nb, "tb": tb, "rb": rb, "fb": fb, "cb": cb, "n": 1,
            "c0": (best == 0).astype(np.int8), "c1": (best == 1).astype(np.int8),
            "c2": (best == 2).astype(np.int8), "l1": loss1, "l3": loss3, "l5": loss5,
            "g1": (j0 - j1) / denom, "g2": (j0 - j2) / denom,
        })
        group_cols = ["qp", "sg", "mg", "lb", "nb", "tb"] if coarse == "no_roi" else ["qp", "sg", "mg", "lb", "nb", "tb", "rb", "fb", "cb"]
        grouped = tmp.groupby(group_cols, sort=False).sum(numeric_only=True)
        for key, row in grouped.iterrows():
            a = agg[key]
            a[0] += row["n"]
            a[1] += row["c0"]
            a[2] += row["c1"]
            a[3] += row["c2"]
            a[4] += row["l1"]
            a[5] += row["l3"]
            a[6] += row["l5"]
            a[7] += row["g1"]
            a[8] += row["g2"]
            a[9] += max(row["g1"], 0.0)
            a[10] += max(row["g2"], 0.0)
            a[11] += 1
    return agg


def choose_mask(a: np.ndarray, max_mean_loss: float, max_false_rate: float) -> int:
    n, _c0, c1, c2, loss1, loss3, loss5 = a[:7]
    candidates = [(1, 2, loss1, c1 + c2), (3, 1, loss3, c2), (5, 1, loss5, c1), (7, 0, 0.0, 0.0)]
    best = (0, -math.inf, 7)
    for mask, saved, loss, false_count in candidates:
        if false_count / n <= max_false_rate and loss / n <= max_mean_loss:
            best = max(best, (saved, -loss, mask))
    return best[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("block_csv", nargs="+", type=Path)
    ap.add_argument("--include-out", type=Path, required=True)
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--csv-out", type=Path)
    ap.add_argument("--chunksize", type=int, default=250000)
    ap.add_argument("--min-samples", type=int, default=50)
    ap.add_argument("--max-mean-loss", type=float, default=5.0e-5)
    ap.add_argument("--max-false-rate", type=float, default=0.01)
    ap.add_argument("--coarse", choices=("full", "no_roi"), default="full")
    args = ap.parse_args()

    agg = aggregate(args.block_csv, args.chunksize, args.coarse)
    rows = []
    masks: Counter[int] = Counter()
    def expanded_keys(key: tuple[int, ...]) -> list[tuple[int, int, int, int, int, int, int, int, int]]:
        if args.coarse == "full":
            return [key]  # type: ignore[list-item]
        qp, sg, mg, lb, nb, tb = key
        return [(qp, sg, mg, lb, nb, tb, rb, fb, cb) for rb in range(6) for fb in range(4) for cb in range(5)]

    for key, a in sorted(agg.items(), key=lambda kv: min(pack_key(*k) for k in expanded_keys(kv[0]))):
        n = int(a[0])
        if n < args.min_samples:
            continue
        mask = choose_mask(a, args.max_mean_loss, args.max_false_rate)
        for ex_key in expanded_keys(key):
            row = {
                "key": pack_key(*ex_key),
                "mask": mask,
                "samples": n,
                "meanGain1": float(a[7] / a[0]),
                "meanGain2": float(a[8] / a[0]),
            }
            rows.append(row)
        masks[mask] += 1

    with args.include_out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("// Generated by tools/lard_lfnst_fit_quant_candidate_table.py\n")
        fh.write(f"// minSamples={args.min_samples}, maxMeanLoss={args.max_mean_loss:g}, maxFalseRate={args.max_false_rate:g}, coarse={args.coarse}, sourceFiles={len(args.block_csv)}\n")
        fh.write("// Key: qp,size,mode,lat,n0,last0,roiEnergy,lfRatio,corrProxy\n")
        fh.write("// Fields: packedKey, mask, meanGain1, meanGain2\n")
        for row in rows:
            fh.write("  { %d, %d, %.9g, %.9g },\n" % (row["key"], row["mask"], row["meanGain1"], row["meanGain2"]))

    summary = {
        "entries": len(rows),
        "sourceFiles": len(args.block_csv),
        "minSamples": args.min_samples,
        "maxMeanLoss": args.max_mean_loss,
        "maxFalseRate": args.max_false_rate,
        "coarse": args.coarse,
        "maskCounts": dict(sorted(masks.items())),
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.csv_out:
        with args.csv_out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["key", "mask", "samples", "meanGain1", "meanGain2"])
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
