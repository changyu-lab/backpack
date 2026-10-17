#!/usr/bin/env python3
"""Fit bucket-level Coff and risk-constrained second-response LFNST score tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def size_group(w: int, h: int) -> int:
    area = w * h
    mn = min(w, h)
    mx = max(w, h)
    if area <= 16:
        return 0
    if area <= 32:
        return 1
    if area <= 64:
        return 2
    if area <= 256:
        return 3
    if area <= 1024:
        return 4
    return 6 if mx >= 4 * mn else 5


def lat_bucket(x: float) -> int:
    return 0 if x < 30.0 else 1 if x < 50.0 else 2 if x < 70.0 else 3


def qstep(qp: int) -> float:
    return 2.0 ** ((max(0, min(63, qp)) - 4.0) / 6.0)


def energy_bucket(x: float) -> int:
    for i, th in enumerate((0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0,
                            64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0)):
        if x <= th:
            return i
    return 15


def nz_bucket(nz: int) -> int:
    return 0 if nz <= 0 else 1 if nz <= 2 else 2 if nz <= 4 else 3 if nz <= 8 else 4 if nz <= 16 else 5


def last_bucket(last: int) -> int:
    return 0 if last <= 0 else 1 if last <= 3 else 2 if last <= 7 else 3 if last <= 15 else 4 if last <= 31 else 5


def obs_bucket(x: float) -> int:
    return 0 if x <= -1000.0 else 1 if x <= -250.0 else 2 if x <= 0.0 else 3 if x <= 50.0 else 4 if x <= 250.0 else 5 if x <= 1000.0 else 6


def coff_bucket(x: float) -> int:
    return 0 if x < 0.05 else 1 if x < 0.10 else 2 if x < 0.15 else 3 if x < 0.20 else 4 if x < 0.30 else 5


def coff_key(qp: int, sg: int, mg: int, lb: int, lset: int, sbc: int, cb: int, eb: int) -> int:
    return ((((((qp * 7 + sg) * 6 + mg) * 4 + lb) * 4 + max(0, min(3, lset))) * 2 + max(0, min(1, sbc))) * 32 + max(0, min(31, cb))) * 16 + eb


def score_key(qp: int, sg: int, mg: int, lb: int, lset: int, sbc: int, cb: int, eb: int, nb: int, tb: int, cof_b: int, ob: int) -> int:
    return ((((((((((qp * 7 + sg) * 6 + mg) * 4 + lb) * 4 + max(0, min(3, lset))) * 2 + max(0, min(1, sbc))) * 32 + max(0, min(31, cb))) * 16 + eb) * 6 + nb) * 6 + tb) * 6 + cof_b) * 7 + ob


def read_float(row: dict[str, str], name: str) -> float:
    v = float(row[name])
    if not math.isfinite(v):
        raise ValueError(name)
    return v


class CorrAgg:
    def __init__(self, dim: int):
        self.dim = dim
        self.n = 0
        self.sum = np.zeros(dim, dtype=np.float64)
        self.outer = np.zeros((dim, dim), dtype=np.float64)

    def add(self, x: np.ndarray) -> None:
        self.n += 1
        self.sum += x
        self.outer += np.outer(x, x)

    def coff(self) -> float:
        if self.n < 2 or self.dim <= 1:
            return 0.0
        mean = self.sum / self.n
        cov = self.outer / self.n - np.outer(mean, mean)
        var = np.maximum(np.diag(cov), 0.0)
        std = np.sqrt(var)
        denom = np.outer(std, std)
        valid = denom > 1.0e-12
        corr = np.zeros_like(cov)
        corr[valid] = cov[valid] / denom[valid]
        corr = np.clip(corr, -1.0, 1.0)
        off = np.abs(corr).sum() - np.abs(np.diag(corr)).sum()
        return float(off / (self.dim * (self.dim - 1)))


def iter_rows(paths: list[Path]):
    for path in paths:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if "x00" not in reader.fieldnames:
                raise SystemExit(f"{path} has no ROI vector columns; rerun final stats with the updated encoder")
            for row in reader:
                yield row


def row_features(row: dict[str, str]):
    qp = int(float(row["qp"]))
    w = int(float(row["w"]))
    h = int(float(row["h"]))
    tr_size = int(float(row["trSize"]))
    sb_size = int(float(row["sbSize"]))
    qs = qstep(qp)
    energy_norm = read_float(row, "inputEnergy") / (tr_size * qs * qs + 1.0e-9)
    return (
        qp,
        size_group(w, h),
        int(float(row["modeGroup"])),
        lat_bucket(float(row["thetaMaxDeg"])),
        int(float(row["lfnstSet"])),
        1 if sb_size > 4 else 0,
        int(float(row["dct2CostBin"])),
        energy_bucket(energy_norm),
        tr_size,
        qs,
    )


def valid_costs(row: dict[str, str]):
    c0 = read_float(row, "cost0")
    c1 = read_float(row, "cost1")
    c2 = read_float(row, "cost2")
    if c0 <= 0.0 or abs(c0) >= 1.0e100 or abs(c1) >= 1.0e100 or abs(c2) >= 1.0e100:
        return None
    return c0, c1, c2


def choose_mask(a, alpha: float, beta: float, gamma: float) -> int:
    n = a["n"]
    candidates = (
        (1, 2, a["loss1"], a["max1"], a["miss1"]),
        (3, 1, a["loss3"], a["max3"], a["miss3"]),
        (5, 1, a["loss5"], a["max5"], a["miss5"]),
        (7, 0, 0.0, 0.0, 0),
    )
    best = (0, float("-inf"), 7)
    for mask, saved, loss, max_loss, miss in candidates:
        if miss / n <= alpha and loss / n <= beta and max_loss <= gamma:
            best = max(best, (saved, -loss, mask))
    return best[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("final_csv", nargs="+", type=Path)
    ap.add_argument("--score-out", type=Path, default=Path("source/Lib/EncoderLib/LardLfnst2ndScoreTable.inc"))
    ap.add_argument("--coff-out", type=Path, default=Path("source/Lib/EncoderLib/LardLfnst2ndCoffTable.inc"))
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--csv-out", type=Path)
    ap.add_argument("--min-coff-samples", type=int, default=20)
    ap.add_argument("--min-score-samples", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=0.08)
    ap.add_argument("--beta", type=float, default=0.001)
    ap.add_argument("--gamma", type=float, default=0.02)
    ap.add_argument("--obs-gate", type=float, default=250.0)
    args = ap.parse_args()

    corr_aggs: dict[int, CorrAgg] = {}
    total_rows = 0
    for row in iter_rows(args.final_csv):
        try:
            qp, sg, mg, lb, lset, sbc, cost_bin, eb, tr_size, _qs = row_features(row)
            x = np.array([float(row[f"x{i:02d}"]) for i in range(tr_size)], dtype=np.float64)
        except Exception:
            continue
        key = coff_key(qp, sg, mg, lb, lset, sbc, cost_bin, eb)
        agg = corr_aggs.get(key)
        if agg is None:
            agg = CorrAgg(tr_size)
            corr_aggs[key] = agg
        agg.add(x)
        total_rows += 1

    coff_rows = []
    coff_buckets = {}
    for key, agg in sorted(corr_aggs.items()):
        if agg.n < args.min_coff_samples:
            continue
        coff = agg.coff()
        bucket = coff_bucket(coff)
        coff_buckets[key] = bucket
        coff_rows.append((key, agg.n, bucket, coff))

    score_aggs = defaultdict(lambda: Counter({
        "n": 0, "c0": 0, "c1": 0, "c2": 0, "miss1": 0, "miss3": 0, "miss5": 0,
    }))
    score_float = defaultdict(lambda: {
        "loss1": 0.0, "loss3": 0.0, "loss5": 0.0,
        "max1": 0.0, "max3": 0.0, "max5": 0.0,
        "gain1": 0.0, "gain2": 0.0,
    })

    for row in iter_rows(args.final_csv):
        try:
            costs = valid_costs(row)
            if costs is None:
                continue
            qp, sg, mg, lb, lset, sbc, cost_bin, eb, tr_size, qs = row_features(row)
            base = coff_key(qp, sg, mg, lb, lset, sbc, cost_bin, eb)
            cof_b = coff_buckets.get(base)
            if cof_b is None:
                continue
            x = [float(row[f"x{i:02d}"]) for i in range(tr_size)]
            q = [int(math.floor(abs(v) / max(qs, 1.0e-9) + 0.5)) for v in x]
            nz = sum(1 for v in q if v)
            last = max((i for i, v in enumerate(q) if v), default=-1)
            obs = max(read_float(row, "obs1"), read_float(row, "obs2"))
        except Exception:
            continue

        key = score_key(qp, sg, mg, lb, lset, sbc, cost_bin, eb, nz_bucket(nz), last_bucket(last), cof_b, obs_bucket(obs))
        c0, c1, c2 = costs
        best = int(float(row["finalLfnstIdx"]))
        best_cost = min(c0, c1, c2)
        denom = max(c0, 1.0)
        l1 = max(0.0, c0 - best_cost) / denom
        l3 = max(0.0, min(c0, c1) - best_cost) / denom
        l5 = max(0.0, min(c0, c2) - best_cost) / denom

        a = score_aggs[key]
        b = score_float[key]
        a["n"] += 1
        a[f"c{best}"] += 1
        if best != 0:
            a["miss1"] += 1
        if best == 2:
            a["miss3"] += 1
        if best == 1:
            a["miss5"] += 1
        b["loss1"] += l1
        b["loss3"] += l3
        b["loss5"] += l5
        b["max1"] = max(b["max1"], l1)
        b["max3"] = max(b["max3"], l3)
        b["max5"] = max(b["max5"], l5)
        b["gain1"] += c0 - c1
        b["gain2"] += c0 - c2

    score_rows = []
    for key in sorted(score_aggs):
        a = score_aggs[key]
        b = score_float[key]
        if a["n"] < args.min_score_samples:
            continue
        merged = {**a, **b}
        mask = choose_mask(merged, args.alpha, args.beta, args.gamma)
        score_rows.append((key, a["n"], mask, b["gain1"] / a["n"], b["gain2"] / a["n"]))

    table = {key: mask for key, _n, mask, _g1, _g2 in score_rows}
    eval_counts = Counter()
    for row in iter_rows(args.final_csv):
        try:
            qp, sg, mg, lb, lset, sbc, cost_bin, eb, tr_size, qs = row_features(row)
            base = coff_key(qp, sg, mg, lb, lset, sbc, cost_bin, eb)
            cof_b = coff_buckets.get(base)
            if cof_b is None:
                mask = 7
            else:
                x = [float(row[f"x{i:02d}"]) for i in range(tr_size)]
                q = [int(math.floor(abs(v) / max(qs, 1.0e-9) + 0.5)) for v in x]
                nz = sum(1 for v in q if v)
                last = max((i for i, v in enumerate(q) if v), default=-1)
                obs = max(read_float(row, "obs1"), read_float(row, "obs2"))
                key = score_key(qp, sg, mg, lb, lset, sbc, cost_bin, eb, nz_bucket(nz), last_bucket(last), cof_b, obs_bucket(obs))
                mask = table.get(key, 7)
                if mask == 1 and obs >= args.obs_gate:
                    mask = 7
            final = int(float(row["finalLfnstIdx"]))
        except Exception:
            continue
        eval_counts["n"] += 1
        eval_counts[f"final{final}"] += 1
        eval_counts[f"mask{mask}"] += 1
        if mask & (1 << final):
            eval_counts["correct"] += 1
        else:
            eval_counts["error"] += 1
            eval_counts[f"error{final}"] += 1
        if final == 0:
            eval_counts["det0" if mask == 1 else "over0"] += 1
        else:
            eval_counts["pos"] += 1
            if not (mask & (1 << final)):
                eval_counts["missPos"] += 1

    args.coff_out.parent.mkdir(parents=True, exist_ok=True)
    with args.coff_out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("// Generated by tools/lard_lfnst2nd_fit_coff_score_table.py\n")
        f.write("// Key: qp,sizeGroup,modeGroup,thetaMaxBucket,lfnstSet,sbClass,dct2CostBin,energyNormBucket\n")
        f.write("// Fields: baseKey, samples, coffBucket, Coff\n")
        for key, n, bucket, coff in coff_rows:
            f.write(f"  {{ {key}LL, {n}, {bucket}, {coff:.9g} }},\n")
        f.write("  { 9223372036854775807LL, 0, 0, 0.0 },\n")

    args.score_out.parent.mkdir(parents=True, exist_ok=True)
    with args.score_out.open("w", encoding="utf-8", newline="\n") as f:
        f.write("// Generated by tools/lard_lfnst2nd_fit_coff_score_table.py\n")
        f.write(f"// totalRows={total_rows}, scoreEntries={len(score_rows)}, alpha={args.alpha:g}, beta={args.beta:g}, gamma={args.gamma:g}\n")
        f.write("// Key: qp,sizeGroup,modeGroup,thetaMaxBucket,lfnstSet,sbClass,dct2CostBin,energyNormBucket,n0Bucket,last0Bucket,CoffBucket,maxObsBucket\n")
        f.write("// Fields: packedKey, samples, mask, meanTrueGain1, meanTrueGain2\n")
        for key, n, mask, g1, g2 in score_rows:
            f.write(f"  {{ {key}LL, {n}, {mask}, {g1:.9g}, {g2:.9g} }},\n")
        f.write("  { 9223372036854775807LL, 0, 7, 0.0, 0.0 },\n")

    summary = {
        "totalRows": total_rows,
        "coffEntries": len(coff_rows),
        "scoreEntries": len(score_rows),
        "alpha": args.alpha,
        "beta": args.beta,
        "gamma": args.gamma,
        "coffBucketCounts": dict(Counter(bucket for _key, _n, bucket, _coff in coff_rows)),
        "maskCounts": dict(Counter(mask for _key, _n, mask, _g1, _g2 in score_rows)),
        "eval": dict(eval_counts),
    }
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.csv_out:
        with args.csv_out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["key", "samples", "mask", "meanTrueGain1", "meanTrueGain2"])
            writer.writerows(score_rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
