#!/usr/bin/env python3
"""Analyze LARD-LFNST candidate traces without loading large CSVs fully."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


LAT_BUCKETS = [(0, 30), (30, 60), (60, 75), (75, 90.0001)]


def ff(row: dict[str, str], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def valid_cost(x: float) -> bool:
    return math.isfinite(x) and abs(x) < 1.0e100


def ii(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def lat_bucket(abs_lat: float) -> str:
    for lo, hi in LAT_BUCKETS:
        if lo <= abs_lat < hi:
            return f"{lo:g}-{int(hi if hi < 90.0001 else 90)}"
    return "unknown"


def summarize_group(rows: list[dict[str, str]]) -> dict[str, float | int | str | bool]:
    first = rows[0]
    best_by_lfnst: dict[int, float] = {}
    best_mts_by_lfnst: dict[int, int] = {}
    best_nz_by_lfnst: dict[int, int] = {}
    best_last_by_lfnst: dict[int, int] = {}
    best_abs_by_lfnst: dict[int, float] = {}
    corr_proxy = math.nan
    for row in rows:
        idx = ii(row, "lfnstIdx")
        cost = ff(row, "cost")
        if idx == 0 and ii(row, "mtsIdx") == 0:
            corr_proxy = ff(row, "corrProxy", corr_proxy)
            if not math.isfinite(corr_proxy):
                roi_dim = ii(row, "roiDim")
                vals = [ff(row, f"roiQ{i:02d}") for i in range(max(0, min(roi_dim, 48)))]
                energy = sum(v * v for v in vals if math.isfinite(v))
                pair_abs = sum(abs(vals[i] * vals[i + 1]) for i in range(len(vals) - 1) if math.isfinite(vals[i]) and math.isfinite(vals[i + 1]))
                corr_proxy = pair_abs / (energy + 1e-9) if vals else math.nan
        if not valid_cost(cost):
            continue
        if idx not in best_by_lfnst or cost < best_by_lfnst[idx]:
            best_by_lfnst[idx] = cost
            best_mts_by_lfnst[idx] = ii(row, "mtsIdx")
            best_nz_by_lfnst[idx] = ii(row, "nonZero", ii(row, "numSig", -1))
            best_last_by_lfnst[idx] = ii(row, "lastPos", -1)
            best_abs_by_lfnst[idx] = ff(row, "absSum")

    j0 = best_by_lfnst.get(0, math.inf)
    j1 = best_by_lfnst.get(1, math.inf)
    j2 = best_by_lfnst.get(2, math.inf)
    best_lfnst = min(j1, j2)
    best_all = min(j0, j1, j2)
    has_lfnst = valid_cost(best_lfnst)
    best_idx = 0 if (not has_lfnst or j0 <= best_lfnst) else (1 if j1 <= j2 else 2)
    oracle_skip = (not has_lfnst) or j0 <= best_lfnst
    pred_skip = ii(first, "stage1") == 1 and ii(first, "stage2") == 1
    false_skip = pred_skip and not oracle_skip
    missed_gain = max(0.0, j0 - best_lfnst) if false_skip else 0.0

    return {
        "poc": ii(first, "poc"),
        "x": ii(first, "x"),
        "y": ii(first, "y"),
        "w": ii(first, "w"),
        "h": ii(first, "h"),
        "qp": ii(first, "qp"),
        "intraMode": ii(first, "intraMode"),
        "absLatDeg": ff(first, "absLatDeg"),
        "thetaMaxDeg": ff(first, "thetaMaxDeg"),
        "thetaSkipDeg": ff(first, "thetaSkipDeg"),
        "roiEnergyQ": ff(first, "roiEnergyQ"),
        "lfRatio": ff(first, "lfRatio"),
        "predNz": ff(first, "predNz"),
        "corrProxy": corr_proxy,
        "stage1": ii(first, "stage1"),
        "stage2": ii(first, "stage2"),
        "j0": j0,
        "j1": j1,
        "j2": j2,
        "bestIdx": best_idx,
        "oracleSkip": oracle_skip,
        "hasLfnst": has_lfnst,
        "predSkip": pred_skip,
        "falseSkip": false_skip,
        "missedGain": missed_gain,
        "deltaBestLfnst": j0 - best_lfnst if has_lfnst else math.nan,
        "bestMts0": best_mts_by_lfnst.get(0, -1),
        "n0": best_nz_by_lfnst.get(0, -1),
        "n1": best_nz_by_lfnst.get(1, -1),
        "n2": best_nz_by_lfnst.get(2, -1),
        "last0": best_last_by_lfnst.get(0, -1),
        "last1": best_last_by_lfnst.get(1, -1),
        "last2": best_last_by_lfnst.get(2, -1),
        "m0": best_abs_by_lfnst.get(0, math.nan),
        "m1": best_abs_by_lfnst.get(1, math.nan),
        "m2": best_abs_by_lfnst.get(2, math.nan),
        "deltaN": (
            best_nz_by_lfnst.get(0, -1) - min(best_nz_by_lfnst.get(1, 1 << 30), best_nz_by_lfnst.get(2, 1 << 30))
            if has_lfnst and best_nz_by_lfnst.get(0, -1) >= 0
            else math.nan
        ),
        "deltaL": (
            best_last_by_lfnst.get(0, -1) - min(best_last_by_lfnst.get(1, 1 << 30), best_last_by_lfnst.get(2, 1 << 30))
            if has_lfnst and best_last_by_lfnst.get(0, -1) >= 0
            else math.nan
        ),
        "deltaLast": (
            best_last_by_lfnst.get(0, -1) - min(best_last_by_lfnst.get(1, 1 << 30), best_last_by_lfnst.get(2, 1 << 30))
            if has_lfnst and best_last_by_lfnst.get(0, -1) >= 0
            else math.nan
        ),
        "deltaM": (
            best_abs_by_lfnst.get(0, math.nan) - min(best_abs_by_lfnst.get(1, math.inf), best_abs_by_lfnst.get(2, math.inf))
            if has_lfnst and math.isfinite(best_abs_by_lfnst.get(0, math.nan))
            else math.nan
        ),
        "bestCost": best_all,
    }


def block_key(row: dict[str, str]) -> tuple[int, int, int, int, int, int, int]:
    return (
        ii(row, "poc"),
        ii(row, "x"),
        ii(row, "y"),
        ii(row, "w"),
        ii(row, "h"),
        ii(row, "qp"),
        ii(row, "intraMode"),
    )


def analyze_streaming(path: Path, block_csv: Path | None = None) -> dict[str, object]:
    total_rows = 0
    total_blocks = 0
    lfnst_eligible_blocks = 0
    pred_skip_blocks = 0
    pred_skip_eligible_blocks = 0
    oracle_keep_blocks = 0
    false_skip_blocks = 0
    false_skip_missed_gain_sum = 0.0
    false_skip_missed_gain_max = 0.0
    by_lat: dict[str, dict[str, float | int]] = {}

    writer = None
    out_fh = None
    if block_csv:
        out_fh = block_csv.open("w", newline="")

    def lat_stats(bucket: str) -> dict[str, float | int]:
        if bucket not in by_lat:
            by_lat[bucket] = {
                "blocks": 0,
                "predSkipBlocks": 0,
                "oracleKeepBlocks": 0,
                "falseSkipBlocks": 0,
                "deltaSum": 0.0,
                "deltaCount": 0,
            }
        return by_lat[bucket]

    def consume(rows: list[dict[str, str]]) -> None:
        nonlocal total_blocks, lfnst_eligible_blocks, pred_skip_blocks, pred_skip_eligible_blocks
        nonlocal oracle_keep_blocks, false_skip_blocks, false_skip_missed_gain_sum, false_skip_missed_gain_max
        nonlocal writer
        if not rows:
            return
        block = summarize_group(rows)
        total_blocks += 1
        if block["hasLfnst"]:
            lfnst_eligible_blocks += 1
            if block["predSkip"]:
                pred_skip_eligible_blocks += 1
        if block["predSkip"]:
            pred_skip_blocks += 1
        if not block["oracleSkip"]:
            oracle_keep_blocks += 1
        if block["falseSkip"]:
            false_skip_blocks += 1
            missed = float(block["missedGain"])
            false_skip_missed_gain_sum += missed
            false_skip_missed_gain_max = max(false_skip_missed_gain_max, missed)

        bucket = lat_bucket(float(block["absLatDeg"]))
        stats = lat_stats(bucket)
        stats["blocks"] = int(stats["blocks"]) + 1
        if block["predSkip"]:
            stats["predSkipBlocks"] = int(stats["predSkipBlocks"]) + 1
        if not block["oracleSkip"]:
            stats["oracleKeepBlocks"] = int(stats["oracleKeepBlocks"]) + 1
        if block["falseSkip"]:
            stats["falseSkipBlocks"] = int(stats["falseSkipBlocks"]) + 1
        delta = float(block["deltaBestLfnst"])
        if math.isfinite(delta):
            stats["deltaSum"] = float(stats["deltaSum"]) + delta
            stats["deltaCount"] = int(stats["deltaCount"]) + 1

        if out_fh:
            if writer is None:
                writer = csv.DictWriter(out_fh, fieldnames=list(block.keys()))
                writer.writeheader()
            writer.writerow(block)

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        current_key = None
        current_rows: list[dict[str, str]] = []
        for row in reader:
            total_rows += 1
            key = block_key(row)
            if current_key is None:
                current_key = key
            if key != current_key:
                consume(current_rows)
                current_rows = []
                current_key = key
            current_rows.append(row)
        consume(current_rows)

    if out_fh:
        out_fh.close()

    summary: dict[str, object] = {
        "trace": str(path),
        "candidateRows": total_rows,
        "blocks": total_blocks,
    }

    summary.update(
        {
            "lfnstEligibleBlocks": lfnst_eligible_blocks,
            "predSkipBlocks": pred_skip_blocks,
            "predSkipRatio": pred_skip_blocks / total_blocks if total_blocks else 0.0,
            "predSkipRatioEligible": pred_skip_eligible_blocks / lfnst_eligible_blocks if lfnst_eligible_blocks else 0.0,
            "oracleKeepBlocks": oracle_keep_blocks,
            "falseSkipBlocks": false_skip_blocks,
            "falseSkipRateAmongPredSkips": false_skip_blocks / pred_skip_blocks if pred_skip_blocks else 0.0,
            "falseSkipRateAmongOracleKeeps": false_skip_blocks / oracle_keep_blocks if oracle_keep_blocks else 0.0,
            "meanMissedGain": false_skip_missed_gain_sum / false_skip_blocks if false_skip_blocks else 0.0,
            "maxMissedGain": false_skip_missed_gain_max,
        }
    )

    for bucket in ["0-30", "30-60", "60-75", "75-90", "unknown"]:
        stats = by_lat.get(bucket)
        if not stats:
            continue
        by_lat[bucket] = {
            "blocks": int(stats["blocks"]),
            "predSkipRatio": int(stats["predSkipBlocks"]) / int(stats["blocks"]) if int(stats["blocks"]) else 0.0,
            "oracleKeepRatio": int(stats["oracleKeepBlocks"]) / int(stats["blocks"]) if int(stats["blocks"]) else 0.0,
            "falseSkipBlocks": int(stats["falseSkipBlocks"]),
            "meanDeltaBestLfnst": float(stats["deltaSum"]) / int(stats["deltaCount"]) if int(stats["deltaCount"]) else math.nan,
        }
    summary["byLatitude"] = by_lat
    return summary


def analyze(path: Path, block_csv: Path | None = None) -> dict[str, object]:
    return analyze_streaming(path, block_csv)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_csv", type=Path)
    ap.add_argument("--block-csv", type=Path)
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    summary = analyze(args.trace_csv, args.block_csv)
    text = json.dumps(summary, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
