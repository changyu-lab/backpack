#!/usr/bin/env python3
"""Analyze Skip15 measure-only logs against full LFNST RDO results."""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
from pathlib import Path


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0.0 or vy <= 0.0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def auc(scores: list[float], labels: list[int]) -> float:
    pairs = sorted(zip(scores, labels))
    positive_count = sum(labels)
    negative_count = len(labels) - positive_count
    if not positive_count or not negative_count:
        return 0.0
    wins = 0.0
    negatives_before = 0
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[index][0]:
            end += 1
        tied = pairs[index:end]
        tied_positives = sum(label for _, label in tied)
        tied_negatives = len(tied) - tied_positives
        wins += tied_positives * (negatives_before + 0.5 * tied_negatives)
        negatives_before += tied_negatives
        index = end
    return wins / (positive_count * negative_count)


def resolve_logs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matched = [Path(path) for path in glob.glob(pattern)]
        if matched:
            paths.extend(matched)
        else:
            path = Path(pattern)
            if path.exists():
                paths.append(path)
    return sorted(set(paths))


def read_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def finite_cost(row: dict[str, str], name: str) -> float | None:
    try:
        value = float(row[name])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and abs(value) < 1e300 else None


def variance_ratios(rows: list[dict[str, str]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for candidate in (1, 2):
        actual_sum = 0.0
        predicted_sum = 0.0
        count = 0
        per_coeff = []
        for index in range(16):
            actual = []
            predicted = []
            for row in rows:
                if int(row.get(f"actualValid{candidate}", "1")) == 0:
                    continue
                actual_key = f"actualY{candidate}Sq_{index:02d}"
                predicted_key = f"predVarY{candidate}_{index:02d}"
                if actual_key in row and predicted_key in row:
                    actual.append(float(row[actual_key]))
                    predicted.append(float(row[predicted_key]))
            mean_actual = sum(actual) / len(actual) if actual else 0.0
            mean_predicted = sum(predicted) / len(predicted) if predicted else 0.0
            per_coeff.append(
                {
                    "index": index,
                    "actual_mean": mean_actual,
                    "predicted_mean": mean_predicted,
                    "actual_over_predicted": mean_actual / mean_predicted if mean_predicted > 0.0 else 0.0,
                }
            )
            actual_sum += sum(actual)
            predicted_sum += sum(predicted)
            count += len(actual)
        result[f"candidate{candidate}"] = {
            "samples": count,
            "actual_over_predicted": actual_sum / predicted_sum if predicted_sum > 0.0 else 0.0,
            "per_coeff": per_coeff,
        }
    return result


def threshold_sweep(rows: list[dict[str, str]], gain1: list[float], gain2: list[float]) -> list[dict[str, float | int]]:
    score_pairs = [
        (
            float(row.get("F1", row["G1_cov"])),
            float(row.get("F2", row["G2_cov"])),
        )
        for row in rows
    ]
    ordered = sorted(
        (max(pair), max(gain1[index], gain2[index], 0.0))
        for index, pair in enumerate(score_pairs)
    )
    if not ordered:
        return []
    groups = []
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        missed = [gain for _, gain in ordered[index:end] if gain > 0.0]
        groups.append((ordered[index][0], end - index, len(missed), sum(missed), max(missed, default=0.0)))
        index = end
    positions = sorted({round(index * (len(groups) - 1) / 100) for index in range(101)})
    sweep = []
    false_count = 0
    missed_sum = 0.0
    missed_max = 0.0
    skipped = 0
    previous = -1
    for position in positions:
        for index in range(previous + 1, position + 1):
            _, count, false, loss_sum, loss_max = groups[index]
            skipped += count
            false_count += false
            missed_sum += loss_sum
            missed_max = max(missed_max, loss_max)
        threshold = groups[position][0]
        sweep.append(
            {
                "threshold": threshold,
                "skip_count": skipped,
                "skip_rate": skipped / len(rows),
                "false_skip_count": false_count,
                "false_skip_rate_all": false_count / len(rows),
                "false_skip_rate_skipped": false_count / skipped,
                "missed_gain_sum": missed_sum,
                "missed_gain_mean": missed_sum / max(false_count, 1),
                "missed_gain_max": missed_max,
            }
        )
        previous = position
    return sweep


def analyze(rows_all: list[dict[str, str]]) -> dict[str, object]:
    found = [row for row in rows_all if int(row.get("tableFound", "1")) != 0]
    rows = []
    for row in found:
        costs = [finite_cost(row, name) for name in ("J0", "J1", "J2")]
        if all(value is not None for value in costs):
            rows.append(row)

    gain1 = [float(row["J0"]) - float(row["J1"]) for row in rows]
    gain2 = [float(row["J0"]) - float(row["J2"]) for row in rows]
    score1 = [float(row["G1_cov"]) for row in rows]
    score2 = [float(row["G2_cov"]) for row in rows]
    rank_rows = [index for index in range(len(rows)) if max(gain1[index], gain2[index]) > 0.0]
    rank_correct = sum((score1[index] > score2[index]) == (gain1[index] > gain2[index]) for index in rank_rows)
    skip_rows = [index for index, row in enumerate(rows) if int(row["maskPred"]) == 1]
    false_skip = [index for index in skip_rows if max(gain1[index], gain2[index]) > 0.0]
    missed = [max(gain1[index], gain2[index], 0.0) for index in false_skip]
    return {
        "rows_total": len(rows_all),
        "rows_table_found": len(found),
        "rows_table_missing": len(rows_all) - len(found),
        "rows": len(rows),
        "rows_incomplete_rdo": len(found) - len(rows),
        "corr_g1_dj1": pearson(score1, gain1),
        "corr_g2_dj2": pearson(score2, gain2),
        "auc_g1": auc(score1, [int(value > 0.0) for value in gain1]),
        "auc_g2": auc(score2, [int(value > 0.0) for value in gain2]),
        "sign_accuracy_g1": sum((a > 0.0) == (b > 0.0) for a, b in zip(score1, gain1)) / max(len(rows), 1),
        "sign_accuracy_g2": sum((a > 0.0) == (b > 0.0) for a, b in zip(score2, gain2)) / max(len(rows), 1),
        "positive_rank_rows": len(rank_rows),
        "rank_correct": rank_correct,
        "positive_rank_accuracy": rank_correct / max(len(rank_rows), 1),
        "skip_count": len(skip_rows),
        "false_skip_count": len(false_skip),
        "false_skip_rate": len(false_skip) / max(len(skip_rows), 1),
        "missed_gain_sum": sum(missed),
        "missed_gain_avg": sum(missed) / max(len(missed), 1),
        "variance_ratios": variance_ratios(rows),
        "threshold_sweep": threshold_sweep(rows, gain1, gain2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", help="CSV paths or glob patterns")
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args()
    paths = resolve_logs(args.logs)
    if not paths:
        raise SystemExit("no input logs found")
    result = analyze(read_rows(paths))
    result["input_logs"] = [str(path) for path in paths]
    text = json.dumps(result, indent=2) + "\n"
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
