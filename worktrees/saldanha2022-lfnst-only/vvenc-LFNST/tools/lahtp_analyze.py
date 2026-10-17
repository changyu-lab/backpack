#!/usr/bin/env python3
"""Analyze LAHTP LFNST/MTS candidate traces.

This script intentionally uses only the Python standard library so it can run
on a fresh encoder checkout. It summarizes the Phase-1 CSV and evaluates a few
interpretable feature scores for Phase-2 threshold fitting.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from typing import Callable, Iterable


LAT_BUCKETS = {
    "0": "[0,30)",
    "1": "[30,60)",
    "2": "[60,75)",
    "3": "[75,90]",
}


def f(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def i(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def finite(v: float) -> bool:
    return math.isfinite(v) and abs(v) < 1.0e300


def pearson(xs: list[float], ys: list[float]) -> float:
    pairs = [(x, y) for x, y in zip(xs, ys) if finite(x) and finite(y)]
    if len(pairs) < 2:
        return float("nan")
    xs, ys = zip(*pairs)
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0.0 or vy <= 0.0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(vx * vy)


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda k: values[k])
    out = [0.0] * len(values)
    pos = 0
    while pos < len(order):
        end = pos + 1
        while end < len(order) and values[order[end]] == values[order[pos]]:
            end += 1
        rank = (pos + end + 1) * 0.5
        for idx in order[pos:end]:
            out[idx] = rank
        pos = end
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    pairs = [(x, y) for x, y in zip(xs, ys) if finite(x) and finite(y)]
    if len(pairs) < 2:
        return float("nan")
    rx = ranks([p[0] for p in pairs])
    ry = ranks([p[1] for p in pairs])
    return pearson(rx, ry)


def auc(scores: list[float], labels: list[int]) -> float:
    pairs = [(s, l) for s, l in zip(scores, labels) if finite(s)]
    pos = sum(l for _, l in pairs)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    rs = ranks([p[0] for p in pairs])
    pos_rank_sum = sum(r for r, (_, l) in zip(rs, pairs) if l)
    return (pos_rank_sum - pos * (pos + 1) * 0.5) / (pos * neg)


def quantile(values: list[float], q: float) -> float:
    vals = sorted(v for v in values if finite(v))
    if not vals:
        return float("nan")
    idx = min(len(vals) - 1, max(0, round(q * (len(vals) - 1))))
    return vals[idx]


def score_functions() -> dict[str, Callable[[dict[str, str]], float]]:
    return {
        "latitude": lambda r: f(r, "absLatDeg"),
        "latitude+QP": lambda r: f(r, "absLatDeg") + 0.5 * f(r, "qp"),
        "LARD": lambda r: -f(r, "psiLard") + 0.01 * f(r, "qp"),
        "sparse": lambda r: -f(r, "psiLard") - 2.0 * f(r, "nzRatio") + 0.01 * f(r, "qp"),
        "full": lambda r: (
            -f(r, "psiLard")
            - 2.0 * f(r, "nzRatio")
            - 0.15 * f(r, "dirAniso")
            - 0.00001 * f(r, "resEnergy")
            + 0.01 * f(r, "qp")
            - 0.001 * (f(r, "w") * f(r, "h"))
        ),
    }


def mean(values: Iterable[float]) -> float:
    vals = [v for v in values if finite(v)]
    return statistics.fmean(vals) if vals else float("nan")


def print_table(headers: list[str], rows: list[list[object]]) -> None:
    widths = [len(h) for h in headers]
    rendered = []
    for row in rows:
        r = [format_cell(c) for c in row]
        rendered.append(r)
        widths = [max(w, len(c)) for w, c in zip(widths, r)]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rendered:
        print(" | ".join(c.rjust(w) for c, w in zip(row, widths)))


def format_cell(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return f"{value:.6g}"
    return str(value)


def motivation_by_lat(rows: list[dict[str, str]]) -> None:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[str(i(row, "latBucket"))].append(row)

    table = []
    for bucket in sorted(groups):
        rs = groups[bucket]
        mts_checked = sum(1 for r in rs if i(r, "mtsIdx") != 0)
        mts_selected = sum(1 for r in rs if i(r, "selected") and i(r, "mtsIdx") != 0)
        lfnst_checked = sum(1 for r in rs if i(r, "lfnstIdx") != 0)
        lfnst_selected = sum(1 for r in rs if i(r, "selected") and i(r, "lfnstIdx") != 0)
        table.append(
            [
                LAT_BUCKETS.get(bucket, bucket),
                len(rs),
                mts_checked,
                mts_selected,
                lfnst_checked,
                lfnst_selected,
                mean(f(r, "deltaJFromDct2") for r in rs),
                mean(f(r, "deltaJFromNoLfnst") for r in rs if i(r, "lfnstIdx") != 0),
            ]
        )
    print("\nLatitude bucket motivation")
    print_table(
        ["bucket", "rows", "MTS checked", "MTS selected", "LFNST checked", "LFNST selected", "avg dJ MTS", "avg dJ LFNST"],
        table,
    )


def correlations(rows: list[dict[str, str]], target_key: str) -> None:
    target = [f(r, target_key) for r in rows]
    table = []
    for key in ["absLatDeg", "psiLard", "nzRatio", "dirAniso", "resEnergy"]:
        xs = [f(r, key) for r in rows]
        table.append([key, pearson(xs, target), spearman(xs, target)])
    print(f"\nFeature correlation with {target_key}")
    print_table(["feature", "Pearson", "Spearman"], table)


def model_metrics(rows: list[dict[str, str]], target_key: str, tau0: float, skip_quantile: float) -> None:
    clean = [r for r in rows if finite(f(r, target_key))]
    labels = [1 if f(r, target_key) < -tau0 else 0 for r in clean]
    table = []
    for name, fn in score_functions().items():
        scores = [fn(r) for r in clean]
        threshold = quantile(scores, skip_quantile)
        skip = [s >= threshold for s in scores]
        beneficial = sum(labels)
        skipped = sum(1 for x in skip if x)
        miss = sum(1 for x, y in zip(skip, labels) if x and y)
        false_skip = miss / skipped if skipped else float("nan")
        miss_rate = miss / beneficial if beneficial else float("nan")
        table.append([name, auc(scores, labels), miss_rate, false_skip, pearson(scores, [f(r, target_key) for r in clean]), threshold])
    print(f"\nModel metrics for {target_key} (beneficial: DeltaJ < {-tau0:g}, skip top {100*(1-skip_quantile):.1f}% risk score)")
    print_table(["model", "AUC", "miss rate", "false skip", "corr", "threshold"], table)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze LAHTP CSV traces")
    parser.add_argument("csv_file")
    parser.add_argument("--tau0", type=float, default=0.0)
    parser.add_argument("--skip-quantile", type=float, default=0.9, help="Score quantile used as a tentative skip threshold")
    args = parser.parse_args()

    with open(args.csv_file, newline="") as fh:
        rows = list(csv.DictReader(fh))

    print(f"Loaded {len(rows)} candidate rows from {args.csv_file}")
    motivation_by_lat(rows)
    correlations(rows, "deltaJFromDct2")
    correlations([r for r in rows if i(r, "lfnstIdx") != 0], "deltaJFromNoLfnst")
    model_metrics(rows, "deltaJFromDct2", args.tau0, args.skip_quantile)
    model_metrics([r for r in rows if i(r, "lfnstIdx") != 0], "deltaJFromNoLfnst", args.tau0, args.skip_quantile)


if __name__ == "__main__":
    main()
