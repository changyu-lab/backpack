#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, TextIO


MASKS = {
    0x1: (0,),
    0x3: (0, 1),
    0x5: (0, 2),
    0x7: (0, 1, 2),
}
MASK_LABELS = {
    0x1: "0",
    0x3: "0,1",
    0x5: "0,2",
    0x7: "0,1,2",
}
REQUIRED_FIELDS = {
    "J0",
    "J1",
    "J2",
    "candidateRdoTimeNs1",
    "candidateRdoTimeNs2",
}


def open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open("r", newline="", encoding="utf-8")


def parse_float(row: dict[str, str], name: str) -> float:
    value = float(row[name])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {name}")
    return value


def iter_rows(paths: Iterable[Path]) -> Iterable[dict[str, float]]:
    for path in paths:
        with open_text(path) as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = sorted(REQUIRED_FIELDS - fields)
            if missing:
                raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")
            for raw in reader:
                try:
                    valid = all(int(raw.get(f"rdoValid{idx}", "1")) != 0 for idx in range(3))
                    if not valid:
                        continue
                    costs = [parse_float(raw, f"J{idx}") for idx in range(3)]
                    times = [
                        0.0,
                        max(0.0, parse_float(raw, "candidateRdoTimeNs1")),
                        max(0.0, parse_float(raw, "candidateRdoTimeNs2")),
                    ]
                except (KeyError, TypeError, ValueError):
                    continue
                yield {"costs": costs, "times": times}


def mask_metrics(row: dict[str, list[float]], mask: int) -> tuple[float, float, int]:
    costs = row["costs"]
    times = row["times"]
    best_full = min(costs)
    retained = MASKS[mask]
    rd_loss = max(0.0, min(costs[idx] for idx in retained) - best_full)
    removed = tuple(idx for idx in (1, 2) if idx not in retained)
    time_saved = sum(times[idx] for idx in removed)
    return time_saved, rd_loss, len(removed)


def evaluate(rows: list[dict[str, list[float]]], mu: float) -> dict[str, object]:
    mask_counts: Counter[str] = Counter()
    total_time_saved = 0.0
    total_rd_loss = 0.0
    removed_candidates = 0
    for row in rows:
        options = []
        for mask in MASKS:
            time_saved, rd_loss, removed = mask_metrics(row, mask)
            score = time_saved - mu * rd_loss
            options.append((score, -rd_loss, time_saved, mask, removed))
        _, neg_loss, time_saved, mask, removed = max(options)
        total_time_saved += time_saved
        total_rd_loss += -neg_loss
        removed_candidates += removed
        mask_counts[MASK_LABELS[mask]] += 1

    total_candidate_time = sum(row["times"][1] + row["times"][2] for row in rows)
    total_candidates = 2 * len(rows)
    return {
        "mu": mu,
        "total_time_saved_ns": int(round(total_time_saved)),
        "time_saving_ratio": total_time_saved / total_candidate_time if total_candidate_time else 0.0,
        "total_rd_loss": total_rd_loss,
        "mean_rd_loss": total_rd_loss / len(rows) if rows else 0.0,
        "removed_candidates": removed_candidates,
        "candidate_reduction": removed_candidates / total_candidates if total_candidates else 0.0,
        "mask_counts": {label: mask_counts.get(label, 0) for label in MASK_LABELS.values()},
    }


def parse_csv_numbers(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("at least one value is required")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute a time-weighted oracle upper bound for LFNST masks."
    )
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument(
        "--mu",
        type=parse_csv_numbers,
        default=parse_csv_numbers("0,1e-6,1e-5,1e-4,1e-3,1e-2,1e-1,1,10,100,1000"),
        help="comma-separated Lagrange multipliers in ns per RD-cost unit",
    )
    parser.add_argument("--targets", type=parse_csv_numbers, default=parse_csv_numbers("5,8,10,12"))
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-csv", type=Path)
    args = parser.parse_args()

    try:
        rows = list(iter_rows(args.logs))
    except ValueError as exc:
        parser.error(str(exc))
    if not rows:
        parser.error("no complete RDO rows with finite costs and candidate timing")

    sweep = [evaluate(rows, mu) for mu in args.mu]
    total_candidate_time = sum(row["times"][1] + row["times"][2] for row in rows)
    profiles = {}
    for target in args.targets:
        target_ratio = target / 100.0
        point = min(
            sweep,
            key=lambda item: (
                abs(float(item["time_saving_ratio"]) - target_ratio),
                float(item["total_rd_loss"]),
            ),
        )
        profiles[f"T{target:g}"] = point

    result = {
        "rows": len(rows),
        "total_candidate_rdo_time_ns": int(round(total_candidate_time)),
        "sweep": sweep,
        "profiles": profiles,
        "input_logs": [str(path) for path in args.logs],
    }

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.out_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "mu",
                    "total_time_saved_ns",
                    "time_saving_ratio",
                    "total_rd_loss",
                    "mean_rd_loss",
                    "removed_candidates",
                    "candidate_reduction",
                    "mask_0",
                    "mask_01",
                    "mask_02",
                    "mask_012",
                ],
            )
            writer.writeheader()
            for point in sweep:
                counts = point["mask_counts"]
                writer.writerow(
                    {
                        **{key: point[key] for key in writer.fieldnames[:7]},
                        "mask_0": counts["0"],
                        "mask_01": counts["0,1"],
                        "mask_02": counts["0,2"],
                        "mask_012": counts["0,1,2"],
                    }
                )
    if not args.out_json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
