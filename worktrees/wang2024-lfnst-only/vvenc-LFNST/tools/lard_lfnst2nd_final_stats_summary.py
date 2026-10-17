#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


DEFAULT_FIELDS = [
    "offdiagProxy",
    "corrStrength",
    "inputEnergy",
    "thetaMaxDeg",
    "rate0",
    "obsRate0",
    "f1",
    "f2",
    "g1",
    "g2",
    "obs1",
    "obs2",
    "trueGain1",
    "trueGain2",
]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    xs = sorted(values)
    pos = (len(xs) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def summarize(values: list[float]) -> dict[str, float | int]:
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean": math.nan,
            "std": math.nan,
            "p05": math.nan,
            "p25": math.nan,
            "p50": math.nan,
            "p75": math.nan,
            "p95": math.nan,
        }
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / max(1, n - 1)
    return {
        "n": n,
        "mean": mean,
        "std": math.sqrt(var),
        "p05": percentile(values, 0.05),
        "p25": percentile(values, 0.25),
        "p50": percentile(values, 0.50),
        "p75": percentile(values, 0.75),
        "p95": percentile(values, 0.95),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize skip13/second-response final validation stats by final best lfnstIdx."
    )
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fields", default=",".join(DEFAULT_FIELDS))
    args = parser.parse_args()

    fields = [x.strip() for x in args.fields.split(",") if x.strip()]
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    counts = defaultdict(int)
    masks = defaultdict(lambda: defaultdict(int))
    safe = defaultdict(int)

    with args.csv_file.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            idx = row.get("finalLfnstIdx", "")
            if idx == "":
                continue
            counts[idx] += 1
            masks[idx][row.get("mask", "")] += 1
            safe[idx] += int(float(row.get("safeGate", "0") or 0))
            for field in fields:
                try:
                    grouped[(idx, field)].append(float(row[field]))
                except (KeyError, TypeError, ValueError):
                    pass

    out_rows: list[dict[str, float | int | str]] = []
    for idx in sorted(counts, key=lambda x: int(x) if x.lstrip("-").isdigit() else 99):
        total = counts[idx]
        for field in fields:
            stats = summarize(grouped[(idx, field)])
            out_rows.append(
                {
                    "finalLfnstIdx": idx,
                    "field": field,
                    "groupCount": total,
                    "fieldCount": stats["n"],
                    "mean": stats["mean"],
                    "std": stats["std"],
                    "p05": stats["p05"],
                    "p25": stats["p25"],
                    "p50": stats["p50"],
                    "p75": stats["p75"],
                    "p95": stats["p95"],
                    "mask1_pct": masks[idx].get("1", 0) / total * 100.0,
                    "mask3_pct": masks[idx].get("3", 0) / total * 100.0,
                    "mask5_pct": masks[idx].get("5", 0) / total * 100.0,
                    "mask7_pct": masks[idx].get("7", 0) / total * 100.0,
                    "safeGate_pct": safe[idx] / total * 100.0,
                }
            )

    fieldnames = [
        "finalLfnstIdx",
        "field",
        "groupCount",
        "fieldCount",
        "mean",
        "std",
        "p05",
        "p25",
        "p50",
        "p75",
        "p95",
        "mask1_pct",
        "mask3_pct",
        "mask5_pct",
        "mask7_pct",
        "safeGate_pct",
    ]

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fh_out = args.out.open("w", newline="", encoding="utf-8")
    else:
        import sys

        fh_out = sys.stdout

    with fh_out:
        writer = csv.DictWriter(fh_out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)


if __name__ == "__main__":
    main()
